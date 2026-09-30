"use client";

import { FileText, Image as ImageIcon, Paperclip, X } from "lucide-react";

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function statusLabel(item) {
  if (item.status === "error") return item.error || "Unable to process";
  if (item.status === "processing") return "Analyzing...";
  if (item.status === "uploading") return "Uploading...";
  return null;
}

// items: [{ id, kind: "image"|"pdf"|"video", name, size, previewUrl, status, error }]
export default function AttachmentPreview({ t, items, onRemove }) {
  if (!items || items.length === 0) return null;

  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 8,
        maxWidth: 780,
        margin: "0 auto 8px",
      }}
    >
      {items.map((item) => {
        const isError = item.status === "error";
        const label = statusLabel(item);

        return (
          <div
            key={item.id}
            style={{
              position: "relative",
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: item.kind === "image" ? 6 : "8px 10px",
              borderRadius: 10,
              border: `1px solid ${isError ? "#F87171" : t.panelBorder}`,
              background: t.input,
              maxWidth: 220,
            }}
          >
            {item.kind === "image" ? (
              item.previewUrl ? (
                <img
                  src={item.previewUrl}
                  alt={item.name}
                  style={{
                    width: 40,
                    height: 40,
                    borderRadius: 7,
                    objectFit: "cover",
                    flexShrink: 0,
                  }}
                />
              ) : (
                <ImageIcon size={18} color={t.textFaint} style={{ flexShrink: 0 }} />
              )
            ) : item.kind === "pdf" ? (
              <FileText size={18} color={t.accent} style={{ flexShrink: 0 }} />
            ) : (
              <Paperclip size={18} color={t.textFaint} style={{ flexShrink: 0 }} />
            )}

            <div style={{ minWidth: 0, flex: 1 }}>
              <div
                title={item.name}
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: t.text,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {item.name}
              </div>
              {(item.size !== undefined || label) && (
                <div style={{ fontSize: 10.5, color: isError ? "#F87171" : t.textFaint }}>
                  {label || formatBytes(item.size)}
                </div>
              )}
            </div>

            <button
              type="button"
              onClick={() => onRemove(item)}
              aria-label={`Remove ${item.name}`}
              title={`Remove ${item.name}`}
              style={{
                width: 20,
                height: 20,
                borderRadius: 6,
                border: "none",
                background: "transparent",
                color: t.textFaint,
                cursor: "pointer",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <X size={13} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
