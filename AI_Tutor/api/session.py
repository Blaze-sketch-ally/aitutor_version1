from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.jwt_bearer import CurrentUser, get_current_user
from memory.session_manager import SessionOwnershipError
from services.session_service import SessionService


router = APIRouter(prefix="/api/session", tags=["session"])

session_service = SessionService()


class CreateSessionRequest(BaseModel):
    title: str = "New Chat"


class RenameSessionRequest(BaseModel):
    title: str


class SaveSelectedPDFsRequest(BaseModel):
    selected_pdfs: list[str]


class TruncateHistoryRequest(BaseModel):
    keep_count: int


@router.post("/create")
def create_session(
    req: CreateSessionRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    return session_service.create_session(
        user_id=current_user.id,
        title=req.title
    )


@router.get("/list")
def list_sessions(
    current_user: CurrentUser = Depends(get_current_user)
):
    return session_service.list_sessions(user_id=current_user.id)


@router.get("/{session_id}")
def get_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    return session_service.get_session(
        user_id=current_user.id,
        session_id=session_id
    )


@router.get("/{session_id}/history")
def get_history(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    return session_service.get_history(
        user_id=current_user.id,
        session_id=session_id
    )


@router.put("/{session_id}/rename")
def rename_session(
    session_id: str,
    req: RenameSessionRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    return session_service.rename_session(
        user_id=current_user.id,
        session_id=session_id,
        title=req.title
    )


@router.delete("/{session_id}")
def delete_session(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    try:
        return session_service.delete_session(
            user_id=current_user.id,
            session_id=session_id
        )
    except SessionOwnershipError:
        raise
    except Exception as e:
        # Cleanup stops before removing the session row on any failure,
        # so the session is still there and a retry is safe.
        print(f"Session delete failed (session={session_id}): {e}")
        raise HTTPException(
            status_code=500,
            detail="The session could not be fully deleted. Please try again."
        )


@router.get("/{session_id}/pdfs")
def get_pdfs(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    return session_service.get_pdfs(
        user_id=current_user.id,
        session_id=session_id
    )


@router.get("/{session_id}/selected-pdfs")
def get_selected_pdfs(
    session_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    return session_service.get_selected_pdfs(
        user_id=current_user.id,
        session_id=session_id
    )


@router.put("/{session_id}/selected-pdfs")
def save_selected_pdfs(
    session_id: str,
    req: SaveSelectedPDFsRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    return session_service.save_selected_pdfs(
        user_id=current_user.id,
        session_id=session_id,
        selected_pdfs=req.selected_pdfs
    )


@router.put("/{session_id}/truncate")
def truncate_history(
    session_id: str,
    req: TruncateHistoryRequest,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Drops history after position `keep_count`, used by the frontend's
    edit-message and regenerate-response features to remove the
    stale message(s) before resending — see
    services/session_service.py::truncate_history().
    """
    return session_service.truncate_history(
        user_id=current_user.id,
        session_id=session_id,
        keep_count=req.keep_count
    )
