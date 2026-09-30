// Shared visual identity — originally defined inline in AITutorApp.jsx.
// Moved here so the new auth pages (login/register/forgot-password) can
// reuse the same palette/type instead of duplicating it; AITutorApp.jsx
// now imports from here too.

export const THEMES = {
  dark: {
    bg: "linear-gradient(160deg,#0B0A1A 0%,#120E2A 45%,#160F30 100%)",
    panel: "rgba(255,255,255,0.045)",
    panelBorder: "rgba(255,255,255,0.08)",
    panelBorderStrong: "rgba(255,255,255,0.14)",
    text: "#EDEBFB",
    textDim: "#9C96C4",
    textFaint: "#6B6590",
    accent: "#7C5CFC",
    accentSoft: "rgba(124,92,252,0.16)",
    bubbleUser: "linear-gradient(135deg,#7C5CFC,#5B3FE0)",
    input: "rgba(255,255,255,0.05)",
    glow1: "#7C5CFC",
    glow2: "#C026D3",
    scrollbar: "rgba(255,255,255,0.15)",
  },
  light: {
    bg: "linear-gradient(160deg,#F7F5FF 0%,#F0EDFC 50%,#EAE6FA 100%)",
    panel: "rgba(255,255,255,0.65)",
    panelBorder: "rgba(124,92,252,0.12)",
    panelBorderStrong: "rgba(124,92,252,0.22)",
    text: "#241E3D",
    textDim: "#6B6590",
    textFaint: "#9891B8",
    accent: "#6D28D9",
    accentSoft: "rgba(109,40,217,0.10)",
    bubbleUser: "linear-gradient(135deg,#8B6CFF,#6D28D9)",
    input: "rgba(255,255,255,0.8)",
    glow1: "#C4B5FD",
    glow2: "#F0ABFC",
    scrollbar: "rgba(109,40,217,0.15)",
  },
};

export const FONT_IMPORT = `@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');`;
