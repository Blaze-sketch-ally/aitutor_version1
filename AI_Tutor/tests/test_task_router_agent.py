from unittest.mock import MagicMock, patch

from agents.task_router_agent import TaskRouterAgent


class TestRouteTask:

    @patch("agents.task_router_agent.route")
    def test_registry_hit_returns_action_and_message(self, mock_route):

        mock_route.side_effect = [
            "aws certification",
            "You can register on the official AWS site."
        ]

        agent = TaskRouterAgent()
        result = agent.route_task("where can I register for aws certification")

        assert result["action"] is not None
        assert result["action"]["source_type"] == "official"
        assert result["action"]["url"].startswith("https://")
        assert result["message"] == "You can register on the official AWS site."

    @patch("agents.task_router_agent.route")
    def test_no_resolution_returns_safe_empty(self, mock_route):

        mock_route.return_value = "completely obscure unresolvable service xyz"

        agent = TaskRouterAgent()
        agent.resolver.tavily = MagicMock()
        agent.resolver.tavily.search.return_value = []

        result = agent.route_task("where can I do the obscure thing")

        assert result == {"message": None, "action": None}

    @patch("agents.task_router_agent.route")
    def test_topic_resolution_failure_is_caught_gracefully(self, mock_route):

        mock_route.side_effect = RuntimeError("LLM down")

        agent = TaskRouterAgent()
        result = agent.route_task("where can I apply for a passport")

        assert result == {"message": None, "action": None}

    @patch("agents.task_router_agent.route")
    def test_tavily_failure_is_caught_gracefully(self, mock_route):

        mock_route.return_value = "some obscure service"

        agent = TaskRouterAgent()
        agent.resolver.tavily = MagicMock()
        agent.resolver.tavily.search.side_effect = RuntimeError("tavily down")

        result = agent.route_task("where can I do the obscure thing")

        assert result == {"message": None, "action": None}

    @patch("agents.task_router_agent.route")
    def test_response_shape_matches_design(self, mock_route):

        mock_route.side_effect = [
            "aws certification",
            "You can register on the official AWS site."
        ]

        agent = TaskRouterAgent()
        result = agent.route_task("where can I register for aws certification")

        assert set(result.keys()) == {"message", "action"}
        assert set(result["action"].keys()) == {"label", "url", "service", "source_type"}
        assert result["action"]["source_type"] in ("official", "unverified")
