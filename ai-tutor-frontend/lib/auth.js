// User session persistence is now handled by Supabase Auth itself
// (lib/supabaseClient.js / lib/AuthContext.jsx) — this file only keeps
// the theme preference, which is unrelated to auth.

const THEME_KEY = "ai_tutor_theme";

export function saveTheme(theme) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(THEME_KEY, theme);
}

export function loadTheme() {
  if (typeof window === "undefined") return "dark";
  return window.localStorage.getItem(THEME_KEY) || "dark";
}
