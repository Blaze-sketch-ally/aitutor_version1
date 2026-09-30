"use client";

import { useEffect, useMemo, useState } from "react";
import { Eye, EyeOff, Sparkles } from "lucide-react";
import { loadTheme } from "../lib/auth";
import { THEMES, FONT_IMPORT } from "../lib/theme";

// Shared chrome for /login, /register, /forgot-password
// — reuses the app's own theme tokens (lib/theme.js) instead of
// inventing a separate visual identity for these pages.
export default function AuthShell({ title, subtitle, children }) {
  const [theme, setTheme] = useState("dark");

  useEffect(() => {
    setTheme(loadTheme());
  }, []);

  const t = useMemo(() => THEMES[theme], [theme]);

  return (
    <div
      style={{
        width: "100vw",
        height: "100vh",
        minHeight: 640,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: t.bg,
        fontFamily: "Inter,sans-serif",
        padding: 20,
        boxSizing: "border-box",
      }}
    >
      <style>{`${FONT_IMPORT}`}</style>

      <div
        style={{
          width: "100%",
          maxWidth: 380,
          background: t.panel,
          border: `1px solid ${t.panelBorder}`,
          borderRadius: 18,
          padding: "32px 28px",
          backdropFilter: "blur(20px)",
          boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 22 }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 9,
              background: "linear-gradient(135deg,#7C5CFC,#C026D3)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <Sparkles size={17} color="#fff" />
          </div>
          <span
            style={{
              fontFamily: "'Space Grotesk',sans-serif",
              fontWeight: 700,
              fontSize: 17,
              color: t.text,
            }}
          >
            Athena
          </span>
        </div>

        <h1
          style={{
            fontFamily: "'Space Grotesk',sans-serif",
            fontWeight: 700,
            fontSize: 21,
            color: t.text,
            margin: "0 0 6px",
          }}
        >
          {title}
        </h1>

        {subtitle && (
          <p style={{ fontSize: 13, color: t.textDim, margin: "0 0 22px", lineHeight: 1.5 }}>
            {subtitle}
          </p>
        )}
        {!subtitle && <div style={{ marginBottom: 10 }} />}

        {children(t)}
      </div>
    </div>
  );
}

export const inputStyle = (t) => ({
  width: "100%",
  boxSizing: "border-box",
  background: t.input,
  border: `1px solid ${t.panelBorder}`,
  borderRadius: 10,
  padding: "10px 12px",
  fontSize: 13.5,
  color: t.text,
  outline: "none",
  fontFamily: "Inter,sans-serif",
});

// Password input with a show/hide toggle. Same visual shape as a plain
// inputStyle() field — just wrapped so the eye button can sit inside it.
export function PasswordField({ t, value, onChange, placeholder, autoComplete, required }) {
  const [visible, setVisible] = useState(false);

  return (
    <div style={{ position: "relative" }}>
      <input
        type={visible ? "text" : "password"}
        placeholder={placeholder}
        autoComplete={autoComplete}
        value={value}
        onChange={onChange}
        required={required}
        style={{ ...inputStyle(t), paddingRight: 38 }}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        title={visible ? "Hide password" : "Show password"}
        style={{
          position: "absolute",
          right: 4,
          top: "50%",
          transform: "translateY(-50%)",
          width: 28,
          height: 28,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          border: "none",
          background: "transparent",
          color: t.textFaint,
          cursor: "pointer",
        }}
      >
        {visible ? <Eye size={15} /> : <EyeOff size={15} />}
      </button>
    </div>
  );
}

export const primaryButtonStyle = (disabled) => ({
  width: "100%",
  padding: "10px 12px",
  borderRadius: 10,
  border: "none",
  cursor: disabled ? "default" : "pointer",
  background: "linear-gradient(135deg,#7C5CFC,#6339E8)",
  color: "#fff",
  fontFamily: "Inter,sans-serif",
  fontWeight: 600,
  fontSize: 13.5,
  opacity: disabled ? 0.6 : 1,
});

export const secondaryButtonStyle = (t) => ({
  width: "100%",
  padding: "10px 12px",
  borderRadius: 10,
  border: `1px solid ${t.panelBorderStrong}`,
  cursor: "pointer",
  background: "transparent",
  color: t.text,
  fontFamily: "Inter,sans-serif",
  fontWeight: 600,
  fontSize: 13.5,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  gap: 8,
});

export function FieldError({ t, children }) {
  if (!children) return null;
  return (
    <div style={{ fontSize: 12.5, color: "#F87171", marginTop: -6, marginBottom: 4 }}>
      {children}
    </div>
  );
}

export function FieldNote({ t, children }) {
  if (!children) return null;
  return (
    <div style={{ fontSize: 12.5, color: t.textDim, marginTop: -6, marginBottom: 4 }}>
      {children}
    </div>
  );
}
