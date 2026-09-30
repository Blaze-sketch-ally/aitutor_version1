import { useEffect, useRef, useState, useCallback } from "react";

/**
 * Tap-to-start / tap-to-stop voice dictation via the browser's
 * SpeechRecognition API. Free, no API key, no network cost — but
 * browser support varies: solid in Chrome/Edge, absent in Firefox,
 * partial in Safari. `supported` tells the caller whether to render
 * the mic button at all.
 *
 * Usage:
 *   const { supported, listening, start, stop } = useVoiceInput({
 *     onResult: (text) => setInput((prev) => (prev ? prev + " " : "") + text),
 *     onError: (msg) => setNotice(msg),
 *   });
 */
export function useVoiceInput({ onResult, onError, lang = "en-US" } = {}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef(null);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      setSupported(false);
      return;
    }

    setSupported(true);

    const recognition = new SpeechRecognition();
    recognition.lang = lang;
    recognition.continuous = false;
    recognition.interimResults = false;

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map((result) => result[0].transcript)
        .join(" ")
        .trim();

      if (transcript) {
        onResult?.(transcript);
      }
    };

    recognition.onerror = (event) => {
      setListening(false);

      // "no-speech" and "aborted" happen on normal tap-to-stop / brief
      // silence — not real errors worth surfacing to the user.
      if (event.error === "no-speech" || event.error === "aborted") {
        return;
      }

      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        onError?.("Microphone access was blocked. Allow mic access in your browser settings to use voice input.");
        return;
      }

      onError?.(`Voice input error: ${event.error}`);
    };

    recognition.onend = () => {
      setListening(false);
    };

    recognitionRef.current = recognition;

    return () => {
      recognition.onresult = null;
      recognition.onerror = null;
      recognition.onend = null;
      try {
        recognition.abort();
      } catch (e) {
        // ignore — already stopped
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lang]);

  const start = useCallback(() => {
    if (!recognitionRef.current || listening) return;

    try {
      recognitionRef.current.start();
      setListening(true);
    } catch (e) {
      // start() throws if called while already started (e.g. a
      // double-click race) — safe to ignore.
    }
  }, [listening]);

  const stop = useCallback(() => {
    if (!recognitionRef.current) return;

    recognitionRef.current.stop();
    setListening(false);
  }, []);

  const toggle = useCallback(() => {
    if (listening) {
      stop();
    } else {
      start();
    }
  }, [listening, start, stop]);

  return { supported, listening, start, stop, toggle };
}
