"use client";

import { useEffect, useRef, useState } from "react";
import { Plus, Image as ImageIcon, FileText, Paperclip } from "lucide-react";

const MENU_ITEMS = [
  {
    key: "images",
    icon: ImageIcon,
    label: "Add photos & images",
    description: "Upload images for AI analysis",
  },
  {
    key: "pdf",
    icon: FileText,
    label: "Upload PDF",
    description: "Ask questions from your PDF",
  },
  {
    key: "files",
    icon: Paperclip,
    label: "Upload files",
    description: "Add audio/video for AI Tutor to summarize",
  },
];

// Matches the backend's actual current MIME acceptance for each
// picker (see AI_Tutor/services/attachment_service.py for images,
// api/pdf.py for PDFs, api/chat.py's /video route's supported
// extensions for the general "files" option) — the backend remains
// authoritative regardless of what's set here.
const IMAGE_ACCEPT = "image/png,image/jpeg,image/webp";
const PDF_ACCEPT = "application/pdf,.pdf";
const FILE_ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4a,.mp3,.wav";

export default function AttachmentMenu({
  t,
  disabled,
  onPickImages,
  onPickPdf,
  onPickFile,
}) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);
  const imageInputRef = useRef(null);
  const pdfInputRef = useRef(null);
  const fileInputRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;

    function handleOutside(e) {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    function handleEscape(e) {
      if (e.key === "Escape") setOpen(false);
    }

    document.addEventListener("mousedown", handleOutside);
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("mousedown", handleOutside);
      document.removeEventListener("keydown", handleEscape);
    };
  }, [open]);

  function handleItemClick(key) {
    setOpen(false);
    if (key === "images") imageInputRef.current?.click();
    if (key === "pdf") pdfInputRef.current?.click();
    if (key === "files") fileInputRef.current?.click();
  }

  return (
    <div ref={containerRef} style={{ position: "relative", flexShrink: 0 }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-label="Add attachment"
        aria-haspopup="menu"
        aria-expanded={open}
        title="Add photos, a PDF, or a file"
        style={{
          width: 30,
          height: 30,
          borderRadius: 9,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: `1px solid ${t.panelBorder}`,
          cursor: disabled ? "default" : "pointer",
          background: open ? t.accentSoft : "transparent",
          color: open ? t.accent : t.textFaint,
          opacity: disabled ? 0.5 : 1,
          flexShrink: 0,
        }}
      >
        <Plus size={16} />
      </button>

      <input
        ref={imageInputRef}
        type="file"
        hidden
        multiple
        accept={IMAGE_ACCEPT}
        onChange={(e) => {
          const files = Array.from(e.target.files || []);
          e.target.value = "";
          if (files.length) onPickImages(files);
        }}
      />
      <input
        ref={pdfInputRef}
        type="file"
        hidden
        accept={PDF_ACCEPT}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) onPickPdf(file);
        }}
      />
      <input
        ref={fileInputRef}
        type="file"
        hidden
        accept={FILE_ACCEPT}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) onPickFile(file);
        }}
      />

      {open && (
        <div
          role="menu"
          aria-label="Attachment options"
          style={{
            position: "absolute",
            bottom: "calc(100% + 8px)",
            left: 0,
            minWidth: 240,
            maxWidth: "min(300px, 90vw)",
            background: t.panel,
            border: `1px solid ${t.panelBorderStrong}`,
            borderRadius: 12,
            boxShadow: "0 12px 32px rgba(0,0,0,0.35)",
            padding: 6,
            zIndex: 20,
            backdropFilter: "blur(20px)",
          }}
        >
          {MENU_ITEMS.map(({ key, icon: Icon, label, description }) => (
            <button
              key={key}
              role="menuitem"
              type="button"
              onClick={() => handleItemClick(key)}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "9px 10px",
                borderRadius: 8,
                border: "none",
                background: "transparent",
                cursor: "pointer",
                textAlign: "left",
                fontFamily: "Inter,sans-serif",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = t.input)}
              onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              onFocus={(e) => (e.currentTarget.style.background = t.input)}
              onBlur={(e) => (e.currentTarget.style.background = "transparent")}
            >
              <Icon size={16} color={t.accent} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                <span style={{ display: "block", fontSize: 13, fontWeight: 600, color: t.text }}>
                  {label}
                </span>
                <span style={{ display: "block", fontSize: 11.5, color: t.textFaint, marginTop: 1 }}>
                  {description}
                </span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
