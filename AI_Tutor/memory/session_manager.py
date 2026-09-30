import os
from datetime import datetime

from database.supabase_client import supabase


class SessionOwnershipError(Exception):
    """
    Raised when a session_id doesn't exist, or exists but doesn't belong
    to the SessionManager's authenticated user_id. Deliberately a plain
    exception (this module stays framework-free) — translated to an HTTP
    404 in exactly one place, main.py's exception handler, so "not found"
    and "not yours" are indistinguishable to the caller and neither leaks
    whether the session_id exists for someone else.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        super().__init__(f"Session '{session_id}' not found.")


class SessionManager:

    def __init__(
        self,
        user_id: str
    ):
        # user_id is the verified Supabase Auth UUID (JWT `sub` claim),
        # established once by auth/jwt_bearer.py's get_current_user() and
        # threaded down through the service layer — never a client-
        # supplied value. Every query below scopes by this.

        if not user_id:

            raise ValueError(
                "user_id cannot be empty."
            )

        self.user_id = user_id

    # =====================================
    # OWNERSHIP GUARD
    # =====================================
    # sessions-table methods below already filter by
    # .eq("user_id", self.user_id) directly, so a mismatched session_id
    # naturally behaves like "not found" with no extra check needed.
    # messages/pdfs/selected_pdfs have no user_id column of their own —
    # ownership is only transitive through session_id — so methods that
    # touch those tables call this first.

    def _assert_session_owned(
        self,
        session_id: str
    ):

        if not self.session_exists(session_id):

            raise SessionOwnershipError(session_id)

    # =====================================
    # CREATE SESSION
    # =====================================

    def create_session(
        self,
        title: str = "New Chat"
    ):

        result = (
            supabase
            .table("sessions")
            .insert(
                {
                    "user_id": self.user_id,
                    "title": title,
                    "summary": ""
                }
            )
            .execute()
        )

        return result.data[0]["id"]

    # =====================================
    # LOAD SESSION
    # =====================================

    def load_session(
        self,
        session_id: str
    ):

        result = (
            supabase
            .table("sessions")
            .select("*")
            .eq(
                "id",
                session_id
            )
            .eq(
                "user_id",
                self.user_id
            )
            .execute()
        )

        if not result.data:

            return None

        session = result.data[0]

        return {

            "session_id": session["id"],

            "title": session["title"],

            "summary": session.get(
                "summary",
                ""
            ),

            "created_at": session[
                "created_at"
            ]
        }

    # =====================================
    # SESSION EXISTS
    # =====================================

    def session_exists(
        self,
        session_id: str
    ):

        result = (
            supabase
            .table("sessions")
            .select("id")
            .eq(
                "id",
                session_id
            )
            .eq(
                "user_id",
                self.user_id
            )
            .execute()
        )

        return len(result.data) > 0

    # =====================================
    # GET SESSION
    # =====================================

    def get_session(
        self,
        session_id: str
    ):

        return self.load_session(
            session_id
        )
    # =====================================
    # LIST SESSIONS
    # =====================================

    def list_sessions(
        self
    ):

        result = (
            supabase
            .table("sessions")
            .select("*")
            .eq(
                "user_id",
                self.user_id
            )
            .order(
                "created_at",
                desc=True
            )
            .execute()
        )

        sessions = []

        for row in result.data:

            sessions.append(
                {

                    "session_id": row["id"],

                    "title": row.get(
                        "title",
                        "New Chat"
                    ),

                    "created_at": row.get(
                        "created_at",
                        ""
                    )
                }
            )

        return sessions

    # =====================================
    # UPDATE TITLE
    # =====================================

    def update_title(
        self,
        session_id: str,
        new_title: str
    ):

        (
            supabase
            .table("sessions")
            .update(
                {
                    "title": new_title
                }
            )
            .eq(
                "id",
                session_id
            )
            .eq(
                "user_id",
                self.user_id
            )
            .execute()
        )

        return True

    # =====================================
    # UPDATE SUMMARY
    # =====================================

    def update_summary(
        self,
        session_id: str,
        summary: str
    ):

        (
            supabase
            .table("sessions")
            .update(
                {
                    "summary": summary
                }
            )
            .eq(
                "id",
                session_id
            )
            .eq(
                "user_id",
                self.user_id
            )
            .execute()
        )

        return True

    # =====================================
    # GET HISTORY
    # =====================================
    # Ordered by the explicit "sequence" column, NOT created_at.
    # save_history() bulk-inserts a whole conversation in a single
    # request, and Supabase/Postgres can assign identical (or
    # out-of-order-arriving) created_at timestamps to rows inserted in
    # the same statement, which previously meant message order was not
    # guaranteed to survive a save/reload round trip.

    def get_history(
        self,
        session_id: str
    ):

        self._assert_session_owned(session_id)

        result = (

            supabase

            .table("messages")

            .select("*")

            .eq(
                "session_id",
                session_id
            )

            .order(
                "sequence"
            )

            .order(
                "created_at"
            )

            .execute()

        )

        history = []

        for row in result.data:

            # ------------------------------
            # NEW FORMAT (JSONB)
            # ------------------------------

            if row.get(
                "message_data"
            ):

                history.append(
                    row["message_data"]
                )

            # ------------------------------
            # BACKWARD COMPATIBILITY
            # ------------------------------

            else:

                history.append(

                    {

                        "role": row.get(
                            "role",
                            "assistant"
                        ),

                        "content": row.get(
                            "content",
                            ""
                        )

                    }

                )

        return history

    # =====================================
    # SAVE HISTORY
    # =====================================
    # This is the single authoritative write path for a session's
    # conversation. Every message gets an explicit "sequence" number
    # (its index in the list), so restore order is deterministic
    # regardless of database timestamp precision or insert ordering.
    #
    # NOTE: requires a "sequence" integer column on the "messages"
    # table. If it doesn't exist yet, run:
    #   ALTER TABLE messages ADD COLUMN sequence integer;
    # Existing rows will have NULL sequence and will sort after rows
    # that do have one; only new saves need the column.

    def save_history(
        self,
        session_id: str,
        history: list
    ):

        self._assert_session_owned(session_id)

        # ------------------------------
        # Remove old history
        # ------------------------------

        (

            supabase

            .table("messages")

            .delete()

            .eq(
                "session_id",
                session_id
            )

            .execute()

        )

        if not history:

            return True

        rows = []

        for index, message in enumerate(history):

            rows.append(

                {

                    "session_id": session_id,

                    "sequence": index,

                    "role": message.get(
                        "role",
                        "assistant"
                    ),

                    "content": message.get(
                        "content",
                        ""
                    ),

                    # ----------------------
                    # COMPLETE MESSAGE
                    # ----------------------

                    "message_data": message

                }

            )

        (

            supabase

            .table("messages")

            .insert(
                rows
            )

            .execute()

        )

        return True
    # =====================================
    # DELETE SESSION
    # =====================================

    def delete_session(
        self,
        session_id: str
    ):
        """
        Deletes a session and everything that belongs to it: its
        Supabase Storage PDFs, its vector chunks, selected-PDF and PDF
        metadata rows, messages, and finally the session row itself.

        Safety:
        - Ownership is verified first; every delete below is scoped by
          this session_id (the sessions row also by user_id), so another
          user's or session's data can't be touched.
        - Storage objects are only removed if they live under this
          session's own "{session_id}/" prefix AND no other session's
          pdfs row points at the same path.

        Order: dependents first, the session row LAST, and every step
        raises on failure. A failure part-way therefore leaves the
        session listed (so the user can simply delete it again — every
        step is idempotent) rather than an invisible session whose
        chunks/files are orphaned forever. Storage goes first: it's the
        step most likely to fail, and failing there changes nothing.
        """

        self._assert_session_owned(session_id)

        # Storage PDFs
        self._delete_session_storage(session_id)

        # Vector chunks
        (
            supabase
            .table("document_chunks")
            .delete()
            .eq(
                "session_id",
                session_id
            )
            .execute()
        )

        # Delete selected PDFs

        (
            supabase
            .table("selected_pdfs")
            .delete()
            .eq(
                "session_id",
                session_id
            )
            .execute()
        )

        # Delete PDF metadata

        (
            supabase
            .table("pdfs")
            .delete()
            .eq(
                "session_id",
                session_id
            )
            .execute()
        )

        # Delete messages

        (
            supabase
            .table("messages")
            .delete()
            .eq(
                "session_id",
                session_id
            )
            .execute()
        )

        # Delete session

        (
            supabase
            .table("sessions")
            .delete()
            .eq(
                "id",
                session_id
            )
            .eq(
                "user_id",
                self.user_id
            )
            .execute()
        )

        return True

    _STORAGE_BUCKET = "pdfs"

    def _delete_session_storage(
        self,
        session_id: str
    ):
        """
        Removes this session's PDFs from Supabase Storage. Candidate
        paths are the session's recorded pdf_path values plus anything
        still under its "{session_id}/" folder (e.g. left by a failed
        upload), restricted to that prefix. Paths another session's pdfs
        row still references are kept. Raises if a file can't be
        removed, so the caller stops before deleting any metadata.
        """

        prefix = f"{session_id}/"
        bucket = supabase.storage.from_(self._STORAGE_BUCKET)

        recorded = (
            supabase
            .table("pdfs")
            .select("pdf_path")
            .eq("session_id", session_id)
            .execute()
        ).data or []

        listed = bucket.list(
            session_id,
            {"limit": 1000}
        ) or []

        paths = {
            row["pdf_path"]
            for row in recorded
            if row.get("pdf_path")
        } | {
            prefix + item["name"]
            for item in listed
            if item.get("name")
        }

        # Never outside this session's own folder.
        paths = {path for path in paths if path.startswith(prefix)}

        if not paths:
            return

        shared = (
            supabase
            .table("pdfs")
            .select("pdf_path")
            .in_("pdf_path", sorted(paths))
            .neq("session_id", session_id)
            .execute()
        ).data or []

        paths -= {row["pdf_path"] for row in shared}

        if not paths:
            return

        bucket.remove(sorted(paths))

        remaining = {
            prefix + item["name"]
            for item in (bucket.list(session_id, {"limit": 1000}) or [])
            if item.get("name")
        }

        not_removed = paths & remaining

        if not_removed:

            raise RuntimeError(
                f"Could not remove {len(not_removed)} storage file(s) "
                f"for session {session_id}; session left intact."
            )

    # =====================================
    # ADD PDF
    # =====================================

    def add_pdf(
        self,
        session_id: str,
        pdf_name: str,
        pdf_path: str
    ):

        self._assert_session_owned(session_id)

        existing = (
            supabase
            .table("pdfs")
            .select("id")
            .eq(
                "session_id",
                session_id
            )
            .eq(
                "pdf_name",
                pdf_name
            )
            .execute()
        )

        if existing.data:

            return True

        (
            supabase
            .table("pdfs")
            .insert(
                {
                    "session_id": session_id,
                    "pdf_name": pdf_name,
                    "pdf_path": pdf_path
                }
            )
            .execute()
        )

        return True

    # =====================================
    # REMOVE PDF
    # =====================================

    def remove_pdf(
        self,
        session_id: str,
        pdf_name: str
    ):

        self._assert_session_owned(session_id)

        (
            supabase
            .table("selected_pdfs")
            .delete()
            .eq(
                "session_id",
                session_id
            )
            .eq(
                "pdf_name",
                pdf_name
            )
            .execute()
        )

        (
            supabase
            .table("pdfs")
            .delete()
            .eq(
                "session_id",
                session_id
            )
            .eq(
                "pdf_name",
                pdf_name
            )
            .execute()
        )

        return True

    # =====================================
    # GET PDFS
    # =====================================

    def get_pdfs(
        self,
        session_id: str
    ):

        self._assert_session_owned(session_id)

        result = (
            supabase
            .table("pdfs")
            .select("*")
            .eq(
                "session_id",
                session_id
            )
            .order(
                "uploaded_at"
            )
            .execute()
        )

        pdfs = []

        for row in result.data:

            pdfs.append(
                {
                    "name": row["pdf_name"],
                    "path": row["pdf_path"],
                    "uploaded_at": row[
                        "uploaded_at"
                    ]
                }
            )

        return pdfs
    # =====================================
    # SAVE SELECTED PDFS
    # =====================================

    def save_selected_pdfs(
        self,
        session_id: str,
        selected_pdfs: list
    ):

        self._assert_session_owned(session_id)

        # Remove previous selection

        (
            supabase
            .table("selected_pdfs")
            .delete()
            .eq(
                "session_id",
                session_id
            )
            .execute()
        )

        if not selected_pdfs:

            return True

        rows = []

        for pdf_name in selected_pdfs:

            rows.append(
                {
                    "session_id": session_id,
                    "pdf_name": pdf_name
                }
            )

        (
            supabase
            .table("selected_pdfs")
            .insert(
                rows
            )
            .execute()
        )

        return True

    # =====================================
    # GET SELECTED PDFS
    # =====================================

    def get_selected_pdfs(
        self,
        session_id: str
    ):

        self._assert_session_owned(session_id)

        result = (
            supabase
            .table("selected_pdfs")
            .select("pdf_name")
            .eq(
                "session_id",
                session_id
            )
            .execute()
        )

        return [
            row["pdf_name"]
            for row in result.data
        ]

    # =====================================
    # CLEAR SELECTED PDFS
    # =====================================

    def clear_selected_pdfs(
        self,
        session_id: str
    ):

        self._assert_session_owned(session_id)

        (
            supabase
            .table("selected_pdfs")
            .delete()
            .eq(
                "session_id",
                session_id
            )
            .execute()
        )

        return True

    # =====================================
    # UPDATE SESSION
    # =====================================

    def update_session(
        self,
        session_id: str,
        data: dict
    ):

        (
            supabase
            .table("sessions")
            .update(
                {
                    "title": data.get(
                        "title",
                        "New Chat"
                    ),

                    "summary": data.get(
                        "summary",
                        ""
                    )
                }
            )
            .eq(
                "id",
                session_id
            )
            .eq(
                "user_id",
                self.user_id
            )
            .execute()
        )

        if "history" in data:

            self.save_history(
                session_id,
                data["history"]
            )

        if "selected_pdfs" in data:

            self.save_selected_pdfs(
                session_id,
                data["selected_pdfs"]
            )

        return True

    # =====================================
    # GET PDF PATHS
    # =====================================

    def get_pdf_paths(
        self,
        session_id: str
    ):

        pdfs = self.get_pdfs(
            session_id
        )

        return [
            pdf["path"]
            for pdf in pdfs
        ]