import os
import streamlit as st

from agents.orchestrator import Orchestrator
from rag.ingest import PDFIngestor
from auth.auth_manager import AuthManager
from memory.session_manager import SessionManager
from storage.storage_manager import StorageManager

# ==================================================
# PAGE CONFIG
# ==================================================

st.set_page_config(
    page_title="AI Tutor Agent",
    page_icon="🧠",
    layout="wide"
)

# ==================================================
# VIDEO CARD RENDERING (shared helper)
# ==================================================
# Used by both the chat-history replay loop and the live response
# block below, so the new fields (views/likes/duration/study segment)
# only need to be written once.

def _format_count(n):

    if n is None:
        return "N/A"

    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def render_video_card(video):

    if not isinstance(video, dict):
        return

    st.markdown(
        f"### {video.get('title', 'Untitled Video')}"
    )

    if video.get("channel"):

        st.write(
            f"**Channel:** {video['channel']}"
        )

    # -----------------------------
    # Stats line: views / likes / duration
    # -----------------------------

    stats_parts = []

    if video.get("views") is not None:
        stats_parts.append(f"👁 {_format_count(video['views'])} views")

    if video.get("likes") is not None:
        stats_parts.append(f"👍 {_format_count(video['likes'])} likes")

    if video.get("duration_minutes") is not None:
        stats_parts.append(f"⏱ {video['duration_minutes']} min")

    if stats_parts:
        st.caption(" · ".join(stats_parts))

    # -----------------------------
    # Study segment (best-matching timestamp)
    # -----------------------------

    segment = video.get("study_segment")

    if segment:

        st.markdown(
            f"📍 **Best section to study:** "
            f"{segment['start_label']} – {segment['end_label']}"
        )

        with st.expander("Preview this section"):
            st.write(segment.get("snippet", ""))

    # -----------------------------
    # Watch buttons
    # -----------------------------

    button_cols = st.columns(2) if segment else [st.container()]

    if video.get("url"):

        with button_cols[0]:
            st.link_button("▶ Watch Video", video["url"])

    if segment and video.get("url_at_timestamp"):

        with button_cols[1]:
            st.link_button(
                f"⏩ Jump to {segment['start_label']}",
                video["url_at_timestamp"]
            )


# ==================================================
# AUTHENTICATION
# ==================================================

auth = AuthManager()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "username" not in st.session_state:
    st.session_state.username = ""

if not st.session_state.logged_in:

    st.title("🔐 AI Tutor Login")

    tab1, tab2 = st.tabs(
        [
            "Login",
            "Register"
        ]
    )

    # =====================================
    # LOGIN
    # =====================================

    with tab1:

        username = st.text_input(
            "Username",
            key="login_user"
        )

        password = st.text_input(
            "Password",
            type="password",
            key="login_pass"
        )

        if st.button(
            "Login"
        ):

            username = username.strip().lower()

            result = auth.login_user(
                username,
                password
            )

            if result["success"]:

                st.session_state.logged_in = True

                st.session_state.username = username

                st.session_state.user_id = result.get(
                    "user_id"
                )

                st.session_state.session_id = None

                st.session_state.messages = []

                st.session_state.uploaded_pdfs = []

                st.session_state.selected_pdfs = []

                st.cache_resource.clear()

                st.rerun()

            else:

                st.error(
                    result["message"]
                )

    # =====================================
    # REGISTER
    # =====================================

    with tab2:

        username = st.text_input(
            "Username",
            key="register_user"
        )

        password = st.text_input(
            "Password",
            type="password",
            key="register_pass"
        )

        if st.button(
            "Register"
        ):

            username = username.strip().lower()

            result = auth.register_user(
                username,
                password
            )

            if result["success"]:

                st.success(
                    result["message"]
                )

            else:

                st.error(
                    result["message"]
                )

    st.stop()

# ==================================================
# SESSION MANAGER
# ==================================================

session_manager = SessionManager(
    st.session_state.username
)
#STORAGE MANAGER
storage = StorageManager()

# ==================================================
# SESSION STATE
# ==================================================

if "messages" not in st.session_state:

    st.session_state.messages = []

if "uploaded_pdfs" not in st.session_state:

    st.session_state.uploaded_pdfs = []

if "selected_pdfs" not in st.session_state:

    st.session_state.selected_pdfs = []

# ==================================================
# LOAD USER SESSIONS
# ==================================================

sessions = session_manager.list_sessions()

if (
    "session_id" not in st.session_state
    or st.session_state.session_id is None
):

    if sessions:

        latest_session = sessions[0]

        st.session_state.session_id = (
            latest_session["session_id"]
        )

        st.session_state.messages = (
            session_manager.get_history(
                latest_session["session_id"]
            )
        )

        pdfs = session_manager.get_pdfs(
            latest_session["session_id"]
        )

        st.session_state.uploaded_pdfs = [

            pdf["name"]

            for pdf in pdfs

        ]

        st.session_state.selected_pdfs = (
            session_manager.get_selected_pdfs(
                latest_session["session_id"]
            )
        )

        if not st.session_state.selected_pdfs:

            st.session_state.selected_pdfs = (
                st.session_state.uploaded_pdfs.copy()
            )

    else:

        new_session = (
            session_manager.create_session()
        )

        st.session_state.session_id = (
            new_session
        )

        st.session_state.messages = []

        st.session_state.uploaded_pdfs = []

        st.session_state.selected_pdfs = []

# ==================================================
# LOAD ORCHESTRATOR
# ==================================================

@st.cache_resource
def load_orchestrator(
    username,
    session_id
):

    return Orchestrator(
        username=username,
        session_id=session_id
    )


orchestrator = load_orchestrator(
    st.session_state.username,
    st.session_state.session_id
)

# ==================================================
# HEADER
# ==================================================

st.title("🧠 AI Tutor Agent")

st.markdown(
    """
Upload PDFs and chat naturally.

### Features

* Conversational AI Tutor
* PDF Question Answering
* Hybrid RAG Search
* Multi-PDF Support
* Quiz Generation
* Notes Generation
* Diagram Generation
* YouTube Recommendations
* Research Papers
* Session-based Memory
* Source Citations
"""
)

# ==================================================
# SIDEBAR
# ==================================================

st.sidebar.markdown(
    f"### 👤 Welcome {st.session_state.username}"
)

# ==================================================
# NEW CHAT
# ==================================================

if st.sidebar.button(
    "➕ New Chat",
    use_container_width=True
):

    new_session = session_manager.create_session()

    st.session_state.session_id = new_session

    st.session_state.messages = []

    st.session_state.uploaded_pdfs = []

    st.session_state.selected_pdfs = []

    st.cache_resource.clear()

    st.rerun()

# ==================================================
# LOGOUT
# ==================================================

if st.sidebar.button(
    "🚪 Logout",
    use_container_width=True
):

    st.session_state.logged_in = False

    st.session_state.username = ""

    st.session_state.user_id = None

    st.session_state.session_id = None

    st.session_state.messages = []

    st.session_state.uploaded_pdfs = []

    st.session_state.selected_pdfs = []

    st.cache_resource.clear()

    st.cache_data.clear()

    st.rerun()

st.sidebar.markdown("---")

# ==================================================
# PREVIOUS CHATS
# ==================================================

st.sidebar.subheader(
    "💬 Previous Chats"
)

sessions = session_manager.list_sessions()

if "rename_chat" not in st.session_state:

    st.session_state.rename_chat = None

for session in sessions:

    col1, col2, col3 = st.sidebar.columns(
        [4, 1, 1]
    )

    # =====================================
    # OPEN CHAT
    # =====================================

    with col1:

        if (
            st.session_state.rename_chat
            == session["session_id"]
        ):

            st.text_input(
                "",
                value=session["title"],
                key=f"edit_{session['session_id']}"
            )

        else:

            if st.button(
                session["title"][:35],
                key=session["session_id"]
            ):

                st.session_state.session_id = (
                    session["session_id"]
                )

                st.session_state.messages = (
                    session_manager.get_history(
                        session["session_id"]
                    )
                )

                pdfs = session_manager.get_pdfs(
                    session["session_id"]
                )

                st.session_state.uploaded_pdfs = [

                    pdf["name"]

                    for pdf in pdfs

                ]

                st.session_state.selected_pdfs = (
                    session_manager.get_selected_pdfs(
                        session["session_id"]
                    )
                )

                if not st.session_state.selected_pdfs:

                    st.session_state.selected_pdfs = (
                        st.session_state.uploaded_pdfs.copy()
                    )

                st.cache_resource.clear()

                st.rerun()

    # =====================================
    # RENAME CHAT
    # =====================================

    with col2:

        if (
            st.session_state.rename_chat
            == session["session_id"]
        ):

            if st.button(
                "✔️",
                key=f"save_{session['session_id']}"
            ):

                new_title = st.session_state.get(
                    f"edit_{session['session_id']}",
                    ""
                )

                if new_title.strip():

                    session_manager.update_title(
                        session["session_id"],
                        new_title.strip()
                    )

                st.session_state.rename_chat = None

                st.rerun()

        else:

            if st.button(
                "✏️",
                key=f"rename_{session['session_id']}"
            ):

                st.session_state.rename_chat = (
                    session["session_id"]
                )

                st.rerun()

    # =====================================
    # DELETE CHAT
    # =====================================

    with col3:

        if (
            st.session_state.rename_chat
            == session["session_id"]
        ):

            if st.button(
                "❌",
                key=f"cancel_{session['session_id']}"
            ):

                st.session_state.rename_chat = None

                st.rerun()

        else:

            if st.button(
                "🗑",
                key=f"delete_{session['session_id']}"
            ):

                deleted_id = session["session_id"]

                session_manager.delete_session(
                    deleted_id
                )

                if (
                    st.session_state.session_id
                    == deleted_id
                ):

                    st.session_state.session_id = None

                    st.session_state.messages = []

                    st.session_state.uploaded_pdfs = []

                    st.session_state.selected_pdfs = []

                st.rerun()

st.sidebar.markdown("---")

# ==================================================
# INDEXED PDFs
# ==================================================

st.sidebar.subheader(
    "📚 Indexed PDFs"
)

for pdf in st.session_state.uploaded_pdfs:

    st.sidebar.write(
        f"📄 {pdf}"
    )

st.sidebar.caption(
    f"{len(st.session_state.uploaded_pdfs)} PDF(s) indexed"
)
# ==================================================
# PDF UPLOAD (MULTI PDF)
# ==================================================

uploaded_files = st.sidebar.file_uploader(
    "Choose PDFs",
    type=["pdf"],
    accept_multiple_files=True
)

if uploaded_files:

    for uploaded_file in uploaded_files:

        if uploaded_file.name in st.session_state.uploaded_pdfs:

            continue

        # =====================================
        # UPLOAD TO SUPABASE STORAGE
        # =====================================

        upload_result = storage.upload_pdf(
            session_id=st.session_state.session_id,
            pdf_name=uploaded_file.name,
            pdf_bytes=uploaded_file.getvalue()
        )

        if not upload_result["success"]:

            st.sidebar.error(
                upload_result["message"]
            )

            continue

        storage_path = upload_result[
            "storage_path"
        ]

        # =====================================
        # DOWNLOAD TEMP FILE
        # =====================================

        download_result = storage.download_pdf(
            storage_path
        )

        if not download_result["success"]:

            st.sidebar.error(
                download_result["message"]
            )

            continue

        temp_pdf = download_result[
            "temp_path"
        ]

        # =====================================
        # INGEST
        # =====================================

        with st.spinner(
            f"Indexing {uploaded_file.name}..."
        ):

            ingestor = PDFIngestor(
                session_id=st.session_state.session_id
            )

            result = ingestor.ingest_pdf(
                temp_pdf
            )

        # =====================================
        # DELETE TEMP FILE
        # =====================================

        try:

            os.remove(
                temp_pdf
            )

        except:

            pass

        # =====================================
        # SAVE METADATA
        # =====================================

        if result["status"] == "success":

            st.session_state.uploaded_pdfs.append(
                uploaded_file.name
            )

            session_manager.add_pdf(
                session_id=st.session_state.session_id,
                pdf_name=uploaded_file.name,
                pdf_path=storage_path
            )

            st.session_state.selected_pdfs = (
                st.session_state.uploaded_pdfs.copy()
            )

            session_manager.save_selected_pdfs(
                st.session_state.session_id,
                st.session_state.selected_pdfs
            )

            st.sidebar.success(
                f"{uploaded_file.name} "
                f"({result['chunks_created']} chunks)"
            )

        else:

            st.sidebar.error(
                result["message"]
            )

# ==================================================
# RESTORE PDF LIST
# ==================================================

stored_pdfs = session_manager.get_pdfs(
    st.session_state.session_id
)

st.session_state.uploaded_pdfs = [

    pdf["name"]

    for pdf in stored_pdfs

]

stored_selected = (
    session_manager.get_selected_pdfs(
        st.session_state.session_id
    )
)

if stored_selected:

    st.session_state.selected_pdfs = stored_selected

else:

    st.session_state.selected_pdfs = (
        st.session_state.uploaded_pdfs.copy()
    )

# ==================================================
# PDF SELECTION
# ==================================================

pdf_options = st.session_state.uploaded_pdfs.copy()

valid_defaults = [

    pdf

    for pdf in st.session_state.selected_pdfs

    if pdf in pdf_options

]

selected_pdfs = st.sidebar.multiselect(

    "Select PDFs for Retrieval",

    options=pdf_options,

    default=valid_defaults,

    # Keyed per session_id: a static key here would make Streamlit
    # ignore `default` after the first render and keep showing a
    # PREVIOUS session's PDF selection when you switch chats.
    key=f"selected_pdfs_widget_{st.session_state.session_id}"

)

st.session_state.selected_pdfs = (
    selected_pdfs
)

session_manager.save_selected_pdfs(

    st.session_state.session_id,

    selected_pdfs

)

st.sidebar.markdown("---")

st.sidebar.write(

    "Selected PDFs:",

    selected_pdfs

)
# ==================================================
# CHAT HISTORY
# ==================================================

for message in st.session_state.messages:

    with st.chat_message(
        message["role"]
    ):

        st.markdown(
            message.get(
                "content",
                ""
            )
        )

        # -----------------------------
        # Diagram
        # -----------------------------

        if message.get("diagram"):

            st.subheader(
                "📊 Diagram"
            )

            st.code(
                message["diagram"],
                language="mermaid"
            )

        # -----------------------------
        # Videos
        # -----------------------------

        if message.get("videos"):

            st.subheader(
                "📺 YouTube Videos"
            )

            for video in message["videos"]:

                render_video_card(video)

        # -----------------------------
        # Papers
        # -----------------------------

        if message.get("papers"):

            st.subheader(
                "📄 Research Papers"
            )

            for paper in message["papers"]:

                if not isinstance(
                    paper,
                    dict
                ):
                    continue

                st.markdown(
                    f"### {paper.get('title','Untitled Paper')}"
                )

                if paper.get("authors"):

                    st.write(
                        "**Authors:**",
                        ", ".join(
                            paper["authors"]
                        )
                    )

                if paper.get("published"):

                    st.write(
                        f"**Published:** {paper['published']}"
                    )

                if paper.get("summary"):

                    with st.expander(
                        "Abstract"
                    ):

                        st.write(
                            paper["summary"]
                        )

                if paper.get("pdf_url"):

                    st.link_button(
                        "📄 Open Paper",
                        paper["pdf_url"]
                    )

        # -----------------------------
        # Sources
        # -----------------------------

        if message.get("sources"):

            unique_pdfs = sorted(

                {

                    source.get(
                        "source",
                        "Unknown PDF"
                    )

                    for source in message["sources"]

                    if isinstance(
                        source,
                        dict
                    )

                }

            )

            st.subheader(
                "📚 PDFs Used"
            )

            for pdf in unique_pdfs:

                st.markdown(
                    f"📄 {pdf}"
                )

            with st.expander(
                "Detailed Sources"
            ):

                for source in message["sources"]:

                    if not isinstance(
                        source,
                        dict
                    ):
                        continue

                    st.markdown(

                        f"• **{source.get('source','Unknown')}** "

                        f"(Page {source.get('page','N/A')}, "

                        f"Chunk {source.get('chunk_id','N/A')})"

                    )

# ==================================================
# CHAT INPUT
# ==================================================

query = st.chat_input(
    "Ask anything..."
)

# ==================================================
# RUN PIPELINE
# ==================================================

if query:

    # ----------------------------------
    # SAVE USER MESSAGE
    # ----------------------------------

    st.session_state.messages.append(
        {
            "role": "user",
            "content": query
        }
    )

    session_manager.save_history(
        st.session_state.session_id,
        st.session_state.messages
    )

    with st.chat_message("user"):

        st.markdown(query)

    with st.chat_message("assistant"):

        with st.spinner("Thinking..."):

            if (
                st.session_state.uploaded_pdfs
                and not st.session_state.selected_pdfs
            ):

                st.warning(
                    "Please select at least one PDF."
                )

                st.stop()

            current_session = (
                session_manager.load_session(
                    st.session_state.session_id
                )
            )

            if (
                current_session
                and current_session.get(
                    "title",
                    "New Chat"
                )
                == "New Chat"
            ):

                session_manager.update_title(
                    st.session_state.session_id,
                    query[:40]
                )

            # ----------------------------------
            # RUN ORCHESTRATOR
            # ----------------------------------

            result = orchestrator.run(

                query=query,

                selected_pdfs=(
                    st.session_state.selected_pdfs
                )

            )

        assistant_text = ""
        # =====================================
        # CHAT
        # =====================================

        if "chat" in result:

            assistant_text += (
                result["chat"]
                + "\n\n"
            )

        # =====================================
        # ANSWER
        # =====================================

        if "answer" in result:

            assistant_text += (
                result["answer"]
                + "\n\n"
            )

        # =====================================
        # COMPARISON
        # =====================================

        if "comparison" in result:

            assistant_text += (
                "## ⚖️ Comparison\n\n"
                + result["comparison"]
                + "\n\n"
            )

        # =====================================
        # NOTES
        # =====================================

        if "notes" in result:

            assistant_text += (
                "## 📝 Notes\n\n"
                + result["notes"]
                + "\n\n"
            )

        # =====================================
        # QUIZ
        # =====================================

        if "quiz" in result:

            assistant_text += (
                "## ❓ Quiz\n\n"
                + result["quiz"]
                + "\n\n"
            )

        st.markdown(
            assistant_text
        )

        # =====================================
        # DIAGRAM
        # =====================================

        if (
            "diagram" in result
            and result["diagram"]
        ):

            st.subheader(
                "📊 Diagram"
            )

            st.code(
                result["diagram"],
                language="mermaid"
            )

        # =====================================
        # VIDEOS
        # =====================================

        if (
            "videos" in result
            and result["videos"]
        ):

            st.subheader(
                "📺 YouTube Videos"
            )

            for video in result["videos"]:

                render_video_card(video)

        # =====================================
        # PAPERS
        # =====================================

        if (
            "papers" in result
            and result["papers"]
        ):

            st.subheader(
                "📄 Research Papers"
            )

            for paper in result["papers"]:

                if not isinstance(
                    paper,
                    dict
                ):
                    continue

                st.markdown(
                    f"### {paper.get('title','Untitled Paper')}"
                )

                if paper.get("authors"):

                    st.write(
                        "**Authors:**",
                        ", ".join(
                            paper["authors"]
                        )
                    )

                if paper.get("published"):

                    st.write(
                        f"**Published:** {paper['published']}"
                    )

                if paper.get("summary"):

                    with st.expander(
                        "Abstract"
                    ):

                        st.write(
                            paper["summary"]
                        )

                if paper.get("pdf_url"):

                    st.link_button(
                        "📄 Open Paper",
                        paper["pdf_url"]
                    )

        # =====================================
        # PDF SOURCES
        # =====================================

        if (
            "sources" in result
            and result["sources"]
        ):

            unique_pdfs = sorted(

                {

                    source.get(
                        "source",
                        "Unknown PDF"
                    )

                    for source in result["sources"]

                    if isinstance(
                        source,
                        dict
                    )

                }

            )

            st.subheader(
                "📚 PDFs Used"
            )

            for pdf in unique_pdfs:

                st.markdown(
                    f"📄 {pdf}"
                )

            with st.expander(
                "Detailed Sources"
            ):

                for source in result["sources"]:

                    if not isinstance(
                        source,
                        dict
                    ):

                        continue

                    st.markdown(

                        f"• **{source.get('source','Unknown')}** "

                        f"(Page {source.get('page','N/A')}, "

                        f"Chunk {source.get('chunk_id','N/A')})"

                    )        
        # =====================================
        # SAVE SOURCES INTO CHAT HISTORY
        # =====================================

        saved_text = assistant_text

        if (
            "sources" in result
            and result["sources"]
        ):

            saved_text += "\n\n📚 PDFs Used:\n"

            unique_pdfs = sorted(

                {

                    source.get(
                        "source",
                        "Unknown PDF"
                    )

                    for source in result["sources"]

                    if isinstance(
                        source,
                        dict
                    )

                }

            )

            for pdf in unique_pdfs:

                saved_text += f"\n• {pdf}"

        # =====================================
        # SAVE COMPLETE ASSISTANT RESPONSE
        # =====================================

        assistant_message = {

            "role": "assistant",

            "content": saved_text,

            "chat": result.get("chat"),

            "answer": result.get("answer"),

            "comparison": result.get("comparison"),

            "notes": result.get("notes"),

            "quiz": result.get("quiz"),

            "diagram": result.get("diagram"),

            "videos": result.get(
                "videos",
                []
            ),

            "papers": result.get(
                "papers",
                []
            ),

            "sources": result.get(
                "sources",
                []
            ),

            "selected_pdfs": st.session_state.selected_pdfs.copy()

        }

        st.session_state.messages.append(
            assistant_message
        )

        # =====================================
        # SAVE HISTORY TO SUPABASE
        # =====================================

        session_manager.save_history(

            st.session_state.session_id,

            st.session_state.messages

        )

        # =====================================
        # UPDATE SUMMARY (OPTIONAL)
        # =====================================

        if "summary" in result:

            session_manager.update_summary(

                st.session_state.session_id,

                result["summary"]

            )

# ==================================================
# FOOTER
# ==================================================

st.markdown("---")

st.caption(

    "Powered by Groq + LangChain + LangSmith + ChromaDB + Supabase + YouTube + arXiv | Made by Blaze"

)