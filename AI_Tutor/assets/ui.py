import streamlit as st

from assets.theme import (
    APP_NAME,
    APP_ICON,
    APP_SUBTITLE,
    FOOTER,
    FEATURES
)


# ==========================================================
# DIVIDER
# ==========================================================

def divider():

    st.markdown(
        '<div class="divider"></div>',
        unsafe_allow_html=True
    )


# ==========================================================
# SECTION TITLE
# ==========================================================

def section_title(
    title: str,
    subtitle: str = ""
):

    st.markdown(
        f"""
        <div class="section-header">

            <div>

                <h2>{title}</h2>

                <p>{subtitle}</p>

            </div>

        </div>
        """,
        unsafe_allow_html=True
    )


# ==========================================================
# BADGES
# ==========================================================

def render_badges(items):

    if not items:

        return

    html = ""

    for item in items:

        html += (
            f'<span class="feature-chip">'
            f'{item}'
            '</span>'
        )

    st.markdown(
        f"""
        <div class="feature-row">

        {html}

        </div>
        """,
        unsafe_allow_html=True
    )


# ==========================================================
# HERO
# ==========================================================

def render_hero(

    username: str,

    total_chats: int = 0,

    total_pdfs: int = 0

):

    st.markdown(
        f"""
        <div class="hero-card">

            <div class="hero-title">

                {APP_ICON} {APP_NAME}

            </div>

            <div class="hero-subtitle">

                Hello <b>{username}</b> 👋

                <br><br>

                {APP_SUBTITLE}

            </div>

        </div>
        """,
        unsafe_allow_html=True
    )

    render_badges(
        FEATURES
    )

    divider()

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.markdown(
            """
            <div class="stat-card">

                <div class="stat-number">
                {}
                </div>

                <div class="stat-label">
                Chats
                </div>

            </div>
            """.format(total_chats),
            unsafe_allow_html=True
        )

    with col2:

        st.markdown(
            """
            <div class="stat-card">

                <div class="stat-number">
                {}
                </div>

                <div class="stat-label">
                PDFs
                </div>

            </div>
            """.format(total_pdfs),
            unsafe_allow_html=True
        )

    with col3:

        st.markdown(
            """
            <div class="stat-card">

                <div class="stat-number">

                AI

                </div>

                <div class="stat-label">

                Assistant

                </div>

            </div>
            """,
            unsafe_allow_html=True
        )

    with col4:

        st.markdown(
            """
            <div class="stat-card">

                <div class="stat-number">

                ✓

                </div>

                <div class="stat-label">

                Ready

                </div>

            </div>
            """,
            unsafe_allow_html=True
        )


# ==========================================================
# EMPTY CHAT
# ==========================================================

def empty_chat():

    st.markdown(
        """
        <div class="glass-card">

            <h2>

                👋 Welcome

            </h2>

            <p>

                Upload PDFs or ask me anything.

            </p>

        </div>
        """,
        unsafe_allow_html=True
    )


# ==========================================================
# FOOTER
# ==========================================================

def render_footer():

    divider()

    st.markdown(
        f"""
        <div style="

        text-align:center;

        color:#94A3B8;

        padding:20px;

        ">

        {FOOTER}

        </div>
        """,
        unsafe_allow_html=True
    )
# ==========================================================
# CARD HELPER
# ==========================================================

def render_card(
    title: str,
    content: str,
    css_class: str = "answer-card"
):
    """
    Generic card renderer.
    """

    if not content:
        return

    st.markdown(
        f"""
        <div class="{css_class}">
            <h3>{title}</h3>
            <div>
                {content}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ==========================================================
# ANSWER
# ==========================================================

def render_answer(answer: str):

    if not answer:
        return

    render_card(
        "📘 Answer",
        answer,
        "answer-card"
    )


# ==========================================================
# NOTES
# ==========================================================

def render_notes(notes: str):

    if not notes:
        return

    render_card(
        "📝 Notes",
        notes,
        "notes-card"
    )


# ==========================================================
# QUIZ
# ==========================================================

def render_quiz(quiz: str):

    if not quiz:
        return

    render_card(
        "❓ Quiz",
        quiz,
        "quiz-card"
    )


# ==========================================================
# COMPARISON
# ==========================================================

def render_comparison(comparison: str):

    if not comparison:
        return

    render_card(
        "⚖️ Comparison",
        comparison,
        "answer-card"
    )


# ==========================================================
# DIAGRAM
# ==========================================================

def render_diagram(diagram: str):

    if not diagram:
        return

    section_title(
        "📊 Diagram",
        "Generated Mermaid diagram"
    )

    st.code(
        diagram,
        language="mermaid"
    )


# ==========================================================
# CHAT RESPONSE
# ==========================================================

def render_chat(chat: str):

    if not chat:
        return

    st.markdown(chat)


# ==========================================================
# RESULT RENDERER
# ==========================================================

def render_result(result: dict):
    """
    Render every response section.
    """

    if not result:
        return

    render_chat(
        result.get("chat")
    )

    render_answer(
        result.get("answer")
    )

    render_notes(
        result.get("notes")
    )

    render_quiz(
        result.get("quiz")
    )

    render_comparison(
        result.get("comparison")
    )

    render_diagram(
        result.get("diagram")
    )
# ==========================================================
# YOUTUBE VIDEOS
# ==========================================================

def render_videos(videos):

    if not videos:
        return

    section_title(
        "📺 Recommended Videos",
        "YouTube resources"
    )

    for video in videos:

        if not isinstance(video, dict):
            continue

        title = video.get("title", "Untitled")
        channel = video.get("channel", "Unknown")
        description = video.get("description", "")
        url = video.get("url", "")

        st.markdown(
            f"""
            <div class="glass-card">

            <h3>{title}</h3>

            <p>
            <b>Channel:</b> {channel}
            </p>

            <p>
            {description[:220]}
            </p>

            </div>
            """,
            unsafe_allow_html=True
        )

        if url:
            st.link_button(
                "▶ Watch on YouTube",
                url,
                use_container_width=True
            )

        st.write("")


# ==========================================================
# RESEARCH PAPERS
# ==========================================================

def render_papers(papers):

    if not papers:
        return

    section_title(
        "📄 Research Papers",
        "Recommended papers"
    )

    for paper in papers:

        if not isinstance(paper, dict):
            continue

        title = paper.get("title", "Untitled")

        authors = paper.get("authors", [])

        published = paper.get("published", "")

        summary = paper.get("summary", "")

        pdf = (
            paper.get("pdf_url")
            or paper.get("url")
            or ""
        )

        author_text = ", ".join(authors)

        st.markdown(
            f"""
            <div class="glass-card">

            <h3>{title}</h3>

            <p>

            <b>Authors</b><br>

            {author_text}

            </p>

            <p>

            <b>Published</b><br>

            {published}

            </p>

            </div>
            """,
            unsafe_allow_html=True
        )

        if summary:

            with st.expander(
                "Abstract"
            ):

                st.write(summary)

        if pdf:

            st.link_button(
                "📄 Read Paper",
                pdf,
                use_container_width=True
            )

        st.write("")


# ==========================================================
# SOURCES
# ==========================================================

def render_sources(sources):

    if not sources:
        return

    section_title(
        "📚 Sources",
        "Knowledge retrieved from PDFs"
    )

    unique_sources = []

    for src in sources:

        if not isinstance(src, dict):
            continue

        name = src.get("source")

        if (
            name
            and name not in unique_sources
        ):

            unique_sources.append(name)

    badges = ""

    for src in unique_sources:

        badges += (
            f'<span class="badge">📄 {src}</span>'
        )

    st.markdown(
        badges,
        unsafe_allow_html=True
    )

    with st.expander(
        "View Detailed Sources"
    ):

        for src in sources:

            if not isinstance(src, dict):
                continue

            st.markdown(
                f"""
**PDF:** {src.get('source','Unknown')}

**Page:** {src.get('page','N/A')}

**Chunk:** {src.get('chunk_id','N/A')}
"""
            )

            st.divider()


# ==========================================================
# COMPLETE RESOURCE RENDERER
# ==========================================================

def render_resources(result):

    if not result:
        return

    render_videos(
        result.get("videos")
    )

    render_papers(
        result.get("papers")
    )

    render_sources(
        result.get("sources")
    )
# ==========================================================
# USER MESSAGE
# ==========================================================

def render_user_message(content: str):

    if not content:
        return

    st.markdown(content)


# ==========================================================
# ASSISTANT TEXT
# ==========================================================

def render_assistant_text(message: dict):

    if not message:
        return

    if message.get("chat"):

        st.markdown(
            message["chat"]
        )

    if message.get("answer"):

        render_answer(
            message["answer"]
        )

    if message.get("comparison"):

        render_comparison(
            message["comparison"]
        )

    if message.get("notes"):

        render_notes(
            message["notes"]
        )

    if message.get("quiz"):

        render_quiz(
            message["quiz"]
        )

    if message.get("diagram"):

        render_diagram(
            message["diagram"]
        )


# ==========================================================
# ASSISTANT RESOURCES
# ==========================================================

def render_assistant_resources(message: dict):

    if not message:
        return

    render_videos(
        message.get("videos", [])
    )

    render_papers(
        message.get("papers", [])
    )

    render_sources(
        message.get("sources", [])
    )


# ==========================================================
# COMPLETE ASSISTANT MESSAGE
# ==========================================================

def render_assistant_message(message: dict):

    render_assistant_text(
        message
    )

    render_assistant_resources(
        message
    )


# ==========================================================
# SINGLE CHAT MESSAGE
# ==========================================================

def render_message(message: dict):

    if not message:
        return

    role = message.get(
        "role",
        "assistant"
    )

    with st.chat_message(role):

        if role == "user":

            render_user_message(
                message.get(
                    "content",
                    ""
                )
            )

        else:

            render_assistant_message(
                message
            )


# ==========================================================
# CHAT HISTORY
# ==========================================================

def render_chat_history(messages):

    if not messages:
        return

    for message in messages:

        render_message(
            message
        )


# ==========================================================
# LIVE RESPONSE
# ==========================================================

def render_live_response(result):

    if not result:
        return

    render_assistant_text(
        result
    )

    render_assistant_resources(
        result
    )