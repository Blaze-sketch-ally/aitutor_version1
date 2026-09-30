import os
import json
import streamlit as st
import streamlit.components.v1 as components

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
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================================================
# THEME / STYLING
# ==================================================
# Design tokens — "study lamp" dark theme: ink-blue base with a warm
# amber accent (the glow of a desk lamp), a serif display face for
# headings (Fraunces) paired with Inter for UI text and JetBrains Mono
# for citations / source metadata.

def inject_css():
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

        :root {
            --bg: #100D1A;
            --bg-elevated: #17132A;
            --bg-card: #1E1836;
            --border: #332A54;
            --text-primary: #F3F1FA;
            --text-secondary: #ABA3C6;
            --accent: #9B6BFF;
            --accent-strong: #7C4FE0;
            --accent-soft: rgba(155, 107, 255, 0.14);
            --success: #5FB878;
            --danger: #E3766E;
        }

        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

        /* Kill every white band Streamlit leaves by default: the outer
           html/body, the app view container, the header/toolbar strip,
           and the floating bottom bar that holds the chat input. */
        html, body,
        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stHeader"],
        [data-testid="stToolbar"],
        [data-testid="stBottomBlockContainer"],
        [data-testid="stBottom"],
        .stChatFloatingInputContainer,
        section.main,
        div[data-testid="stMainBlockContainer"] {
            background-color: var(--bg) !important;
            color: var(--text-primary);
        }

        [data-testid="stHeader"] { border-bottom: 1px solid var(--border); }
        [data-testid="stDecoration"] { background-image: none !important; background-color: var(--accent) !important; }

        /* Every bit of body copy defaults to the light text color —
           this is what was reading as washed-out / low contrast. */
        p, li, span, label, div[data-testid="stMarkdownContainer"],
        div[data-testid="stMarkdownContainer"] * ,
        [data-testid="stCaptionContainer"] {
            color: var(--text-primary);
        }
        [data-testid="stCaptionContainer"] { color: var(--text-secondary) !important; }

        h1, h2, h3 { font-family: 'Fraunces', serif !important; letter-spacing: -0.01em; color: var(--text-primary) !important; }
        h1 { font-weight: 600 !important; }
        h2, h3 { font-weight: 600 !important; }

        /* ---------- Sidebar ---------- */
        [data-testid="stSidebar"] {
            background-color: var(--bg-elevated);
            border-right: 1px solid var(--border);
        }
        [data-testid="stSidebar"] h3 {
            font-family: 'Inter', sans-serif !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            letter-spacing: 0.06em;
            text-transform: uppercase;
            color: var(--text-secondary) !important;
            margin-top: 0.4rem;
        }

        /* ---------- Buttons ---------- */
        .stButton > button {
            border-radius: 8px;
            border: 1px solid var(--border);
            background-color: var(--bg-card);
            color: var(--text-primary);
            font-weight: 500;
            transition: all 0.15s ease;
        }
        .stButton > button:hover {
            border-color: var(--accent);
            color: var(--accent);
        }
        .stButton > button[kind="primary"] {
            background-color: var(--accent);
            border-color: var(--accent);
            color: #FFFFFF;
            font-weight: 600;
        }
        .stButton > button[kind="primary"]:hover {
            background-color: var(--accent-strong);
            border-color: var(--accent-strong);
            color: #FFFFFF;
        }
        .stLinkButton > a {
            border-radius: 8px !important;
            border: 1px solid var(--accent) !important;
            color: var(--accent) !important;
            background-color: var(--accent-soft) !important;
            font-weight: 500 !important;
        }

        /* ---------- Chat input wrapper (the floating bar itself, not just the textarea) ---------- */
        [data-testid="stChatInput"] {
            background-color: var(--bg-card) !important;
            border: 1px solid var(--border) !important;
            border-radius: 12px !important;
        }
        [data-testid="stChatInput"] textarea::placeholder { color: var(--text-secondary) !important; }

        /* ---------- Dropdowns / multiselect / selectbox popovers ---------- */
        [data-baseweb="select"] > div {
            background-color: var(--bg-card) !important;
            border-color: var(--border) !important;
            color: var(--text-primary) !important;
        }
        [data-baseweb="popover"] li, [data-baseweb="menu"] {
            background-color: var(--bg-card) !important;
            color: var(--text-primary) !important;
        }
        [data-baseweb="tag"] {
            background-color: var(--accent-soft) !important;
            color: var(--text-primary) !important;
        }

        /* ---------- File uploader rows (uploaded file chips) ---------- */
        [data-testid="stFileUploaderFile"] {
            background-color: var(--bg-card) !important;
            color: var(--text-primary) !important;
            border-radius: 8px;
        }

        /* ---------- Cards / containers with border=True ---------- */
        [data-testid="stVerticalBlockBorderWrapper"] {
            background-color: var(--bg-card);
            border-color: var(--border) !important;
            border-radius: 12px !important;
        }

        /* ---------- Chat bubbles ---------- */
        [data-testid="stChatMessage"] {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 0.4rem 0.2rem;
        }

        /* ---------- Tabs ---------- */
        .stTabs [data-baseweb="tab-list"] {
            gap: 4px;
            border-bottom: 1px solid var(--border);
        }
        .stTabs [data-baseweb="tab"] {
            background-color: transparent;
            color: var(--text-secondary);
            font-weight: 500;
            border-radius: 8px 8px 0 0;
        }
        .stTabs [aria-selected="true"] {
            color: var(--accent) !important;
            border-bottom: 2px solid var(--accent) !important;
        }

        /* ---------- Inputs ---------- */
        .stTextInput input, .stChatInput textarea, textarea {
            background-color: var(--bg-card) !important;
            color: var(--text-primary) !important;
            border-radius: 8px !important;
            border: 1px solid var(--border) !important;
        }
        [data-testid="stFileUploaderDropzone"] {
            background-color: var(--bg-card);
            border: 1px dashed var(--border);
            border-radius: 10px;
        }

        /* ---------- Expander ---------- */
        [data-testid="stExpander"] {
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 10px;
        }

        /* ---------- Misc ---------- */
        code, .stCode, pre { font-family: 'JetBrains Mono', monospace !important; }
        hr { border-color: var(--border) !important; }

        .feature-pill {
            display: inline-block;
            padding: 0.28rem 0.7rem;
            margin: 0.15rem 0.3rem 0.15rem 0;
            border-radius: 999px;
            background-color: var(--accent-soft);
            border: 1px solid var(--border);
            color: var(--text-primary);
            font-size: 0.82rem;
        }

        .pdf-chip {
            display: inline-block;
            padding: 0.25rem 0.6rem;
            margin: 0.15rem 0.3rem 0.15rem 0;
            border-radius: 8px;
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            font-size: 0.82rem;
        }

        .avatar-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 34px;
            height: 34px;
            border-radius: 50%;
            background-color: var(--accent);
            color: #FFFFFF;
            font-weight: 700;
            font-family: 'Fraunces', serif;
            margin-right: 0.5rem;
        }

        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: var(--bg); }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 8px; }
        </style>
        """,
        unsafe_allow_html=True
    )


inject_css()

# ==================================================
# AUTHENTICATION
# ==================================================

auth = AuthManager()

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "username" not in st.session_state:
    st.session_state.username = ""

if not st.session_state.logged_in:

    st.markdown(
        "<h1 style='text-align:center; margin-top:2rem;'>🧠 AI Tutor Agent</h1>"
        "<p style='text-align:center; color:var(--text-secondary); margin-bottom:2rem;'>"
        "Your research, notes and quiz companion.</p>",
        unsafe_allow_html=True
    )

    left, mid, right = st.columns([1, 1.3, 1])

    with mid:
        with st.container(border=True):

            tab1, tab2 = st.tabs(["Login", "Register"])

            # =====================================
            # LOGIN
            # =====================================
            with tab1:

                username = st.text_input("Username", key="login_user")
                password = st.text_input("Password", type="password", key="login_pass")

                if st.button("Login", use_container_width=True, type="primary"):

                    username = username.strip().lower()
                    result = auth.login_user(username, password)

                    if result["success"]:

                        st.session_state.logged_in = True
                        st.session_state.username = username
                        st.session_state.user_id = result.get("user_id")
                        st.session_state.session_id = None
                        st.session_state.messages = []
                        st.session_state.uploaded_pdfs = []
                        st.session_state.selected_pdfs = []
                        st.cache_resource.clear()
                        st.rerun()

                    else:
                        st.error(result["message"])

            # =====================================
            # REGISTER
            # =====================================
            with tab2:

                username = st.text_input("Username", key="register_user")
                password = st.text_input("Password", type="password", key="register_pass")

                if st.button("Register", use_container_width=True, type="primary"):

                    username = username.strip().lower()
                    result = auth.register_user(username, password)

                    if result["success"]:
                        st.success(result["message"])
                    else:
                        st.error(result["message"])

    st.stop()

# ==================================================
# SESSION MANAGER
# ==================================================

session_manager = SessionManager(st.session_state.username)
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

if "rename_chat" not in st.session_state:
    st.session_state.rename_chat = None

# ==================================================
# LOAD USER SESSIONS
# ==================================================

sessions = session_manager.list_sessions()

if "session_id" not in st.session_state or st.session_state.session_id is None:

    if sessions:

        latest_session = sessions[0]
        st.session_state.session_id = latest_session["session_id"]
        st.session_state.messages = session_manager.get_history(latest_session["session_id"])

        pdfs = session_manager.get_pdfs(latest_session["session_id"])
        st.session_state.uploaded_pdfs = [pdf["name"] for pdf in pdfs]

        st.session_state.selected_pdfs = session_manager.get_selected_pdfs(latest_session["session_id"])

        if not st.session_state.selected_pdfs:
            st.session_state.selected_pdfs = st.session_state.uploaded_pdfs.copy()

    else:

        new_session = session_manager.create_session()
        st.session_state.session_id = new_session
        st.session_state.messages = []
        st.session_state.uploaded_pdfs = []
        st.session_state.selected_pdfs = []

# ==================================================
# LOAD ORCHESTRATOR
# ==================================================

@st.cache_resource
def load_orchestrator(username, session_id):
    return Orchestrator(username=username, session_id=session_id)


orchestrator = load_orchestrator(st.session_state.username, st.session_state.session_id)

# ==================================================
# RENDER HELPERS (shared by history + live response)
# ==================================================

def _format_count(n):
    if n is None:
        return None
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def render_videos(videos):
    for video in videos:
        if not isinstance(video, dict):
            continue
        with st.container(border=True):
            st.markdown(f"**{video.get('title', 'Untitled Video')}**")
            if video.get("channel"):
                st.caption(f"Channel: {video['channel']}")

            description = video.get("description", "")
            if description:
                snippet = description.strip().replace("\n", " ")
                if len(snippet) > 160:
                    snippet = snippet[:160].rsplit(" ", 1)[0] + "..."
                st.write(snippet)

            stats_parts = []
            views = _format_count(video.get("views"))
            likes = _format_count(video.get("likes"))
            if views is not None:
                stats_parts.append(f"👁 {views} views")
            if likes is not None:
                stats_parts.append(f"👍 {likes} likes")
            if video.get("duration_minutes") is not None:
                stats_parts.append(f"⏱ {video['duration_minutes']} min")
            if stats_parts:
                st.caption(" · ".join(stats_parts))

            segment = video.get("study_segment")

            if video.get("url"):
                st.link_button("▶ Watch Video", video["url"])

            # Timestamp goes BELOW the watch button, on purpose —
            # it's "here's the portion to watch", read after you've
            # already decided to click through.
            if segment:
                st.markdown(
                    f"📍 Watch **{segment['start_label']} – {segment['end_label']}** "
                    f"for the part most relevant to your question."
                )
                if video.get("url_at_timestamp"):
                    st.link_button(
                        f"⏩ Jump to {segment['start_label']}",
                        video["url_at_timestamp"]
                    )
                with st.expander("Preview this section"):
                    st.write(segment.get("snippet", ""))


def render_papers(papers):
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        with st.container(border=True):
            st.markdown(f"**{paper.get('title', 'Untitled Paper')}**")
            if paper.get("authors"):
                st.caption("Authors: " + ", ".join(paper["authors"]))
            if paper.get("published"):
                st.caption(f"Published: {paper['published']}")
            if paper.get("summary"):
                with st.expander("Abstract"):
                    st.write(paper["summary"])
            if paper.get("pdf_url"):
                st.link_button("📄 Open Paper", paper["pdf_url"])


def render_sources(sources):
    unique_pdfs = sorted({
        source.get("source", "Unknown PDF")
        for source in sources
        if isinstance(source, dict)
    })

    chips = "".join(f"<span class='pdf-chip'>📄 {pdf}</span>" for pdf in unique_pdfs)
    st.markdown(chips, unsafe_allow_html=True)

    with st.expander("Detailed sources"):
        for source in sources:
            if not isinstance(source, dict):
                continue
            st.markdown(
                f"`{source.get('source','Unknown')}` — "
                f"page {source.get('page','N/A')}, chunk {source.get('chunk_id','N/A')}"
            )


# ----------------------------------------------------
# DIAGRAM RENDERING (mermaid / chart / image)
# ----------------------------------------------------
# DiagramAgent.generate_diagram() returns a dict:
#   {"type": "mermaid", "content": "<mermaid code>"}
#   {"type": "chart",   "content": {chart_type, title, labels, datasets}}
#   {"type": "image",   "content": "<image url>", "prompt": "<prompt>"}
# render_diagram_result() below dispatches on "type" and renders
# accordingly. Old messages saved before this change may still have
# a raw string in "diagram" (from the previous st.code-only version)
# — that's handled as a fallback so old chat history doesn't break.

def render_mermaid(mermaid_code: str):
    code = (mermaid_code or "").strip()

    html = f"""
    <div class="mermaid">
    {code}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{ startOnLoad: true, theme: "dark" }});
    </script>
    """
    components.html(html, height=500, scrolling=True)


def render_chart(chart_data: dict):
    chart_type = chart_data.get("chart_type", "bar")
    title = chart_data.get("title", "")
    labels = chart_data.get("labels", [])
    datasets = chart_data.get("datasets", [])

    palette = ["#9B6BFF", "#5FB878", "#E3766E", "#F5C463", "#4FA8E0", "#C97CE0"]

    js_datasets = []
    for i, ds in enumerate(datasets):
        color = palette[i % len(palette)]
        js_datasets.append({
            "label": ds.get("label", f"Series {i+1}"),
            "data": ds.get("data", []),
            "backgroundColor": color if chart_type in ("bar", "pie", "doughnut", "radar") else "transparent",
            "borderColor": color,
            "borderWidth": 2
        })

    config = {
        "type": chart_type,
        "data": {"labels": labels, "datasets": js_datasets},
        "options": {
            "plugins": {
                "title": {"display": bool(title), "text": title, "color": "#F3F1FA"},
                "legend": {"labels": {"color": "#F3F1FA"}}
            },
            "scales": {} if chart_type in ("pie", "doughnut", "radar") else {
                "x": {"ticks": {"color": "#ABA3C6"}, "grid": {"color": "#332A54"}},
                "y": {"ticks": {"color": "#ABA3C6"}, "grid": {"color": "#332A54"}}
            }
        }
    }

    html = f"""
    <div style="background:#1E1836; padding:16px; border-radius:12px;">
      <canvas id="chartCanvas"></canvas>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <script>
        const ctx = document.getElementById('chartCanvas');
        new Chart(ctx, {json.dumps(config)});
    </script>
    """
    components.html(html, height=450)


def render_diagram_result(data):
    """data is normally the dict returned by DiagramAgent.generate_diagram().
    Falls back gracefully if it's an old raw mermaid string from before
    this feature existed."""

    if not data:
        return

    # Backward compatibility: old saved messages have a raw string here.
    if isinstance(data, str):
        render_mermaid(data)
        with st.expander("View Mermaid source"):
            st.code(data, language="mermaid")
        return

    if not isinstance(data, dict):
        return

    dtype = data.get("type", "mermaid")
    content = data.get("content")

    if dtype == "mermaid":
        render_mermaid(content)
        with st.expander("View Mermaid source"):
            st.code(content, language="mermaid")

    elif dtype == "chart":
        render_chart(content)
        with st.expander("View chart data"):
            st.json(content)

    elif dtype == "image":
        st.image(content, caption=data.get("prompt", ""), use_container_width=True)
        st.caption("Generated with Pollinations.ai")


def render_extras(data):
    """Render diagram / videos / papers / sources as tabs, only including
    tabs for content types that are actually present on this message."""

    tab_specs = []
    if data.get("diagram"):
        tab_specs.append(("📊 Diagram", "diagram"))
    if data.get("videos"):
        tab_specs.append(("📺 Videos", "videos"))
    if data.get("papers"):
        tab_specs.append(("📄 Papers", "papers"))
    if data.get("sources"):
        tab_specs.append(("📚 Sources", "sources"))

    if not tab_specs:
        return

    tabs = st.tabs([label for label, _ in tab_specs])

    for tab, (_, key) in zip(tabs, tab_specs):
        with tab:
            if key == "diagram":
                render_diagram_result(data["diagram"])
            elif key == "videos":
                render_videos(data["videos"])
            elif key == "papers":
                render_papers(data["papers"])
            elif key == "sources":
                render_sources(data["sources"])


def render_video_summary_caption(data):
    """Shows a small caption noting this reply was generated from a
    YouTube link or an uploaded video, for both the live response and
    when re-rendering saved chat history."""

    if data.get("mode") != "video_summary" or not data.get("video_source_ref"):
        return

    if data.get("video_source") == "youtube":
        st.caption(f"🎬 Summarized from: {data['video_source_ref']}")
    else:
        st.caption(f"🎬 Summarized uploaded video: {data['video_source_ref']}")


def build_assistant_text(result):
    text = ""
    if "chat" in result:
        text += result["chat"] + "\n\n"
    if "answer" in result:
        text += result["answer"] + "\n\n"
    if "comparison" in result:
        text += "## ⚖️ Comparison\n\n" + result["comparison"] + "\n\n"
    if "notes" in result:
        text += "## 📝 Notes\n\n" + result["notes"] + "\n\n"
    if "quiz" in result:
        text += "## ❓ Quiz\n\n" + result["quiz"] + "\n\n"
    return text


# ==================================================
# SIDEBAR
# ==================================================

initials = st.session_state.username[:2].upper() if st.session_state.username else "?"

st.sidebar.markdown(
    f"<div style='display:flex; align-items:center; margin-bottom:0.5rem;'>"
    f"<span class='avatar-badge'>{initials}</span>"
    f"<div><div style='font-weight:600;'>{st.session_state.username}</div>"
    f"<div style='color:var(--text-secondary); font-size:0.78rem;'>Signed in</div></div>"
    f"</div>",
    unsafe_allow_html=True
)

col_new, col_out = st.sidebar.columns(2)

with col_new:
    new_chat_clicked = st.button("➕ New Chat", use_container_width=True, type="primary")

with col_out:
    logout_clicked = st.button("🚪 Logout", use_container_width=True)

if new_chat_clicked:
    new_session = session_manager.create_session()
    st.session_state.session_id = new_session
    st.session_state.messages = []
    st.session_state.uploaded_pdfs = []
    st.session_state.selected_pdfs = []
    st.cache_resource.clear()
    st.rerun()

if logout_clicked:
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

st.sidebar.markdown("### 💬 Previous Chats")

sessions = session_manager.list_sessions()

for session in sessions:

    col1, col2, col3 = st.sidebar.columns([4, 1, 1])

    # OPEN CHAT
    with col1:

        if st.session_state.rename_chat == session["session_id"]:
            st.text_input("", value=session["title"], key=f"edit_{session['session_id']}", label_visibility="collapsed")
        else:
            is_active = session["session_id"] == st.session_state.session_id
            if st.button(
                ("● " if is_active else "") + session["title"][:33],
                key=session["session_id"],
                use_container_width=True
            ):
                st.session_state.session_id = session["session_id"]
                st.session_state.messages = session_manager.get_history(session["session_id"])

                pdfs = session_manager.get_pdfs(session["session_id"])
                st.session_state.uploaded_pdfs = [pdf["name"] for pdf in pdfs]

                st.session_state.selected_pdfs = session_manager.get_selected_pdfs(session["session_id"])
                if not st.session_state.selected_pdfs:
                    st.session_state.selected_pdfs = st.session_state.uploaded_pdfs.copy()

                st.cache_resource.clear()
                st.rerun()

    # RENAME CHAT
    with col2:

        if st.session_state.rename_chat == session["session_id"]:
            if st.button("✔️", key=f"save_{session['session_id']}"):
                new_title = st.session_state.get(f"edit_{session['session_id']}", "")
                if new_title.strip():
                    session_manager.update_title(session["session_id"], new_title.strip())
                st.session_state.rename_chat = None
                st.rerun()
        else:
            if st.button("✏️", key=f"rename_{session['session_id']}"):
                st.session_state.rename_chat = session["session_id"]
                st.rerun()

    # DELETE CHAT
    with col3:

        if st.session_state.rename_chat == session["session_id"]:
            if st.button("❌", key=f"cancel_{session['session_id']}"):
                st.session_state.rename_chat = None
                st.rerun()
        else:
            if st.button("🗑", key=f"delete_{session['session_id']}"):
                deleted_id = session["session_id"]
                session_manager.delete_session(deleted_id)

                if st.session_state.session_id == deleted_id:
                    st.session_state.session_id = None
                    st.session_state.messages = []
                    st.session_state.uploaded_pdfs = []
                    st.session_state.selected_pdfs = []

                st.rerun()

st.sidebar.markdown("---")

# ==================================================
# INDEXED PDFs
# ==================================================

st.sidebar.markdown("### 📚 Indexed PDFs")

if st.session_state.uploaded_pdfs:
    chips = "".join(f"<span class='pdf-chip'>📄 {pdf}</span>" for pdf in st.session_state.uploaded_pdfs)
    st.sidebar.markdown(chips, unsafe_allow_html=True)
else:
    st.sidebar.caption("No PDFs indexed yet.")

st.sidebar.caption(f"{len(st.session_state.uploaded_pdfs)} PDF(s) indexed")

# ==================================================
# PDF UPLOAD (MULTI PDF)
# ==================================================

uploaded_files = st.sidebar.file_uploader("Choose PDFs", type=["pdf"], accept_multiple_files=True)

if uploaded_files:

    for uploaded_file in uploaded_files:

        if uploaded_file.name in st.session_state.uploaded_pdfs:
            continue

        upload_result = storage.upload_pdf(
            session_id=st.session_state.session_id,
            pdf_name=uploaded_file.name,
            pdf_bytes=uploaded_file.getvalue()
        )

        if not upload_result["success"]:
            st.sidebar.error(upload_result["message"])
            continue

        storage_path = upload_result["storage_path"]

        download_result = storage.download_pdf(storage_path)

        if not download_result["success"]:
            st.sidebar.error(download_result["message"])
            continue

        temp_pdf = download_result["temp_path"]

        with st.spinner(f"Indexing {uploaded_file.name}..."):
            ingestor = PDFIngestor(session_id=st.session_state.session_id)
            result = ingestor.ingest_pdf(temp_pdf)

        try:
            os.remove(temp_pdf)
        except Exception:
            pass

        if result["status"] == "success":

            st.session_state.uploaded_pdfs.append(uploaded_file.name)

            session_manager.add_pdf(
                session_id=st.session_state.session_id,
                pdf_name=uploaded_file.name,
                pdf_path=storage_path
            )

            st.session_state.selected_pdfs = st.session_state.uploaded_pdfs.copy()
            session_manager.save_selected_pdfs(st.session_state.session_id, st.session_state.selected_pdfs)

            st.sidebar.success(f"{uploaded_file.name} ({result['chunks_created']} chunks)")

        else:
            st.sidebar.error(result["message"])

# ==================================================
# RESTORE PDF LIST
# ==================================================

stored_pdfs = session_manager.get_pdfs(st.session_state.session_id)
st.session_state.uploaded_pdfs = [pdf["name"] for pdf in stored_pdfs]

stored_selected = session_manager.get_selected_pdfs(st.session_state.session_id)

if stored_selected:
    st.session_state.selected_pdfs = stored_selected
else:
    st.session_state.selected_pdfs = st.session_state.uploaded_pdfs.copy()

# ==================================================
# PDF SELECTION
# ==================================================

st.sidebar.markdown("### 🎯 Retrieval Scope")

pdf_options = st.session_state.uploaded_pdfs.copy()
valid_defaults = [pdf for pdf in st.session_state.selected_pdfs if pdf in pdf_options]

selected_pdfs = st.sidebar.multiselect(
    "Select PDFs for Retrieval",
    options=pdf_options,
    default=valid_defaults,
    # Keyed per session_id on purpose: Streamlit widgets with a static
    # key keep their value in session_state across reruns and ignore
    # `default` after the first render. Without the session_id in the
    # key, switching chats (or hitting New Chat) would keep showing
    # the PREVIOUS session's PDF selection instead of this session's.
    key=f"selected_pdfs_widget_{st.session_state.session_id}",
    label_visibility="collapsed"
)

st.session_state.selected_pdfs = selected_pdfs
session_manager.save_selected_pdfs(st.session_state.session_id, selected_pdfs)

# ==================================================
# HEADER
# ==================================================

st.markdown("## 🧠 AI Tutor Agent")
st.caption(
    "Upload PDFs and chat naturally — ask for answers, notes, quizzes, "
    "diagrams, videos or papers. Paste a YouTube link or attach a video "
    "(📎 icon in the chat bar) to get a summary."
)

features = [
    "Conversational Tutor", "PDF Q&A", "Hybrid RAG", "Multi-PDF",
    "Quiz Generation", "Notes Generation", "Diagrams",
    "YouTube Recs", "Video Summaries", "Research Papers",
    "Session Memory", "Citations"
]
st.markdown("".join(f"<span class='feature-pill'>{f}</span>" for f in features), unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

# ==================================================
# CHAT HISTORY
# ==================================================

for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        st.markdown(message.get("content", ""))
        render_video_summary_caption(message)
        render_extras(message)

# ==================================================
# CHAT INPUT
# ==================================================
# accept_file=True adds a paperclip attachment icon inside the chat
# bar itself (built into Streamlit's chat_input, requires Streamlit
# >= 1.40.0) — this is the "button beside the chat bar" for attaching
# a video. When accept_file is enabled, chat_input returns a dict-like
# object with "text" and "files" instead of a plain string, so we
# unpack it into `query` (the text Orchestrator gets) and
# `uploaded_video_path` (saved to disk if a file was attached).
#
# A pasted YouTube link needs NO special handling here at all — it's
# just plain text in `query`, and Orchestrator already detects
# YouTube URLs inside the query text on its own (see
# agents/orchestrator.py's VIDEO SUMMARY SHORT-CIRCUIT block).

chat_value = st.chat_input(
    "Ask anything... (or paste a YouTube link / attach a video)",
    accept_file=True,
    file_type=["mp4", "mov", "mkv", "webm", "avi", "m4a", "mp3", "wav"]
)

query = None
uploaded_video_path = None
attached_video_name = None

if chat_value:

    query = (chat_value.get("text") or "").strip()
    attached_files = chat_value.get("files") or []

    if attached_files:

        # Only the first attached file is used — summarizing multiple
        # videos in one turn isn't supported, same scope as the rest
        # of this feature.
        video_file = attached_files[0]
        attached_video_name = video_file.name

        os.makedirs("temp_uploads", exist_ok=True)
        uploaded_video_path = os.path.join("temp_uploads", video_file.name)

        with open(uploaded_video_path, "wb") as f:
            f.write(video_file.getbuffer())

        # If the user attached a video without typing anything, give
        # Orchestrator a sensible default query text so downstream
        # prompts (which reference the "topic"/"question") aren't
        # working from an empty string.
        if not query:
            query = f"Summarize this uploaded video: {attached_video_name}"

# ==================================================
# RUN PIPELINE
# ==================================================

if chat_value:

    display_text = query
    if attached_video_name:
        display_text = f"📎 {attached_video_name}\n\n{query}" if query else f"📎 {attached_video_name}"

    st.session_state.messages.append({"role": "user", "content": display_text})
    session_manager.save_history(st.session_state.session_id, st.session_state.messages)

    with st.chat_message("user"):
        st.markdown(display_text)

    with st.chat_message("assistant"):

        if st.session_state.uploaded_pdfs and not st.session_state.selected_pdfs and not uploaded_video_path:
            st.warning("Please select at least one PDF.")
            st.stop()

        current_session = session_manager.load_session(st.session_state.session_id)

        if current_session and current_session.get("title", "New Chat") == "New Chat":
            session_manager.update_title(st.session_state.session_id, query[:40])

        # ==================================================
        # STREAMING vs NON-STREAMING
        # ==================================================
        # orchestrator.run_stream() decides internally which case
        # this is:
        #   - Pure chat, or "answer" as the ONLY requested intent ->
        #     result["streamed"] = True, result["generator"] is a text
        #     generator to feed into st.write_stream().
        #   - Anything else (video summary short-circuit, or any
        #     multi-intent combination involving notes/quiz/diagram/
        #     videos/papers/comparison) -> result["streamed"] = False,
        #     result is already the complete dict, exactly like the
        #     old orchestrator.run() return value.
        #
        # Non-streamed responses still show the spinner while
        # waiting, since there's nothing to progressively render for
        # those (structured widgets need the full result before they
        # can render at all).

        if uploaded_video_path or query.strip():

            # We don't know yet whether this will stream — but
            # classification + retrieval always happen first regardless
            # (run_stream() only returns once those are done; for the
            # streaming cases, the actual LLM generation hasn't started
            # yet at this point, that only begins once st.write_stream()
            # below starts iterating the generator).
            with st.spinner("Thinking..."):

                result = orchestrator.run_stream(
                    query=query,
                    selected_pdfs=st.session_state.selected_pdfs,
                    uploaded_video_path=uploaded_video_path
                )

        else:

            result = {"streamed": False, "answer": "", "sources": []}

        # Clean up the temp video file now that Orchestrator has
        # processed it — VideoSummaryAgent only cleans up its own
        # temp dir for YouTube downloads, uploaded files are owned by
        # this script.
        if uploaded_video_path:
            try:
                os.remove(uploaded_video_path)
            except OSError:
                pass

        if result.get("streamed"):

            # st.write_stream consumes the generator chunk-by-chunk,
            # renders incrementally as tokens arrive, and returns the
            # fully concatenated string once the generator is
            # exhausted.
            full_text = st.write_stream(result["generator"])

            # Persist into ChatMemory now that the full text actually
            # exists (deferred from run_stream(), which couldn't do
            # this earlier since the text wasn't generated yet).
            result = orchestrator.finalize_stream(result, full_text)

            assistant_text = full_text

        else:

            assistant_text = build_assistant_text(result)
            st.markdown(assistant_text)

        render_video_summary_caption(result)
        render_extras(result)

        # =====================================
        # SAVE SOURCES INTO CHAT HISTORY TEXT
        # =====================================

        saved_text = assistant_text

        if result.get("sources"):
            saved_text += "\n\n📚 PDFs Used:\n"
            unique_pdfs = sorted({
                source.get("source", "Unknown PDF")
                for source in result["sources"]
                if isinstance(source, dict)
            })
            for pdf in unique_pdfs:
                saved_text += f"\n• {pdf}"

        assistant_message = {
            "role": "assistant",
            "content": saved_text,
            "chat": result.get("chat"),
            "answer": result.get("answer"),
            "comparison": result.get("comparison"),
            "notes": result.get("notes"),
            "quiz": result.get("quiz"),
            "diagram": result.get("diagram"),
            "videos": result.get("videos", []),
            "papers": result.get("papers", []),
            "sources": result.get("sources", []),
            "mode": result.get("mode"),
            "video_source": result.get("video_source"),
            "video_source_ref": result.get("video_source_ref"),
            "selected_pdfs": st.session_state.selected_pdfs.copy()
        }

        st.session_state.messages.append(assistant_message)
        session_manager.save_history(st.session_state.session_id, st.session_state.messages)

        if "summary" in result:
            session_manager.update_summary(st.session_state.session_id, result["summary"])

# ==================================================
# FOOTER
# ==================================================

st.markdown("---")
st.caption(
    "Powered by Groq + LangChain + LangSmith + ChromaDB + Supabase + YouTube + arXiv | Made by Blaze"
)