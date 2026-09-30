from typing import List, Dict, Optional

from memory.session_manager import SessionManager


class ChatMemory:
    """
    In-process conversation buffer used by the Orchestrator to build
    LLM context (history_text, last-message lookups, etc.) during a
    single run() call.

    IMPORTANT — persistence ownership:
    app.py owns the authoritative copy of chat history (the rich
    per-message dicts with videos/papers/notes/quiz/sources) and is
    the only caller that should routinely persist it via
    SessionManager.save_history(). ChatMemory used to call
    SessionManager.save_history() on every add_message(), which wrote
    a second, *less complete* copy of the conversation to the same
    table and could stomp on app.py's richer save — see add_message()
    for details. add_message() now defaults to NOT persisting; pass
    persist=True only if this ChatMemory instance is being used
    somewhere that does NOT already have its own save step.
    """

    def __init__(
        self,
        user_id: str,
        session_id: str
    ):

        self.user_id = user_id
        self.session_id = session_id

        self.session_manager = SessionManager(
            user_id=user_id
        )

        # ----------------------------------
        # LOAD EXISTING HISTORY
        # ----------------------------------

        self.history: List[Dict] = (
            self.session_manager.get_history(
                session_id
            )
        )

    # ----------------------------------
    # SAVE MEMORY
    # ----------------------------------

    def save(self):

        self.session_manager.save_history(
            session_id=self.session_id,
            history=self.history
        )

    # ----------------------------------
    # LOAD MEMORY
    # ----------------------------------

    def load(self):

        self.history = (
            self.session_manager.get_history(
                self.session_id
            )
        )

    # ----------------------------------
    # ADD MESSAGE (Backward Compatible)
    # ----------------------------------

    def add_message(
        self,
        role: Optional[str] = None,
        content: Optional[str] = None,
        message: Optional[Dict] = None,
        persist: bool = False
    ):

        # New structured message
        if message is not None:

            self.history.append(message)

        # Old style
        else:

            self.history.append(
                {
                    "role": role,
                    "content": content
                }
            )

        # Only write through to Supabase if explicitly asked to.
        # Orchestrator calls this with the default (persist=False)
        # because app.py always saves the complete, rich message
        # right after run() returns — writing here too would save a
        # second, thinner copy (no videos/papers/sources) and could
        # race with / overwrite app.py's save.
        if persist:

            self.save()

    # ----------------------------------
    # UPDATE LAST MESSAGE
    # ----------------------------------

    def update_last_message(
        self,
        updates: Dict,
        persist: bool = False
    ):

        if not self.history:

            return

        self.history[-1].update(
            updates
        )

        if persist:

            self.save()

    # ----------------------------------
    # GET HISTORY
    # ----------------------------------

    def get_history(
        self,
        max_turns: int = 10
    ):

        return self.history[-max_turns:]

    # ----------------------------------
    # GET FULL HISTORY
    # ----------------------------------

    def get_full_history(self):

        return self.history

    # ----------------------------------
    # HISTORY AS TEXT
    # ----------------------------------

    def get_history_text(
        self,
        max_turns: int = 10,
        max_chars: int | None = None,
        latest_max_chars: int | None = None,
        start: int | None = None
    ) -> str:
        """
        History as "ROLE: text" lines, for prompts.

        max_turns        — last N messages (ignored when `start` is given)
        start            — render messages[start:] instead
        max_chars        — cap per message (long answers are clipped
                           with a marker, so a follow-up still sees the
                           gist without resending whole answers)
        latest_max_chars — larger cap for the final two messages, which
                           follow-ups usually refer to
        """

        recent = (
            self.history[start:] if start is not None
            else self.history[-max_turns:]
        )

        return self.format_messages(recent, max_chars, latest_max_chars)

    @staticmethod
    def format_messages(
        messages: List[Dict],
        max_chars: int | None = None,
        latest_max_chars: int | None = None
    ) -> str:

        history_text = ""

        for index, msg in enumerate(messages):

            limit = (
                latest_max_chars
                if latest_max_chars and index >= len(messages) - 2
                else max_chars
            )

            role = msg.get(
                "role",
                "assistant"
            )

            content = msg.get(
                "content",
                ""
            ) or ""

            if limit and len(content) > limit:
                content = content[:limit].rstrip() + " …[truncated]"

            # Mark earlier assistant replies as conversation, so no agent
            # mistakes a past (possibly unsupported) answer for something
            # the uploaded document says. See prompts/grounding.py.
            label = (
                "ASSISTANT (earlier reply, not document evidence)"
                if role == "assistant"
                else role.upper()
            )

            history_text += (
                f"{label}: "
                f"{content}\n"
            )

        return history_text.strip()

    # ----------------------------------
    # LAST USER MESSAGE
    # ----------------------------------

    def get_last_user_message(self):

        for msg in reversed(
            self.history
        ):

            if msg.get(
                "role"
            ) == "user":

                return msg.get(
                    "content",
                    ""
                )

        return ""

    # ----------------------------------
    # LAST ASSISTANT MESSAGE
    # ----------------------------------

    def get_last_assistant_message(self):

        for msg in reversed(
            self.history
        ):

            if msg.get(
                "role"
            ) == "assistant":

                return msg.get(
                    "content",
                    ""
                )

        return ""

    # ----------------------------------
    # LAST ASSISTANT OBJECT
    # ----------------------------------

    def get_last_assistant_message_object(self):

        for msg in reversed(
            self.history
        ):

            if msg.get(
                "role"
            ) == "assistant":

                return msg

        return {}

    # ----------------------------------
    # TOTAL MESSAGES
    # ----------------------------------

    def size(self):

        return len(
            self.history
        )

    # ----------------------------------
    # CLEAR MEMORY
    # ----------------------------------

    def clear(self, persist: bool = True):

        self.history = []

        if persist:

            self.save()