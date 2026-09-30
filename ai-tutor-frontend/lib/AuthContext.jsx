"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "./supabaseClient";

const AuthContext = createContext(null);

function toDisplayUser(session) {
  if (!session?.user) return null;
  const meta = session.user.user_metadata || {};
  return {
    id: session.user.id,
    email: session.user.email,
    name: meta.full_name || meta.name || null,
    avatarUrl: meta.avatar_url || null,
  };
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;

    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      setSession(data.session);
      setLoading(false);
    });

    // Fires on sign-in, sign-out, and token refresh — this single
    // subscription keeps `user`/`session` current everywhere the
    // context is read, including across browser refreshes (Supabase
    // persists the session in localStorage by default).
    const { data: listener } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      if (!active) return;
      setSession(nextSession);
      setLoading(false);
    });

    return () => {
      active = false;
      listener.subscription.unsubscribe();
    };
  }, []);

  const value = {
    user: toDisplayUser(session),
    session,
    loading,

    async signInWithPassword(email, password) {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw error;
    },

    async signUpWithPassword(email, password) {
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        // Explicit, so the confirmation link always lands back on
        // whichever origin the app is actually running on (dev or
        // prod) instead of depending on the Supabase dashboard's
        // "Site URL" default — that's easy to forget to update after
        // deploying and would otherwise send confirmations to
        // localhost from a production signup.
        options: { emailRedirectTo: `${window.location.origin}/login` },
      });
      if (error) throw error;
      // data.session is null when the project requires email
      // confirmation before a session is issued, and set immediately
      // otherwise — the caller (app/register/page.js) uses this to
      // decide whether to redirect straight in or show a "check your
      // email" notice instead.
      return { confirmedImmediately: !!data.session };
    },

    async signOut() {
      const { error } = await supabase.auth.signOut();
      if (error) throw error;
    },

    // Step 1 of password reset — triggers Supabase's "Reset Password"
    // email, which needs to be configured to show {{ .Token }} (a
    // 6-digit code) rather than only a clickable link — see
    // app/forgot-password/page.js for the rest of the flow.
    async requestPasswordResetOtp(email) {
      const { error } = await supabase.auth.resetPasswordForEmail(email);
      if (error) throw error;
    },

    // Step 2 — verifying the code establishes a real (recovery)
    // session, same as clicking the link would have, so the immediate
    // updatePassword() call below works normally.
    async verifyPasswordResetOtp(email, token) {
      const { error } = await supabase.auth.verifyOtp({ email, token, type: "recovery" });
      if (error) throw error;
    },

    async updatePassword(newPassword) {
      const { error } = await supabase.auth.updateUser({ password: newPassword });
      if (error) throw error;
    },

    // Re-sends the signup confirmation email — used by /login when
    // signInWithPassword fails with Supabase's "Email not confirmed"
    // error, so a user whose confirmation email got lost/expired isn't
    // stuck.
    async resendConfirmationEmail(email) {
      const { error } = await supabase.auth.resend({
        type: "signup",
        email,
        options: { emailRedirectTo: `${window.location.origin}/login` },
      });
      if (error) throw error;
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth() must be used inside an <AuthProvider>.");
  }
  return ctx;
}
