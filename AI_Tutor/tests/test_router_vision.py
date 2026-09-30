import os
from unittest.mock import patch

import pytest

import models.router as router_module


class TestRouteVisionDispatch:

    def test_groq_provider_calls_vision_client_with_default_model(self):
        with patch.object(
            router_module, "groq_generate_vision", return_value="ok"
        ) as mock_generate, patch.dict(
            os.environ, {"VISION_MODEL": "qwen/qwen3.6-27b"}
        ):
            result = router_module.route_vision(
                prompt="describe this",
                images=[b"bytes"],
            )

        assert result == "ok"
        mock_generate.assert_called_once_with(
            prompt="describe this",
            images=[b"bytes"],
            image_mime_types=None,
            model="qwen/qwen3.6-27b",
        )

    def test_explicit_model_overrides_env_default(self):
        with patch.object(
            router_module, "groq_generate_vision", return_value="ok"
        ) as mock_generate:
            router_module.route_vision(
                prompt="describe this",
                images=[b"bytes"],
                model="some-other-vision-model",
            )

        _, kwargs = mock_generate.call_args
        assert kwargs["model"] == "some-other-vision-model"

    def test_unsupported_provider_raises(self):
        with pytest.raises(ValueError, match="Unsupported vision provider"):
            router_module.route_vision(
                prompt="describe this",
                images=[b"bytes"],
                provider="hf",
            )

    def test_existing_text_route_is_unaffected(self):
        """
        Regression guard: adding route_vision() must not change route()'s
        behavior for the existing text-only providers.
        """
        with patch.object(
            router_module, "groq_generate", return_value="hello"
        ) as mock_generate:
            result = router_module.route(prompt="hi", provider="groq")

        assert result == "hello"
        mock_generate.assert_called_once_with(
            prompt="hi", model=router_module.get_text_model()
        )

    def test_text_model_comes_from_env(self):
        with patch.dict(os.environ, {"TEXT_MODEL": "some-text-model"}), \
             patch.object(
                 router_module, "groq_generate", return_value="ok"
             ) as mock_generate:
            router_module.route(prompt="hi", provider="groq")

        mock_generate.assert_called_once_with(
            prompt="hi", model="some-text-model"
        )
