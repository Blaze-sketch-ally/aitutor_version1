from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AttachmentType(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    OTHER_SUPPORTED_FILE = "other_supported_file"
    UNSUPPORTED = "unsupported"


class AttachmentMetadata(BaseModel):
    """
    Structural metadata for one attachment on a chat turn.

    Intentionally provider/pipeline-agnostic: an IMAGE entry carries a
    temp_path for VisionAgent to read (ephemeral, deleted after the
    request — see AttachmentService), while a PDF entry only carries a
    reference to an already-uploaded/indexed file (PDFs are never
    processed here — that stays entirely in rag/ingest.py). Keeping
    both shapes in the same model lets one list represent a mixed
    IMAGE + PDF attachment set for a later routing step, without this
    module touching the existing PDF/RAG pipeline at all.
    """

    attachment_type: AttachmentType
    filename: str
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    temp_path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None


class VisionAnalysisResult(BaseModel):
    """
    Structured output of VisionAgent.analyze_images().

    Fields mirror the existing per-agent "safe fallback" convention
    used across this codebase (TutorAgent, DiagramAgent, etc.): on any
    failure, `description` carries a user-facing explanation and
    `confidence` is 0.0, rather than raising up to the orchestrator.
    """

    description: str
    content_type: str = "unknown"
    detected_text: Optional[str] = None
    concepts: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    domain: Optional[str] = None
    confidence: float = 0.0
    instruction: Optional[str] = None
    image_count: int = 0
    model_used: Optional[str] = None
    raw_response: Optional[str] = None
