import { ExternalLink, ShieldCheck, ShieldQuestion } from "lucide-react";

export default function ExternalActionCard({ data, t }) {
  if (!data || !data.action) return null;

  const { message } = data;
  const { label, url, service, source_type } = data.action;

  const isOfficial = source_type === "official";

  return (
    <div
      style={{
        marginTop: 10,
        padding: 16,
        borderRadius: 14,
        border: `1px solid ${t.panelBorder}`,
        background: t.panel,
        maxWidth: 420,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
        <span style={{ fontWeight: 700, fontSize: 13.5, color: t.text }}>{service}</span>
        <span
          title={isOfficial ? "Official source" : "Could not be fully verified as official"}
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            fontSize: 10.5, fontWeight: 700, textTransform: "uppercase", letterSpacing: 0.4,
            padding: "2px 7px", borderRadius: 6,
            background: isOfficial ? t.input : t.input,
            color: isOfficial ? t.accent : t.textFaint,
          }}
        >
          {isOfficial ? <ShieldCheck size={11} /> : <ShieldQuestion size={11} />}
          {isOfficial ? "Official" : "Unverified"}
        </span>
      </div>

      {message && (
        <div style={{ fontSize: 13, color: t.textDim, marginBottom: 12, lineHeight: 1.5 }}>
          {message}
        </div>
      )}

      <a
        href={url}
        target="_blank"
        rel="noreferrer"
        style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "8px 14px", borderRadius: 9,
          background: t.accent, color: "#fff",
          fontSize: 13, fontWeight: 600, textDecoration: "none",
        }}
      >
        {label} <ExternalLink size={14} />
      </a>
    </div>
  );
}
