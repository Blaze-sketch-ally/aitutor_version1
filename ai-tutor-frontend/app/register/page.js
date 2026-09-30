"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "../../lib/AuthContext";
import AuthShell, {
  inputStyle,
  primaryButtonStyle,
  PasswordField,
  FieldError,
  FieldNote,
} from "../../components/AuthShell";

export default function RegisterPage() {
  const router = useRouter();
  const { user, loading, signUpWithPassword } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user) router.replace("/");
  }, [loading, user, router]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setNotice("");

    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    setBusy(true);
    try {
      const { confirmedImmediately } = await signUpWithPassword(email.trim(), password);
      if (confirmedImmediately) {
        router.push("/");
      } else {
        setNotice("Account created — check your email to confirm it, then log in.");
      }
    } catch (err) {
      setError(err.message || "Registration failed.");
    } finally {
      setBusy(false);
    }
  }

  if (loading || user) return null;

  return (
    <AuthShell title="Create your account" subtitle="Start tutoring with Athena in a minute.">
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
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <PasswordField
              t={t}
              placeholder="Confirm password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
            <FieldError t={t}>{error}</FieldError>
            <FieldNote t={t}>{notice}</FieldNote>
            <button type="submit" disabled={busy} style={primaryButtonStyle(busy)}>
              {busy ? "Creating account..." : "Create account"}
            </button>
          </form>

          <div style={{ marginTop: 16, fontSize: 12.5, textAlign: "center" }}>
            <span style={{ color: t.textDim }}>Already have an account? </span>
            <Link href="/login" style={{ color: t.accent, textDecoration: "none", fontWeight: 600 }}>
              Log in
            </Link>
          </div>
        </>
      )}
    </AuthShell>
  );
}
