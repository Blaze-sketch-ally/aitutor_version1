from pydantic import BaseModel, Field

class ChatRequest(BaseModel):

    username: str

    session_id: str

    query: str

    selected_pdfs: list[str] = Field(default_factory=list)