"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Plus, Search, MessageSquare, FileText, ChevronLeft, Moon, Sun, User,
  Send, Sparkles, Settings as SettingsIcon, LogOut, Trash2, Pencil, Check, X,
  Mic, Square, Menu, RefreshCw, AlertTriangle,
} from "lucide-react";

import * as api from "../lib/api";
import { saveTheme, loadTheme } from "../lib/auth";
import { useAuth } from "../lib/AuthContext";
import { THEMES, FONT_IMPORT } from "../lib/theme";
import { useVoiceInput } from "../lib/useVoiceInput";
import { MessageExtras, MessageText, buildAssistantText } from "./MessageRenderer";
import { MessageActions } from "./MessageActions";
import ExternalActionCard from "./ExternalActionCard";
import AttachmentMenu from "./AttachmentMenu";
import AttachmentPreview from "./AttachmentPreview";

const VIDEO_EXTENSIONS = ["mp4", "mov", "mkv", "webm", "avi", "m4a", "mp3", "wav"];
const MAX_IMAGES_PER_MESSAGE = 5; // mirrors the backend's default MAX_IMAGES_PER_MESSAGE — backend remains authoritative
const SUPPORTED_IMAGE_MIME_TYPES = ["image/png", "image/jpeg", "image/webp"];

function buildDisplayText(query, images, video) {
  // Mirrors services/chat_api_service.py's _persist_turn() prefix
  // logic exactly, so the optimistic bubble shown here matches what
  // gets persisted and shown again after a history reload.
  const prefixes = [];
  if (video) prefixes.push(`📎 ${video.name}`);
  images.forEach((img) => prefixes.push(`🖼️ ${img.file.name}`));

  if (!prefixes.length) return query;

  const prefix = prefixes.join("\n");
  return query ? `${prefix}\n\n${query}` : prefix;
}

function Nebula({ t }) {
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", borderRadius: "inherit" }}>
      <div style={{
        position: "absolute", width: 420, height: 420, top: -140, left: -80,
        background: `radial-gradient(circle, ${t.glow1}55 0%, transparent 70%)`,
        filter: "blur(10px)", animation: "drift1 18s ease-in-out infinite",
      }} />
      <div style={{
        position: "absolute", width: 380, height: 380, top: 40, right: -100,
        background: `radial-gradient(circle, ${t.glow2}40 0%, transparent 70%)`,
        filter: "blur(10px)", animation: "drift2 22s ease-in-out infinite",
      }} />
    </div>
  );
}

function rowIconBtn(t) {
  return {
    flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
    width: 22, height: 22, padding: 0, border: "none", borderRadius: 6,
    background: "transparent", color: t.textDim, opacity: 0.75, cursor: "pointer",
  };
}

function IconBtn({ children, onClick, t, title, ...rest }) {
  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      {...rest}
      style={{
        width: 34, height: 34, borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "center",
        background: "transparent", border: "1px solid transparent", color: t.textDim, cursor: "pointer",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = t.panel)}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      {children}
    </button>
  );
}

export default function AITutorApp() {
  const { user, loading: authLoading, signOut } = useAuth();

  const [theme, setThemeState] = useState("dark");
  const [view, setView] = useState("chat");

  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState("");

  const [messages, setMessages] = useState([]);
  const [pdfs, setPdfs] = useState([]);
  const [selectedPdfs, setSelectedPdfs] = useState([]);

  const [input, setInput] = useState("");
  const [pendingVideo, setPendingVideo] = useState(null);
  const [pendingImages, setPendingImages] = useState([]);
  const [justUploadedPdfs, setJustUploadedPdfs] = useState([]);
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState("");

  // Responsive layout: below 768px the sidebar becomes an overlay drawer
  // (hamburger in the header) instead of permanently taking 250px.
  const [isMobile, setIsMobile] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Loading a saved chat can fail transiently (network/database). A
  // failure must never look like the data was deleted: keep what is on
  // screen for this chat, show a retryable error, and block sending
  // until the chat (and its PDF selection) has actually loaded.
  // loadError: { sessionId, history: bool, pdfs: bool } | null
  const [loadError, setLoadError] = useState(null);
  const currentSessionRef = useRef(null);
  const historyLoadedForRef = useRef(null);
  const pdfsLoadedForRef = useRef(null);

  // Two-step delete: first click asks, second click deletes.
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  // Streaming chat (feature: streaming responses / stop generation).
  // streamingSid identifies which assistant message (by its __sid tag)
  // is currently receiving chunks — only that message shows the Stop
  // button's target state; non-streamed sends (images/video) never set
  // this, so they keep behaving exactly as before.
  const [streamingSid, setStreamingSid] = useState(null);
  const abortControllerRef = useRef(null);
  // Mutable, updated on every chunk (refs, not state, so handleStop can
  // read the latest accumulated text synchronously without waiting on
  // a render): { sid, query, mode, sources, text }
  const activeStreamRef = useRef(null);

  // Edit user message (feature: edit user message).
  const [editingIndex, setEditingIndex] = useState(null);
  const [editValue, setEditValue] = useState("");

  const {
    supported: micSupported,
    listening: micListening,
    toggle: toggleMic,
  } = useVoiceInput({
    onResult: (transcript) => {
      setInput((prev) => (prev ? `${prev.trim()} ${transcript}` : transcript));
    },
    onError: (msg) => setNotice(msg),
  });

  const scrollRef = useRef(null);
  const pendingImagesRef = useRef(pendingImages);

  const t = useMemo(() => THEMES[theme], [theme]);

  useEffect(() => {
    pendingImagesRef.current = pendingImages;
  }, [pendingImages]);

  // Revoke any remaining preview object URLs on unmount, using the
  // ref (not the state) so this always sees the latest attachments
  // rather than whatever was pending the first time this effect ran.
  useEffect(() => {
    return () => {
      pendingImagesRef.current.forEach(
        (img) => img.previewUrl && URL.revokeObjectURL(img.previewUrl)
      );
    };
  }, []);

  const attachmentItems = useMemo(() => {
    const items = pendingImages.map((img) => ({
      id: img.id,
      kind: "image",
      name: img.file.name,
      size: img.file.size,
      previewUrl: img.previewUrl,
      status: img.status,
      error: img.error,
    }));

    if (pendingVideo) {
      items.push({
        id: "pending-video",
        kind: "video",
        name: pendingVideo.name,
        size: pendingVideo.size,
        status: "selected",
      });
    }

    justUploadedPdfs.forEach((pdf) => {
      items.push({
        id: `pending-pdf-${pdf.name}`,
        kind: "pdf",
        name: pdf.name,
        status: "ready",
      });
    });

    return items;
  }, [pendingImages, pendingVideo, justUploadedPdfs]);

  // A PDF-only attachment never counts on its own (see handlePdfPicked
  // — it's already indexed/included via selectedPdfs, not something
  // this composer "sends" as a file), and an image whose frontend
  // pre-check already flagged it "error" is excluded here too, so the
  // send button's enabled state always matches what handleSend() will
  // actually do.
  const canSend =
    !!input.trim() ||
    pendingImages.some((img) => img.status !== "error") ||
    !!pendingVideo;

  // ---------- bootstrap: theme ----------
  // Auth state itself (user/loading) comes from AuthContext — app/page.js
  // is what redirects to /login when unauthenticated, so this component
  // only needs to react to `user` once it's known.
  useEffect(() => {
    setThemeState(loadTheme());
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const update = () => {
      setIsMobile(mq.matches);
      if (!mq.matches) setSidebarOpen(false);
    };
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);

  // Escape closes the mobile drawer / a pending delete confirmation.
  useEffect(() => {
    function onKey(e) {
      if (e.key !== "Escape") return;
      setSidebarOpen(false);
      setConfirmDeleteId(null);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (user) refreshSessions();
  }, [user]);

  useEffect(() => {
    currentSessionRef.current = sessionId;
    setLoadError(null);
    setConfirmDeleteId(null);

    if (sessionId) {
      loadHistory(sessionId);
      loadPdfState(sessionId);
    } else {
      setMessages([]);
      setPdfs([]);
      setSelectedPdfs([]);
      historyLoadedForRef.current = null;
      pdfsLoadedForRef.current = null;
    }

    // Composer attachments are per-conversation drafts, not per-account
    // — clear them on every session switch so a pending image/video
    // never leaks into a different chat.
    setPendingImages((prev) => {
      prev.forEach((img) => img.previewUrl && URL.revokeObjectURL(img.previewUrl));
      return [];
    });
    setPendingVideo(null);
    setJustUploadedPdfs([]);
    setNotice("");

    // A streaming/editing turn belongs to the session it started in —
    // don't let it (or a stale edit box) leak into a different chat.
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    activeStreamRef.current = null;
    setStreamingSid(null);
    setEditingIndex(null);
    setEditValue("");
  }, [sessionId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  function setTheme(next) {
    setThemeState(next);
    saveTheme(next);
  }

  async function refreshSessions(preferredId) {
    try {
      const list = await api.listSessions();
      setSessions(list || []);
      if (preferredId) {
        setSessionId(preferredId);
      } else if (!sessionId && list && list.length > 0) {
        setSessionId(list[0].session_id);
      }
    } catch (e) {
      setNotice(e.message);
    }
  }

  function markLoadError(id, part, failed) {
    setLoadError((prev) => {
      const base = prev && prev.sessionId === id ? prev : { sessionId: id, history: false, pdfs: false };
      const next = { ...base, [part]: failed };
      return next.history || next.pdfs ? next : null;
    });
  }

  // Failure never empties this chat's already-loaded messages. If the
  // failed load is for a DIFFERENT chat than the one on screen, the old
  // chat's messages are cleared (they'd be wrong here) and the error
  // panel is shown in their place — never the "empty chat" state.
  async function loadHistory(id) {
    try {
      const history = await api.getSessionHistory(id);
      if (currentSessionRef.current !== id) return; // user switched chats
      setMessages(history || []);
      historyLoadedForRef.current = id;
      markLoadError(id, "history", false);
    } catch (e) {
      if (currentSessionRef.current !== id) return;
      if (historyLoadedForRef.current !== id) setMessages([]);
      markLoadError(id, "history", true);
    }
  }

  async function loadPdfState(id) {
    try {
      const [pdfList, selected] = await Promise.all([
        api.getPdfs(id),
        api.getSelectedPdfs(id),
      ]);
      if (currentSessionRef.current !== id) return;
      setPdfs(pdfList || []);
      setSelectedPdfs(selected && selected.length ? selected : (pdfList || []).map((p) => p.name));
      pdfsLoadedForRef.current = id;
      markLoadError(id, "pdfs", false);
    } catch (e) {
      if (currentSessionRef.current !== id) return;
      if (pdfsLoadedForRef.current !== id) {
        setPdfs([]);
        setSelectedPdfs([]);
      }
      markLoadError(id, "pdfs", true);
    }
  }

  function retryLoad() {
    if (!sessionId || !loadError) return;
    if (loadError.history) loadHistory(sessionId);
    if (loadError.pdfs) loadPdfState(sessionId);
  }

  const chatLoadFailed = !!(loadError && loadError.sessionId === sessionId);

  async function handleLogout() {
    try {
      await signOut();
    } catch (e) {
      setNotice(e.message);
    }
    setSessions([]);
    setSessionId(null);
    setMessages([]);
  }

  async function handleNewChat() {
    try {
      const result = await api.createSession("New Chat");
      await refreshSessions(result.session_id);
      setView("chat");
      setSidebarOpen(false);
    } catch (e) {
      setNotice(e.message);
    }
  }

  async function handleRenameSave(id) {
    if (!renameValue.trim()) { setRenamingId(null); return; }
    try {
      await api.renameSession(id, renameValue.trim());
      setRenamingId(null);
      refreshSessions(id);
    } catch (e) {
      setNotice(e.message);
    }
  }

  async function handleDeleteSession(id) {
    setConfirmDeleteId(null);
    try {
      await api.deleteSession(id);
      if (id === sessionId) setSessionId(null);
      refreshSessions();
    } catch (e) {
      setNotice(e.message);
    }
  }

  function openSession(id) {
    setSessionId(id);
    setView("chat");
    setSidebarOpen(false);
  }

  function togglePdfSelection(name) {
    const next = selectedPdfs.includes(name)
      ? selectedPdfs.filter((p) => p !== name)
      : [...selectedPdfs, name];
    setSelectedPdfs(next);
    api.saveSelectedPdfs(sessionId, next).catch((e) => setNotice(e.message));
  }

  function handleImagesPicked(files) {
    if (!sessionId) return;

    const room = MAX_IMAGES_PER_MESSAGE - pendingImages.length;
    if (room <= 0) {
      setNotice(`You can attach up to ${MAX_IMAGES_PER_MESSAGE} images per message.`);
      return;
    }

    const accepted = files.slice(0, room);
    if (files.length > accepted.length) {
      setNotice(
        `Only the first ${accepted.length} image(s) were added — maximum ${MAX_IMAGES_PER_MESSAGE} images per message.`
      );
    }

    // Early, non-authoritative feedback only — the backend
    // (services/attachment_service.py) does the real MIME/content
    // validation and is what actually decides whether an image is
    // accepted.
    const newEntries = accepted.map((file) => {
      const supported = SUPPORTED_IMAGE_MIME_TYPES.includes(file.type);
      return {
        id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        file,
        previewUrl: supported ? URL.createObjectURL(file) : null,
        status: supported ? "selected" : "error",
        error: supported ? null : "Unsupported image format.",
      };
    });

    setPendingImages((prev) => [...prev, ...newEntries]);
  }

  async function handlePdfPicked(file) {
    if (!sessionId) return;

    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setNotice("Unsupported file type — please choose a PDF.");
      return;
    }

    setNotice(`Indexing ${file.name}...`);
    try {
      const result = await api.uploadPdf(sessionId, file);
      setNotice(`${result.pdf_name} indexed (${result.chunks_created ?? "?"} chunks).`);

      setJustUploadedPdfs((prev) =>
        prev.some((p) => p.name === result.pdf_name) ? prev : [...prev, { name: result.pdf_name }]
      );

      const nextSelected = selectedPdfs.includes(result.pdf_name)
        ? selectedPdfs
        : [...selectedPdfs, result.pdf_name];
      setSelectedPdfs(nextSelected);
      api.saveSelectedPdfs(sessionId, nextSelected).catch((e) => setNotice(e.message));

      loadPdfState(sessionId);
    } catch (err) {
      setNotice(err.message);
    }
  }

  function handleFilePicked(file) {
    if (!sessionId) return;

    const ext = "." + (file.name.split(".").pop() || "").toLowerCase();
    if (!VIDEO_EXTENSIONS.some((e) => `.${e}` === ext)) {
      setNotice("Unsupported file type — this option currently supports audio/video files.");
      return;
    }

    setPendingVideo(file);
  }

  function handleRemoveAttachment(item) {
    if (item.kind === "image") {
      setPendingImages((prev) => {
        const target = prev.find((p) => p.id === item.id);
        if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
        return prev.filter((p) => p.id !== item.id);
      });
      return;
    }

    if (item.kind === "video") {
      setPendingVideo(null);
      return;
    }

    if (item.kind === "pdf") {
      setJustUploadedPdfs((prev) => prev.filter((p) => p.name !== item.name));
      // Excludes it from THIS message's retrieval context only — it
      // stays indexed and still toggleable in the sidebar's PDF list.
      const next = selectedPdfs.filter((p) => p !== item.name);
      setSelectedPdfs(next);
      api.saveSelectedPdfs(sessionId, next).catch((e) => setNotice(e.message));
    }
  }

  // ---------- streaming turn (feature: streaming responses) ----------
  // Drives one assistant reply via POST /api/chat/stream. `mode.kind`
  // is "append" (normal send / edit-resend — adds a new placeholder
  // assistant message) or "replace" (regenerate — overwrites the
  // assistant message at mode.index in place). The caller is
  // responsible for the user-message side of things (appending a new
  // user bubble, or not, for regenerate).
  async function runStreamingTurn({ query, mode }) {
    const sid = `s-${Date.now()}-${Math.random().toString(36).slice(2)}`;

    setMessages((prev) => {
      const placeholder = { role: "assistant", content: "", __sid: sid, streaming: true };
      if (mode.kind === "append") return [...prev, placeholder];
      return prev.map((m, i) => (i === mode.index ? placeholder : m));
    });

    function patchMsg(patch) {
      setMessages((prev) => prev.map((m) => (m.__sid === sid ? { ...m, ...patch } : m)));
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    activeStreamRef.current = { sid, query, mode: "answer", sources: [], text: "" };
    setStreamingSid(sid);
    setSending(true);

    try {
      await api.streamChat({
        sessionId,
        query,
        selectedPdfs,
        signal: controller.signal,
        onStart: (payload) => {
          if (activeStreamRef.current?.sid === sid) {
            activeStreamRef.current.mode = payload.mode || "answer";
            activeStreamRef.current.sources = payload.sources || [];
          }
        },
        onChunk: (chunk) => {
          if (activeStreamRef.current?.sid !== sid) return;
          activeStreamRef.current.text += chunk;
          patchMsg({ content: activeStreamRef.current.text });
        },
        onDone: (result) => {
          const finalText = buildAssistantText(result) || activeStreamRef.current?.text || "";
          patchMsg({
            content: finalText,
            streaming: false,
            chat: result.chat,
            answer: result.answer,
            comparison: result.comparison,
            notes: result.notes,
            quiz: result.quiz,
            diagram: result.diagram,
            videos: result.videos || [],
            papers: result.papers || [],
            web_research: result.web_research,
            web_sources: result.web_sources || [],
            external_action: result.external_action || null,
            sources: result.sources || [],
            mode: result.mode,
            stopped: !!result.stopped,
          });
          if (activeStreamRef.current?.sid === sid) activeStreamRef.current = null;
          refreshSessions(sessionId); // title may have just been set from first message
        },
        onError: (message) => {
          const fallback = activeStreamRef.current?.text || `⚠️ ${message}`;
          patchMsg({ content: fallback, streaming: false });
          setNotice(message);
          if (activeStreamRef.current?.sid === sid) activeStreamRef.current = null;
        },
      });
    } catch (e) {
      if (e.name !== "AbortError") {
        // A real network/error failure (not a user-initiated Stop,
        // which is handled by handleStop itself).
        const fallback = activeStreamRef.current?.text || `⚠️ ${e.message}`;
        patchMsg({ content: fallback, streaming: false });
        setNotice(e.message);
        if (activeStreamRef.current?.sid === sid) activeStreamRef.current = null;
      }
    } finally {
      if (abortControllerRef.current === controller) abortControllerRef.current = null;
      setStreamingSid((cur) => (cur === sid ? null : cur));
      setSending(false);
    }
  }

  // ---------- stop generation (feature: stop generation button) ----------
  async function handleStop() {
    const stream = activeStreamRef.current;
    abortControllerRef.current?.abort();

    if (!stream) {
      setSending(false);
      setStreamingSid(null);
      return;
    }

    const { sid, query, mode, sources, text } = stream;
    activeStreamRef.current = null;

    // Preserve exactly what was generated so far — don't delete it.
    setMessages((prev) =>
      prev.map((m) => (m.__sid === sid ? { ...m, content: text, streaming: false, stopped: true } : m))
    );
    setStreamingSid(null);
    setSending(false);

    try {
      await api.stopChat(sessionId, query, selectedPdfs, mode, text, sources);
    } catch (e) {
      setNotice(`Could not save the stopped response: ${e.message}`);
    }
  }

  // ---------- regenerate response (feature: regenerate response) ----------
  // Only offered on the LAST assistant message (see the render below) —
  // regenerating an earlier one would mean silently discarding every
  // message that came after it, which the spec only calls for on
  // Edit (an explicit, visible action), not Regenerate.
  async function handleRegenerate(index) {
    if (sending) return;

    const userIndex = index - 1;
    const userMsg = messages[userIndex];
    if (!userMsg || userMsg.role !== "user") return;

    if (userMsg.content?.startsWith("📎") || userMsg.content?.startsWith("🖼️")) {
      setNotice("Note: the original attachment can't be re-analyzed in a regenerated response — regenerating from the text only.");
    }

    setSending(true);
    try {
      await api.truncateHistory(sessionId, userIndex);
    } catch (e) {
      setNotice(e.message);
      setSending(false);
      return;
    }

    await runStreamingTurn({ query: userMsg.content, mode: { kind: "replace", index } });
  }

  // ---------- edit user message (feature: edit user message) ----------
  async function handleEditSave(index, newText) {
    const trimmed = newText.trim();
    if (!trimmed || sending) {
      setEditingIndex(null);
      return;
    }

    setSending(true);
    try {
      await api.truncateHistory(sessionId, index);
    } catch (e) {
      setNotice(e.message);
      setSending(false);
      return;
    }

    setMessages((prev) => [...prev.slice(0, index), { role: "user", content: trimmed }]);
    setEditingIndex(null);
    setEditValue("");

    await runStreamingTurn({ query: trimmed, mode: { kind: "append" } });
  }

  function handleEditCancel() {
    setEditingIndex(null);
    setEditValue("");
  }

  async function handleSend() {
    if (!sessionId || sending || chatLoadFailed) return;

    const query = input.trim();
    const validImages = pendingImages.filter((img) => img.status !== "error");
    const hasImages = validImages.length > 0;
    const hasVideo = !!pendingVideo;

    if (!query && !hasImages && !hasVideo) return;

    if (!hasImages && !hasVideo) {
      // Plain text turn — stream it. Images/video keep using the
      // existing non-streaming request/response path below unchanged.
      setInput("");
      setMessages((prev) => [...prev, { role: "user", content: query }]);
      await runStreamingTurn({ query, mode: { kind: "append" } });
      return;
    }

    const displayText = buildDisplayText(query, validImages, pendingVideo);

    const userMessage = { role: "user", content: displayText };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setSending(true);

    if (hasImages) {
      setPendingImages((prev) =>
        prev.map((img) => (img.status !== "error" ? { ...img, status: "processing" } : img))
      );
    }

    try {
      let result;
      if (hasImages) {
        result = await api.sendChatWithImages(
          sessionId, query, selectedPdfs, validImages.map((img) => img.file)
        );
      } else if (hasVideo) {
        result = await api.sendChatWithVideo(sessionId, query, selectedPdfs, pendingVideo);
      } else {
        result = await api.sendChat(sessionId, query, selectedPdfs);
      }

      const assistantMessage = {
        role: "assistant",
        content: buildAssistantText(result),
        chat: result.chat,
        answer: result.answer,
        comparison: result.comparison,
        notes: result.notes,
        quiz: result.quiz,
        diagram: result.diagram,
        videos: result.videos || [],
        papers: result.papers || [],
        web_research: result.web_research,
        web_sources: result.web_sources || [],
        external_action: result.external_action || null,
        sources: result.sources || [],
        mode: result.mode,
        video_source: result.video_source,
        video_source_ref: result.video_source_ref,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      refreshSessions(sessionId); // title may have just been set from first message
    } catch (e) {
      setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ ${e.message}` }]);
    } finally {
      pendingImages.forEach((img) => img.previewUrl && URL.revokeObjectURL(img.previewUrl));
      setPendingImages([]);
      setPendingVideo(null);
      setJustUploadedPdfs([]);
      setSending(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  // app/page.js owns the redirect-to-/login guard (and shows its own
  // loading state while auth is resolving) — this is just a safe
  // fallback so nothing below ever renders with a null user.
  if (authLoading || !user) return null;

  const activeSession = sessions.find((s) => s.session_id === sessionId);

  return (
    <div style={{
      width: "100%", height: "100%", borderRadius: isMobile ? 0 : 18, overflow: "hidden",
      background: t.bg, display: "flex", fontFamily: "Inter,sans-serif",
      border: isMobile ? "none" : `1px solid ${t.panelBorder}`, position: "relative", boxSizing: "border-box",
    }}>
      <style>{`
        ${FONT_IMPORT}
        @keyframes drift1 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(30px,20px); } }
        @keyframes drift2 { 0%,100% { transform: translate(0,0); } 50% { transform: translate(-25px,-15px); } }
        @keyframes micPulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-thumb { background: ${t.scrollbar}; border-radius: 8px; }
        ::-webkit-scrollbar-track { background: transparent; }
        input::placeholder, textarea::placeholder { color: ${t.textFaint}; }
      `}</style>

      {/* ---------------- SIDEBAR ---------------- */}
      {/* Desktop: fixed 250px column (unchanged). Mobile: off-canvas
          drawer over the chat, opened from the header's menu button. */}
      {isMobile && sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
          style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.55)", zIndex: 40 }}
        />
      )}
      <nav
        id="app-sidebar"
        aria-label="Chats and PDFs"
        aria-hidden={isMobile && !sidebarOpen ? true : undefined}
        style={{
          width: isMobile ? "min(280px, 86vw)" : 250, flexShrink: 0, display: "flex", flexDirection: "column",
          borderRight: `1px solid ${t.panelBorder}`, background: isMobile ? t.bg : t.panel, backdropFilter: "blur(20px)",
          ...(isMobile ? {
            position: "absolute", top: 0, bottom: 0, left: 0, zIndex: 50,
            transform: sidebarOpen ? "translateX(0)" : "translateX(-105%)",
            visibility: sidebarOpen ? "visible" : "hidden",
            transition: "transform 0.2s ease, visibility 0.2s",
            boxShadow: sidebarOpen ? "0 0 40px rgba(0,0,0,0.5)" : "none",
          } : {}),
        }}
      >
        <div style={{ padding: "18px 16px 10px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 18 }}>
            <div style={{
              width: 30, height: 30, borderRadius: 9, background: "linear-gradient(135deg,#7C5CFC,#C026D3)",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>
              <Sparkles size={16} color="#fff" />
            </div>
            <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 700, fontSize: 16, color: t.text }}>
              Athena
            </span>
            {isMobile && (
              <div style={{ marginLeft: "auto" }}>
                <IconBtn t={t} onClick={() => setSidebarOpen(false)} title="Close menu">
                  <X size={16} />
                </IconBtn>
              </div>
            )}
          </div>

          <button
            onClick={handleNewChat}
            style={{
              width: "100%", padding: "9px 12px", borderRadius: 10, border: "none", cursor: "pointer",
              background: "linear-gradient(135deg,#7C5CFC,#6339E8)", color: "#fff", fontFamily: "Inter,sans-serif",
              fontWeight: 600, fontSize: 13.5, display: "flex", alignItems: "center", gap: 8,
              boxShadow: "0 4px 16px rgba(124,92,252,0.35)",
            }}
          >
            <Plus size={16} /> New Chat
          </button>
        </div>

        <div style={{ flex: 1, overflowY: "auto", padding: "4px 12px" }}>
          <div style={{ fontSize: 11, letterSpacing: 0.6, color: t.textFaint, fontWeight: 600, margin: "10px 6px 6px", textTransform: "uppercase" }}>
            Chats
          </div>
          {sessions.map((s) => (
            <div
              key={s.session_id}
              style={{
                display: "flex", alignItems: "center", gap: 6, padding: "7px 8px", borderRadius: 9,
                marginBottom: 2, fontSize: 13, fontFamily: "Inter,sans-serif",
                background: s.session_id === sessionId ? t.accentSoft : "transparent",
                color: s.session_id === sessionId ? t.text : t.textDim,
                border: s.session_id === sessionId ? `1px solid ${t.panelBorderStrong}` : "1px solid transparent",
              }}
            >
              {renamingId === s.session_id ? (
                <>
                  <input
                    autoFocus
                    aria-label="Chat name"
                    value={renameValue}
                    onChange={(e) => setRenameValue(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleRenameSave(s.session_id)}
                    style={{
                      flex: 1, background: t.input, border: `1px solid ${t.panelBorder}`, borderRadius: 6,
                      color: t.text, fontSize: 12.5, padding: "3px 6px", outline: "none",
                    }}
                  />
                  <button type="button" aria-label="Save chat name" title="Save" onClick={() => handleRenameSave(s.session_id)} style={rowIconBtn(t)}>
                    <Check size={13} />
                  </button>
                  <button type="button" aria-label="Cancel rename" title="Cancel" onClick={() => setRenamingId(null)} style={rowIconBtn(t)}>
                    <X size={13} />
                  </button>
                </>
              ) : confirmDeleteId === s.session_id ? (
                <div role="alertdialog" aria-label="Confirm delete" style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12, color: t.text, marginBottom: 6 }}>
                    Delete “{s.title || "New Chat"}” permanently? Its messages and PDFs will be removed.
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    <button
                      type="button"
                      autoFocus
                      onClick={() => handleDeleteSession(s.session_id)}
                      style={{
                        padding: "4px 10px", borderRadius: 7, border: "none", cursor: "pointer",
                        background: "#DC2626", color: "#fff", fontSize: 12, fontWeight: 600,
                      }}
                    >
                      Delete
                    </button>
                    <button
                      type="button"
                      onClick={() => setConfirmDeleteId(null)}
                      style={{
                        padding: "4px 10px", borderRadius: 7, cursor: "pointer", fontSize: 12,
                        background: "transparent", border: `1px solid ${t.panelBorder}`, color: t.textDim,
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => openSession(s.session_id)}
                    aria-current={s.session_id === sessionId ? "page" : undefined}
                    style={{
                      flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 6, padding: 0,
                      background: "transparent", border: "none", color: "inherit", font: "inherit",
                      cursor: "pointer", textAlign: "left",
                    }}
                  >
                    <MessageSquare size={14} style={{ flexShrink: 0, opacity: 0.75 }} aria-hidden="true" />
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {s.title || "New Chat"}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Rename chat ${s.title || "New Chat"}`}
                    title="Rename"
                    onClick={() => { setRenamingId(s.session_id); setRenameValue(s.title || ""); }}
                    style={rowIconBtn(t)}
                  >
                    <Pencil size={12} />
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete chat ${s.title || "New Chat"}`}
                    title="Delete"
                    onClick={() => setConfirmDeleteId(s.session_id)}
                    style={rowIconBtn(t)}
                  >
                    <Trash2 size={12} />
                  </button>
                </>
              )}
            </div>
          ))}

          <div style={{ fontSize: 11, letterSpacing: 0.6, color: t.textFaint, fontWeight: 600, margin: "16px 6px 6px", textTransform: "uppercase" }}>
            Indexed PDFs
          </div>
          {chatLoadFailed && loadError.pdfs ? (
            <div role="status" style={{ fontSize: 12, color: "#F59E0B", padding: "0 6px" }}>
              Couldn't load this chat's PDFs — use Retry.
            </div>
          ) : pdfs.length === 0 && (
            <div style={{ fontSize: 12, color: t.textFaint, padding: "0 6px" }}>None yet — attach one in chat.</div>
          )}
          {pdfs.map((pdf) => (
            <label
              key={pdf.name}
              style={{ display: "flex", alignItems: "center", gap: 7, padding: "5px 6px", fontSize: 12.5, color: t.textDim, cursor: "pointer" }}
            >
              <input
                type="checkbox"
                checked={selectedPdfs.includes(pdf.name)}
                onChange={() => togglePdfSelection(pdf.name)}
              />
              <FileText size={13} style={{ flexShrink: 0, opacity: 0.7 }} aria-hidden="true" />
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{pdf.name}</span>
            </label>
          ))}
        </div>

        <div style={{ padding: 12, borderTop: `1px solid ${t.panelBorder}` }}>
          <button
            type="button"
            onClick={() => { setView("settings"); setSidebarOpen(false); }}
            aria-current={view === "settings" ? "page" : undefined}
            style={{
              width: "100%", display: "flex", alignItems: "center", gap: 8, padding: "8px 10px", borderRadius: 9, cursor: "pointer",
              fontSize: 13, color: view === "settings" ? t.accent : t.textDim, border: "none", textAlign: "left",
              background: view === "settings" ? t.accentSoft : "transparent", marginBottom: 8, fontFamily: "Inter,sans-serif",
            }}
          >
            <SettingsIcon size={14} aria-hidden="true" /> Settings &amp; log out
          </button>
          <div style={{ display: "flex", alignItems: "center", gap: 9, padding: "6px 4px" }}>
            <div style={{
              width: 30, height: 30, borderRadius: "50%", background: "linear-gradient(135deg,#7C5CFC,#F472B6)",
              display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
            }}>
              <User size={15} color="#fff" />
            </div>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: t.text, overflowWrap: "anywhere" }}>{user.name || user.email}</div>
          </div>
        </div>
      </nav>

      {/* ---------------- MAIN ---------------- */}
      {view === "settings" ? (
        <div style={{ flex: 1, overflowY: "auto", padding: isMobile ? "18px 16px" : "28px 40px", minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
            {isMobile && (
              <IconBtn t={t} onClick={() => setSidebarOpen(true)} title="Open menu" aria-expanded={sidebarOpen} aria-controls="app-sidebar">
                <Menu size={16} />
              </IconBtn>
            )}
            <IconBtn t={t} onClick={() => setView("chat")} title="Back to chat"><ChevronLeft size={16} /></IconBtn>
            <span style={{ fontFamily: "'Space Grotesk',sans-serif", fontWeight: 700, fontSize: 20, color: t.text }}>Settings</span>
          </div>
          <div style={{ maxWidth: 480 }}>
            <div style={{ padding: 18, borderRadius: 14, background: t.panel, border: `1px solid ${t.panelBorder}`, marginBottom: 18 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textFaint, textTransform: "uppercase", marginBottom: 10 }}>Appearance</div>
              <div style={{ display: "flex", gap: 6, background: t.input, padding: 3, borderRadius: 10, width: "fit-content" }}>
                <button onClick={() => setTheme("light")} style={{
                  display: "flex", alignItems: "center", gap: 5, padding: "6px 11px", borderRadius: 8, border: "none",
                  cursor: "pointer", fontSize: 12, background: theme === "light" ? t.accent : "transparent",
                  color: theme === "light" ? "#fff" : t.textDim,
                }}><Sun size={13} /> Light</button>
                <button onClick={() => setTheme("dark")} style={{
                  display: "flex", alignItems: "center", gap: 5, padding: "6px 11px", borderRadius: 8, border: "none",
                  cursor: "pointer", fontSize: 12, background: theme === "dark" ? t.accent : "transparent",
                  color: theme === "dark" ? "#fff" : t.textDim,
                }}><Moon size={13} /> Dark</button>
              </div>
            </div>
            <div style={{ padding: 18, borderRadius: 14, background: t.panel, border: `1px solid ${t.panelBorder}` }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: t.textFaint, textTransform: "uppercase", marginBottom: 10 }}>Account</div>
              <div style={{ fontSize: 13.5, color: t.text, marginBottom: 12 }}>{user.name || user.email}</div>
              <button onClick={handleLogout} style={{
                display: "flex", alignItems: "center", gap: 7, padding: "8px 13px", borderRadius: 9, cursor: "pointer",
                background: "transparent", border: `1px solid ${t.panelBorderStrong}`, color: "#F87171", fontSize: 12.5,
              }}>
                <LogOut size={14} /> Log out
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}>
          {theme === "dark" && <Nebula t={t} />}

          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8,
            padding: isMobile ? "10px 10px" : "14px 22px",
            borderBottom: `1px solid ${t.panelBorder}`, position: "relative", zIndex: 1,
          }}>
            {isMobile && (
              <IconBtn t={t} onClick={() => setSidebarOpen(true)} title="Open menu" aria-expanded={sidebarOpen} aria-controls="app-sidebar">
                <Menu size={18} />
              </IconBtn>
            )}
            <span style={{
              fontFamily: "'Space Grotesk',sans-serif", fontWeight: 600, fontSize: 15, color: t.text,
              flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            }}>
              {activeSession?.title || "Athena"}
            </span>
            {isMobile && (
              <IconBtn t={t} onClick={handleNewChat} title="New chat">
                <Plus size={17} />
              </IconBtn>
            )}
            <IconBtn t={t} onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="Toggle theme">
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </IconBtn>
          </div>

          <div ref={scrollRef} style={{
            flex: 1, overflowY: "auto", overflowX: "hidden", padding: isMobile ? "16px 12px" : "24px 22px",
            position: "relative", zIndex: 1, minWidth: 0,
          }}>
            {chatLoadFailed && (
              <div role="alert" style={{
                display: "flex", alignItems: "flex-start", gap: 10, maxWidth: 640, margin: "0 auto 16px",
                padding: "12px 14px", borderRadius: 12, border: "1px solid rgba(245,158,11,0.45)",
                background: "rgba(245,158,11,0.10)", color: t.text, fontSize: 13,
              }}>
                <AlertTriangle size={16} color="#F59E0B" style={{ flexShrink: 0, marginTop: 1 }} aria-hidden="true" />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>Couldn't load your saved chat.</div>
                  <div style={{ color: t.textDim, fontSize: 12.5 }}>
                    Nothing has been deleted — this is a temporary connection problem.
                    {messages.length > 0 ? " Showing what was already loaded." : ""} Please retry.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={retryLoad}
                  style={{
                    display: "flex", alignItems: "center", gap: 6, padding: "6px 11px", borderRadius: 8,
                    border: "none", cursor: "pointer", background: "linear-gradient(135deg,#7C5CFC,#6339E8)",
                    color: "#fff", fontSize: 12.5, fontWeight: 600, flexShrink: 0,
                  }}
                >
                  <RefreshCw size={13} aria-hidden="true" /> Retry
                </button>
              </div>
            )}

            {!sessionId && (
              <div style={{ textAlign: "center", color: t.textFaint, marginTop: 60, fontSize: 13.5 }}>
                Create a new chat to get started.
              </div>
            )}

            {messages.map((m, i) => {
              const isLastAssistant =
                m.role === "assistant" && i === messages.length - 1 && !m.streaming && !sending;

              return (
                <div key={i} style={{ maxWidth: 640, minWidth: 0, marginBottom: 16, marginLeft: m.role === "user" ? "auto" : 0 }}>
                  {m.role === "user" ? (
                    editingIndex === i ? (
                      <div>
                        <textarea
                          autoFocus
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                              e.preventDefault();
                              handleEditSave(i, editValue);
                            } else if (e.key === "Escape") {
                              handleEditCancel();
                            }
                          }}
                          rows={Math.min(6, Math.max(2, editValue.split("\n").length))}
                          style={{
                            width: "100%", boxSizing: "border-box", background: t.input, color: t.text,
                            border: `1px solid ${t.panelBorderStrong}`, borderRadius: 12, padding: "10px 12px",
                            fontSize: 13.5, fontFamily: "Inter,sans-serif", resize: "vertical", outline: "none",
                          }}
                        />
                        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 6 }}>
                          <button
                            onClick={handleEditCancel}
                            style={{
                              padding: "6px 12px", borderRadius: 8, border: `1px solid ${t.panelBorder}`,
                              background: "transparent", color: t.textDim, fontSize: 12.5, cursor: "pointer",
                            }}
                          >
                            Cancel
                          </button>
                          <button
                            onClick={() => handleEditSave(i, editValue)}
                            disabled={!editValue.trim() || sending}
                            style={{
                              padding: "6px 12px", borderRadius: 8, border: "none",
                              background: "linear-gradient(135deg,#7C5CFC,#6339E8)", color: "#fff",
                              fontSize: 12.5, cursor: "pointer",
                              opacity: !editValue.trim() || sending ? 0.5 : 1,
                            }}
                          >
                            Save &amp; Resend
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div>
                        <div style={{
                          background: t.bubbleUser, color: "#fff", padding: "11px 16px", borderRadius: "14px 14px 4px 14px",
                          fontSize: 13.5, lineHeight: 1.5, whiteSpace: "pre-wrap",
                        }}>
                          {m.content}
                        </div>
                        {!sending && (
                          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 4 }}>
                            <button
                              onClick={() => { setEditingIndex(i); setEditValue(m.content); }}
                              title="Edit message"
                              style={{
                                display: "flex", alignItems: "center", gap: 4, padding: "3px 7px", borderRadius: 6,
                                border: "none", background: "transparent", color: t.textFaint, fontSize: 11,
                                cursor: "pointer",
                              }}
                            >
                              <Pencil size={11} /> Edit
                            </button>
                          </div>
                        )}
                      </div>
                    )
                  ) : (
                    <div style={{ display: "flex", gap: 10 }}>
                      <div style={{
                        width: 26, height: 26, borderRadius: 8, background: "linear-gradient(135deg,#7C5CFC,#C026D3)",
                        display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, marginTop: 2,
                      }}>
                        <Sparkles size={13} color="#fff" />
                      </div>
                      <div style={{
                        background: t.panel, border: `1px solid ${t.panelBorder}`, borderRadius: "4px 14px 14px 14px",
                        padding: isMobile ? "12px 12px" : "14px 16px", color: t.text, fontSize: 13.5, lineHeight: 1.6, flex: 1, minWidth: 0,
                      }}>
                        {m.mode === "video_summary" && m.video_source_ref && (
                          <div style={{ fontSize: 11.5, color: t.textFaint, marginBottom: 8 }}>
                            🎬 Summarized from: {m.video_source_ref}
                          </div>
                        )}
                        <MessageText content={m.content} t={t} streaming={!!m.streaming} />
                        {m.stopped && (
                          <div style={{ fontSize: 11, color: t.textFaint, marginTop: 4, fontStyle: "italic" }}>
                            Stopped
                          </div>
                        )}
                        {!m.streaming && m.content && (
                          <MessageActions
                            text={m.content}
                            t={t}
                            onRegenerate={isLastAssistant ? () => handleRegenerate(i) : undefined}
                          />
                        )}
                        {m.external_action?.action && <ExternalActionCard data={m.external_action} t={t} />}
                        <MessageExtras message={m} t={t} />
                      </div>
                    </div>
                  )}
                </div>
              );
            })}

            {sending && !streamingSid && (
              <div style={{ fontSize: 12.5, color: t.textFaint, paddingLeft: 36 }}>
                {pendingImages.some((img) => img.status === "processing") ? "Analyzing image..." : "Thinking..."}
              </div>
            )}
          </div>

          <div style={{ padding: isMobile ? "8px 10px 12px" : "14px 22px 20px", position: "relative", zIndex: 1 }}>
            {notice && (
              <div style={{ maxWidth: 780, margin: "0 auto 8px", fontSize: 12, color: t.textDim }}>{notice}</div>
            )}

            <AttachmentPreview t={t} items={attachmentItems} onRemove={handleRemoveAttachment} />

            <div style={{
              display: "flex", alignItems: "center", gap: 8, padding: "10px 12px", borderRadius: 14,
              background: t.input, border: `1px solid ${t.panelBorder}`, maxWidth: 780, margin: "0 auto",
            }}>
              <AttachmentMenu
                t={t}
                disabled={!sessionId || sending || chatLoadFailed}
                onPickImages={handleImagesPicked}
                onPickPdf={handlePdfPicked}
                onPickFile={handleFilePicked}
              />
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  chatLoadFailed ? "Retry loading this chat to continue"
                    : micListening ? "Listening..." : "Ask your AI Tutor... (or paste a YouTube link)"
                }
                aria-label="Message"
                disabled={!sessionId || sending || chatLoadFailed}
                style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 13.5, minWidth: 0 }}
              />
              {micSupported && (
                <button
                  onClick={toggleMic}
                  title={micListening ? "Stop recording" : "Speak your question"}
                  aria-label={micListening ? "Stop recording" : "Speak your question"}
                  style={{
                    display: "flex", alignItems: "center", justifyContent: "center",
                    width: 26, height: 26, borderRadius: 8, border: "none", cursor: "pointer",
                    background: micListening ? "rgba(239,68,68,0.15)" : "transparent",
                    color: micListening ? "#EF4444" : t.textFaint,
                    animation: micListening ? "micPulse 1.4s ease-in-out infinite" : "none",
                    flexShrink: 0,
                  }}
                >
                  <Mic size={15} />
                </button>
              )}
              {streamingSid ? (
                <button
                  onClick={handleStop}
                  aria-label="Stop generating"
                  title="Stop generating"
                  style={{
                    width: 32, height: 32, borderRadius: 10, border: "none", cursor: "pointer",
                    background: "#EF4444", display: "flex", alignItems: "center",
                    justifyContent: "center", flexShrink: 0,
                  }}
                >
                  <Square size={13} color="#fff" fill="#fff" />
                </button>
              ) : (
                <button
                  onClick={handleSend}
                  disabled={!sessionId || sending || !canSend || chatLoadFailed}
                  aria-label="Send message"
                  title="Send message"
                  style={{
                    width: 32, height: 32, borderRadius: 10, border: "none", cursor: "pointer",
                    background: "linear-gradient(135deg,#7C5CFC,#6339E8)", display: "flex", alignItems: "center",
                    justifyContent: "center", flexShrink: 0,
                    opacity: (!sessionId || sending || !canSend) ? 0.5 : 1,
                  }}
                >
                  <Send size={14} color="#fff" />
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
