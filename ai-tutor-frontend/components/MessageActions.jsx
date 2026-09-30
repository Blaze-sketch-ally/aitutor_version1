import { useEffect, useRef, useState } from "react";
import { Copy, Check, Volume2, Square, RotateCcw } from "lucide-react";

/**
 * Strips the extra prefix words buildAssistantText() adds ("Comparison",
 * "Notes", "Quiz") so copy/speech reads naturally instead of literally
 * saying "Notes Notes here are your notes...". Adjust/remove if you'd
 * rather keep those headers.
 */
function cleanForSpeech(text) {
  return text
    .replace(/[#*_`>]/g, "")           // strip basic markdown symbols
    .replace(/\n{2,}/g, ". ")           // paragraph breaks -> pause
    .replace(/\n/g, " ")
    .trim();
}

export function MessageActions({ text, t, onRegenerate }) {
  const [copied, setCopied] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const utteranceRef = useRef(null);

  // Stop speech if the component unmounts mid-speech (e.g. user
  // switches chats while it's still talking) — otherwise it keeps
  // reading over whatever chat you switch to.
  useEffect(() => {
    return () => {
      if (typeof window !== "undefined") {
        window.speechSynthesis?.cancel();
      }
    };
  }, []);

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (e) {
      console.error("Copy failed:", e);
    }
  }

  function handleVoice() {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      console.error("Speech synthesis not supported in this browser.");
      return;
    }

    // Toggle off if already speaking this message.
    if (speaking) {
      window.speechSynthesis.cancel();
      setSpeaking(false);
      return;
    }

    // Cancel anything else currently speaking (only one at a time).
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(cleanForSpeech(text));
    utterance.rate = 1;
    utterance.pitch = 1;
    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);

    utteranceRef.current = utterance;
    setSpeaking(true);
    window.speechSynthesis.speak(utterance);
  }

  const btnStyle = {
    display: "inline-flex",
    alignItems: "center",
    gap: 5,
    padding: "5px 9px",
    borderRadius: 7,
    border: `1px solid ${t.panelBorder}`,
    background: "transparent",
    color: t.textFaint,
    fontSize: 11.5,
    fontFamily: "Inter,sans-serif",
    cursor: "pointer",
    transition: "color 0.15s, border-color 0.15s",
  };

  return (
    <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
      <button onClick={handleCopy} style={btnStyle} title="Copy message">
        {copied ? <Check size={13} /> : <Copy size={13} />}
        {copied ? "Copied" : "Copy"}
      </button>

      <button
        onClick={handleVoice}
        style={{
          ...btnStyle,
          color: speaking ? t.accent : t.textFaint,
          borderColor: speaking ? t.accent : t.panelBorder,
        }}
        title={speaking ? "Stop reading" : "Read aloud"}
      >
        {speaking ? <Square size={13} /> : <Volume2 size={13} />}
        {speaking ? "Stop" : "Listen"}
      </button>

      {onRegenerate && (
        <button onClick={onRegenerate} style={btnStyle} title="Regenerate response">
          <RotateCcw size={13} />
          Regenerate
        </button>
      )}
    </div>
  );
}
