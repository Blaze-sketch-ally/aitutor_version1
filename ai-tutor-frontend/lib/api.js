import { supabase } from "./supabaseClient";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function handle(res) {
  let data;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const message = (data && (data.detail || data.message)) || `Request failed (${res.status})`;
    throw new Error(message);
  }
  return data;
}

// Every call below is authenticated — the backend derives identity from
// this Bearer token (auth/jwt_bearer.py's get_current_user()) rather
// than trusting anything the client sends in the request itself. Reused
// everywhere so there's exactly one place that reads the current
// Supabase session.
async function authHeaders() {
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return session ? { Authorization: `Bearer ${session.access_token}` } : {};
}

// ---------- Sessions ----------

export async function createSession(title = "New Chat") {
  const res = await fetch(`${BASE_URL}/api/session/create`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ title }),
  });
  return handle(res);
}

export async function listSessions() {
  const res = await fetch(`${BASE_URL}/api/session/list`, {
    headers: await authHeaders(),
  });
  return handle(res);
}

export async function getSessionHistory(sessionId) {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/history`, {
    headers: await authHeaders(),
  });
  return handle(res);
}

export async function renameSession(sessionId, title) {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/rename`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ title }),
  });
  return handle(res);
}

export async function deleteSession(sessionId) {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });
  return handle(res);
}

// ---------- PDFs ----------

export async function getPdfs(sessionId) {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/pdfs`, {
    headers: await authHeaders(),
  });
  return handle(res);
}

export async function getSelectedPdfs(sessionId) {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/selected-pdfs`, {
    headers: await authHeaders(),
  });
  return handle(res);
}

export async function saveSelectedPdfs(sessionId, selectedPdfs) {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/selected-pdfs`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ selected_pdfs: selectedPdfs }),
  });
  return handle(res);
}

export async function uploadPdf(sessionId, file) {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("file", file);

  const res = await fetch(`${BASE_URL}/api/pdf/upload`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  return handle(res);
}

// ---------- Chat ----------

export async function sendChat(sessionId, query, selectedPdfs) {
  const res = await fetch(`${BASE_URL}/api/chat/`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({
      session_id: sessionId,
      query,
      selected_pdfs: selectedPdfs,
    }),
  });
  return handle(res);
}

export async function sendChatWithImages(sessionId, query, selectedPdfs, files) {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("query", query || "");
  form.append("selected_pdfs", JSON.stringify(selectedPdfs || []));
  files.forEach((file) => form.append("files", file));

  const res = await fetch(`${BASE_URL}/api/chat/images`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  return handle(res);
}

export async function sendChatWithVideo(sessionId, query, selectedPdfs, file) {
  const form = new FormData();
  form.append("session_id", sessionId);
  form.append("query", query || "");
  form.append("selected_pdfs", JSON.stringify(selectedPdfs || []));
  form.append("file", file);

  const res = await fetch(`${BASE_URL}/api/chat/video`, {
    method: "POST",
    headers: await authHeaders(),
    body: form,
  });
  return handle(res);
}

// ---------- Streaming chat ----------
//
// POST /api/chat/stream returns Server-Sent-Events frames
// ("data: {...}\n\n"). This reads the fetch response body manually
// (not the EventSource API, since that can't do POST, send a Bearer
// header, or take an AbortController signal) and dispatches parsed
// frames to the provided callbacks as they arrive.
//
// Frame shapes (see services/chat_api_service.py::stream()):
//   {"type": "start", "mode", "sources"}
//   {"type": "chunk", "content"}
//   {"type": "done", "result": {...}}
//   {"type": "error", "message"}
export async function streamChat({
  sessionId,
  query,
  selectedPdfs,
  signal,
  onStart,
  onChunk,
  onDone,
  onError,
}) {
  const res = await fetch(`${BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({
      session_id: sessionId,
      query,
      selected_pdfs: selectedPdfs || [],
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      message = (data && (data.detail || data.message)) || message;
    } catch {
      // no JSON body — keep the generic message
    }
    throw new Error(message);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);

      const line = rawEvent.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;

      const jsonStr = line.slice(5).trim();
      if (!jsonStr) continue;

      let payload;
      try {
        payload = JSON.parse(jsonStr);
      } catch {
        continue;
      }

      if (payload.type === "start") onStart?.(payload);
      else if (payload.type === "chunk") onChunk?.(payload.content);
      else if (payload.type === "done") onDone?.(payload.result);
      else if (payload.type === "error") onError?.(payload.message);
    }
  }
}

// Persists a turn that was cut short by the Stop button — see
// api/chat.py POST /api/chat/stream/stop.
export async function stopChat(sessionId, query, selectedPdfs, mode, partialText, sources) {
  const res = await fetch(`${BASE_URL}/api/chat/stream/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({
      session_id: sessionId,
      query,
      selected_pdfs: selectedPdfs || [],
      mode,
      partial_text: partialText,
      sources: sources || [],
    }),
  });
  return handle(res);
}

// Drops history after position `keepCount` — used before resending an
// edited message or regenerating a response, so the stale message(s)
// don't linger. See api/session.py PUT /{session_id}/truncate.
export async function truncateHistory(sessionId, keepCount) {
  const res = await fetch(`${BASE_URL}/api/session/${sessionId}/truncate`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", ...(await authHeaders()) },
    body: JSON.stringify({ keep_count: keepCount }),
  });
  return handle(res);
}
