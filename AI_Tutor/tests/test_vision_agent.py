from unittest.mock import patch

import agents.vision_agent as vision_agent_module
from agents.vision_agent import VisionAgent


def _agent():
    return VisionAgent(provider="groq", model="qwen/qwen3.6-27b")


class TestNoImages:

    def test_returns_safe_result_without_calling_model(self):
        agent = _agent()

        with patch.object(vision_agent_module, "route_vision") as mock_route:
            result = agent.analyze_images(images=[])

        mock_route.assert_not_called()
        assert result["image_count"] == 0
        assert "No image" in result["description"]


class TestImageOnlyQuery:

    def test_valid_json_response_is_parsed(self):
        agent = _agent()

        fake_response = """
        {
          "description": "This appears to be a textbook page about CPU scheduling, covering FCFS, SJF and Round Robin.",
          "content_type": "textbook_page",
          "detected_text": "CPU Scheduling Algorithms",
          "concepts": ["FCFS", "SJF", "Round Robin"],
          "objects": ["heading", "diagram"],
          "domain": "computer_science",
          "confidence": 0.87
        }
        """

        with patch.object(
            vision_agent_module, "route_vision", return_value=fake_response
        ) as mock_route:
            result = agent.analyze_images(
                images=[b"fake-png-bytes"],
                image_mime_types=["image/png"],
            )

        mock_route.assert_called_once()
        _, kwargs = mock_route.call_args
        assert kwargs["images"] == [b"fake-png-bytes"]
        assert kwargs["provider"] == "groq"

        assert result["content_type"] == "textbook_page"
        assert "CPU scheduling" in result["description"]
        assert result["concepts"] == ["FCFS", "SJF", "Round Robin"]
        assert result["confidence"] == 0.87
        assert result["instruction"] is None  # no instruction was given
        assert result["image_count"] == 1


class TestImagePlusInstruction:

    def test_instruction_is_preserved_in_result(self):
        agent = _agent()

        fake_response = (
            '{"description": "A simple explanation of the diagram.", '
            '"confidence": 0.7}'
        )

        with patch.object(
            vision_agent_module, "route_vision", return_value=fake_response
        ):
            result = agent.analyze_images(
                images=[b"fake-bytes"],
                instruction="Explain this in simple terms.",
            )

        assert result["instruction"] == "Explain this in simple terms."


class TestMultipleImages:

    def test_multiple_images_passed_through_to_provider(self):
        agent = _agent()

        fake_response = '{"description": "Two related diagrams.", "confidence": 0.6}'

        with patch.object(
            vision_agent_module, "route_vision", return_value=fake_response
        ) as mock_route:
            result = agent.analyze_images(
                images=[b"img1", b"img2"],
                image_mime_types=["image/png", "image/jpeg"],
                instruction="Compare these images.",
            )

        _, kwargs = mock_route.call_args
        assert len(kwargs["images"]) == 2
        assert kwargs["image_mime_types"] == ["image/png", "image/jpeg"]
        assert result["image_count"] == 2


class TestModelFailure:

    def test_provider_exception_returns_safe_fallback(self):
        agent = _agent()

        with patch.object(
            vision_agent_module,
            "route_vision",
            side_effect=RuntimeError("Groq API unavailable"),
        ):
            result = agent.analyze_images(images=[b"fake-bytes"])

        assert result["confidence"] == 0.0
        assert "couldn't analyze" in result["description"]

    def test_invalid_or_missing_configuration_does_not_raise(self):
        agent = _agent()

        with patch.object(
            vision_agent_module,
            "route_vision",
            side_effect=ValueError("Unsupported vision provider: bogus"),
        ):
            result = agent.analyze_images(images=[b"fake-bytes"])

        assert result["confidence"] == 0.0
        assert result["image_count"] == 1


class TestNonJsonModelResponse:

    def test_prose_response_falls_back_to_raw_text_as_description(self):
        agent = _agent()

        prose = (
            "Sure! This image shows a hand-drawn circuit diagram with "
            "a resistor and a capacitor in series."
        )

        with patch.object(
            vision_agent_module, "route_vision", return_value=prose
        ):
            result = agent.analyze_images(images=[b"fake-bytes"])

        assert result["description"] == prose
        assert result["raw_response"] == prose
        assert 0 < result["confidence"] < 1
