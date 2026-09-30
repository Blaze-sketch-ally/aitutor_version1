from memory.session_manager import SessionManager


class SessionService:

    def create_session(
        self,
        user_id: str,
        title: str = "New Chat"
    ):

        manager = SessionManager(
            user_id=user_id
        )

        session_id = manager.create_session(
            title=title
        )

        return {
            "success": True,
            "session_id": session_id,
            "title": title
        }

    def list_sessions(
        self,
        user_id: str
    ):

        manager = SessionManager(
            user_id=user_id
        )

        return manager.list_sessions()

    def get_session(
        self,
        user_id: str,
        session_id: str
    ):

        manager = SessionManager(
            user_id=user_id
        )

        return manager.get_session(
            session_id
        )

    def delete_session(
        self,
        user_id: str,
        session_id: str
    ):

        manager = SessionManager(
            user_id=user_id
        )

        manager.delete_session(
            session_id
        )

        return {
            "success": True
        }

    def rename_session(
        self,
        user_id: str,
        session_id: str,
        title: str
    ):

        manager = SessionManager(
            user_id=user_id
        )

        manager.update_title(
            session_id,
            title
        )

        return {
            "success": True
        }

    def get_history(
        self,
        user_id: str,
        session_id: str
    ):

        manager = SessionManager(
            user_id=user_id
        )

        return manager.get_history(
            session_id
        )

    def save_history(
        self,
        user_id: str,
        session_id: str,
        messages: list
    ):

        manager = SessionManager(
            user_id=user_id
        )

        manager.save_history(
            session_id,
            messages
        )

        return {
            "success": True
        }

    def truncate_history(
        self,
        user_id: str,
        session_id: str,
        keep_count: int
    ):
        """
        Keeps only the first `keep_count` messages of a session's
        history, discarding the rest, then saves that back through the
        existing save_history() delete-then-reinsert path. Used by the
        edit-user-message and regenerate-response chat features: both
        need to drop a trailing slice of history before resending, and
        SessionManager.save_history() already fully replaces a
        session's history from a plain list, so this just reuses that
        instead of adding a new persistence mechanism.
        """

        manager = SessionManager(
            user_id=user_id
        )

        history = manager.get_history(session_id) or []

        keep_count = max(0, keep_count)

        truncated = history[:keep_count]

        manager.save_history(
            session_id,
            truncated
        )

        return {
            "success": True,
            "remaining": len(truncated)
        }

    # ==================================================
    # NEW — PDF selection (mirrors app_new.py's sidebar,
    # which calls these same SessionManager methods directly)
    # ==================================================

    def get_pdfs(
        self,
        user_id: str,
        session_id: str
    ):
        """
        Returns the list of PDFs indexed for this session, e.g.
        [{"name": "Wireless Systems.pdf", ...}, ...] — same shape
        SessionManager.get_pdfs() already returns, used by app_new.py
        to populate st.session_state.uploaded_pdfs.
        """

        manager = SessionManager(
            user_id=user_id
        )

        return manager.get_pdfs(
            session_id
        )

    def get_selected_pdfs(
        self,
        user_id: str,
        session_id: str
    ):
        """
        Returns the subset of this session's PDFs currently selected
        for retrieval scope. Falls back to an empty list — same as
        app_new.py falling back to `uploaded_pdfs.copy()` when this
        comes back empty is a FRONTEND decision, not something this
        service should assume, so it stays a plain passthrough here.
        """

        manager = SessionManager(
            user_id=user_id
        )

        return manager.get_selected_pdfs(
            session_id
        )

    def save_selected_pdfs(
        self,
        user_id: str,
        session_id: str,
        selected_pdfs: list[str]
    ):

        manager = SessionManager(
            user_id=user_id
        )

        manager.save_selected_pdfs(
            session_id,
            selected_pdfs
        )

        return {
            "success": True,
            "selected_pdfs": selected_pdfs
        }

    def add_pdf(
        self,
        user_id: str,
        session_id: str,
        pdf_name: str,
        pdf_path: str
    ):
        """
        Records an already-uploaded-and-ingested PDF against this
        session (storage upload + chunk ingestion happen upstream, in
        api/pdf.py — this just persists the record, same as
        app_new.py's session_manager.add_pdf() call after a
        successful ingest).
        """

        manager = SessionManager(
            user_id=user_id
        )

        manager.add_pdf(
            session_id=session_id,
            pdf_name=pdf_name,
            pdf_path=pdf_path
        )

        return {
            "success": True,
            "pdf_name": pdf_name
        }