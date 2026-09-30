from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    username: str
    title: str = "New Chat"


class UpdateSessionRequest(BaseModel):
    username: str
    title: str


class SessionResponse(BaseModel):
    session_id: str
    title: str