# AI Tutor — Next.js Frontend

## Setup

```bash
npm install
cp .env.local.example .env.local   # edit if your FastAPI backend isn't on localhost:8000
npm run dev
```

Open http://localhost:3000. Your FastAPI backend (`uvicorn main:app --reload --port 8000`) needs to be running at the same time — this is a separate process, not something Next.js starts for you.

## What's wired up

- **Auth** — login/register hit `/api/auth/login` and `/api/auth/register`. On success, `{username, user_id}` is saved to `localStorage` so refreshing the page keeps you logged in (this was your choice — no real token/session cookie, just a client-side "remember who I am").
- **Sessions** — sidebar lists real sessions from `/api/session/list`, creates via `/api/session/create`, supports rename/delete inline.
- **Chat** — sends to `/api/chat/` (plain text, including pasted YouTube links) or `/api/chat/video` (when a video file is attached via the paperclip).
- **PDFs** — attaching a `.pdf` via the paperclip uploads through `/api/pdf/upload`; the sidebar's "Indexed PDFs" list reflects `/api/session/{id}/pdfs`, and checkboxes toggle retrieval scope via `/api/session/{id}/selected-pdfs`.
- **Diagrams** — mermaid and Pollinations-image diagram types render inline (chart.js diagrams render via Chart.js loaded from CDN). Videos/papers/sources render as tabs under each assistant message, same shape as `app_new.py`'s `render_extras`.
- **Theme** — dark/light toggle persists in `localStorage`.

## ⚠️ Known gap — chat history isn't persisted server-side yet

`app_new.py` (Streamlit) called `session_manager.save_history(session_id, messages)` itself, right in the script, after every turn. That call lived in the **Streamlit UI code**, not in `Orchestrator`, `ChatService`, or `ChatAPIService` — so it never made it into the API layer we built.

Practically, this means:
- Chat **works** in this frontend — messages send, responses render, extras (diagrams/videos/papers/sources) all display correctly.
- But `GET /api/session/{id}/history` will come back **empty or stale** next time you load a session, because nothing is writing to that table from the API path. Right now this frontend keeps the conversation in React state for the current tab session only — refresh the page or switch chats and away, and it's gone from the backend's perspective (though `messages` in the browser will still show it until then).

**To fix properly**, one of these needs to happen server-side:
1. Add a `save_history(username, session_id, messages)` method to `SessionService` (thin wrapper over `SessionManager.save_history`, same pattern as everything else there), plus a route in `api/session.py`, and have this frontend call it after every turn — same division of responsibility Streamlit had, just moved to the client.
2. Or, better long-term: have `ChatAPIService.run()` itself persist the turn immediately after getting a result back from `ChatService`, so *any* client (this frontend, a future mobile app, etc.) gets durable history for free without remembering to call a separate save endpoint.

I'd lean toward option 2 — it matches how every other piece of this backend already treats the API layer as the source of truth. Want me to implement that next?
