"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "../lib/AuthContext";
import AITutorApp from "../components/AITutorApp";

export default function Home() {
  const router = useRouter();
  const { user, loading } = useAuth();

  // Redirect only once loading has resolved — redirecting while still
  // loading would bounce a genuinely-logged-in user to /login before
  // their session had a chance to load from storage.
  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) return null;

  return (
    <div className="app-viewport">
      <AITutorApp />
    </div>
  );
}
