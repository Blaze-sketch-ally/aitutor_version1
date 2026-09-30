"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "../../lib/AuthContext";
import AuthShell, {
  inputStyle,
  primaryButtonStyle,
  secondaryButtonStyle,
  PasswordField,
  FieldError,
  FieldNote,
} from "../../components/AuthShell";

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, signInWithPassword, resendConfirmationEmail } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [needsConfirmation, setNeedsConfirmation] = useState(false);
  const [resent, setResent] = useState(false);

  // Already logged in — bounce forward. Only fires the opposite
  // direction of app/page.js's guard, so the two can't loop.
  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setNeedsConfirmation(false);
    setResent(false);
    setBusy(true);
    try {
      await signInWithPassword(email.trim(), password);
      router.push("/");
    } catch (err) {
      // Supabase's exact message for an unconfirmed account — offer to
      // resend rather than just showing a dead-end error.
      if (/email not confirmed/i.test(err.message || "")) {
        setNeedsConfirmation(true);
        setError("Your email isn't confirmed yet. Check your inbox, or resend the confirmation link below.");
      } else {
        setError(err.message || "Login failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleResend() {
    setError("");
    try {
      await resendConfirmationEmail(email.trim());
      setResent(true);
    } catch (err) {
      setError(err.message || "Could not resend the confirmation email.");
    }
  }

  if (loading || user) return null;

  return (
    <AuthShell title="Welcome back" subtitle="Log in to continue to Athena.">
      {(t) => (
        <>
          <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <input
              type="email"
              placeholder="Email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              style={inputStyle(t)}
            />
            <PasswordField
              t={t}
              placeholder="Password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <FieldError t={t}>{error}</FieldError>
            {needsConfirmation && !resent && (
              <button
                type="button"
                onClick={handleResend}
                style={{ ...secondaryButtonStyle(t), marginTop: -4 }}
              >
                Resend confirmation email
              </button>
            )}
            {resent && <FieldNote t={t}>Confirmation email sent — check your inbox.</FieldNote>}
            <button type="submit" disabled={busy} style={primaryButtonStyle(busy)}>
              {busy ? "Logging in..." : "Log in"}
            </button>
          </form>

          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 16, fontSize: 12.5 }}>
            <Link href="/forgot-password" style={{ color: t.textDim, textDecoration: "none" }}>
              Forgot password?
            </Link>
            <Link href="/register" style={{ color: t.accent, textDecoration: "none", fontWeight: 600 }}>
              Create account
            </Link>
          </div>
        </>
      )}
    </AuthShell>
  );
}
