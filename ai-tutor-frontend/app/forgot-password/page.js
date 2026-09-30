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

// Two-step flow, both on this one page:
//   1. enter email -> requestPasswordResetOtp() sends a 6-digit code
//   2. enter that code + a new password -> verifyPasswordResetOtp()
//      establishes a session, then updatePassword() sets it
export default function ForgotPasswordPage() {
  const router = useRouter();
  const {
    user,
    loading,
    requestPasswordResetOtp,
    verifyPasswordResetOtp,
    updatePassword,
  } = useAuth();

  const [step, setStep] = useState("email"); // "email" | "code"
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!loading && user && step === "email") router.replace("/");
  }, [loading, user, step, router]);

  async function handleSendCode(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await requestPasswordResetOtp(email.trim());
      setStep("code");
    } catch (err) {
      setError(err.message || "Could not send the code.");
    } finally {
      setBusy(false);
    }
  }

  async function handleResetPassword(e) {
    e.preventDefault();
    setError("");

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
      await verifyPasswordResetOtp(email.trim(), code.trim());
      await updatePassword(password);
      setNotice("Password updated — taking you in...");
      setTimeout(() => router.push("/"), 1200);
    } catch (err) {
      setError(err.message || "Could not reset the password.");
    } finally {
      setBusy(false);
    }
  }

  if (loading || (user && step === "email")) return null;

  return (
    <AuthShell
      title={step === "email" ? "Reset your password" : "Enter your code"}
      subtitle={
        step === "email"
          ? "Enter your email and we'll send you a 6-digit code."
          : `We sent a code to ${email}. Enter it below along with your new password.`
      }
    >
      {(t) =>
        step === "email" ? (
          <>
            <form onSubmit={handleSendCode} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <input
                type="email"
                placeholder="Email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                style={inputStyle(t)}
              />
              <FieldError t={t}>{error}</FieldError>
              <button type="submit" disabled={busy} style={primaryButtonStyle(busy)}>
                {busy ? "Sending..." : "Send code"}
              </button>
            </form>

            <div style={{ marginTop: 16, fontSize: 12.5, textAlign: "center" }}>
              <Link href="/login" style={{ color: t.textDim, textDecoration: "none" }}>
                Back to login
              </Link>
            </div>
          </>
        ) : (
          <>
            <form onSubmit={handleResetPassword} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              <input
                type="text"
                inputMode="numeric"
                placeholder="6-digit code"
                autoComplete="one-time-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
                style={{ ...inputStyle(t), letterSpacing: 3, textAlign: "center" }}
              />
              <PasswordField
                t={t}
                placeholder="New password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <PasswordField
                t={t}
                placeholder="Confirm new password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
              <FieldError t={t}>{error}</FieldError>
              <FieldNote t={t}>{notice}</FieldNote>
              <button type="submit" disabled={busy} style={primaryButtonStyle(busy)}>
                {busy ? "Resetting..." : "Reset password"}
              </button>
            </form>

            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 16, fontSize: 12.5 }}>
              <button
                type="button"
                onClick={() => setStep("email")}
                style={{ background: "none", border: "none", padding: 0, cursor: "pointer", color: t.textDim }}
              >
                Use a different email
              </button>
              <button
                type="button"
                onClick={handleSendCode}
                disabled={busy}
                style={{
                  background: "none",
                  border: "none",
                  padding: 0,
                  cursor: busy ? "default" : "pointer",
                  color: t.accent,
                  fontWeight: 600,
                  opacity: busy ? 0.6 : 1,
                }}
              >
                {busy ? "Sending..." : "Resend code"}
              </button>
            </div>
          </>
        )
      }
    </AuthShell>
  );
}
