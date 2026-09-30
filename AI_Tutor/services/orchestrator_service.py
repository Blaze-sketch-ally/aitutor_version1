from agents.orchestrator import Orchestrator


def load_orchestrator(
    user_id: str,
    session_id: str
):
    return Orchestrator(
        user_id=user_id,
        session_id=session_id
    )