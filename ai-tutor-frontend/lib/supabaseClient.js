import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

if (!supabaseUrl || !supabaseAnonKey) {
  throw new Error(
    "NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY must be set (see .env.local.example)."
  );
}

// Plain browser client — this app has no Server Components/middleware
// anywhere a cookie-based (@supabase/ssr) session would matter, so the
// default localStorage-backed session (persistSession/autoRefreshToken
// on by default) is exactly what "stay logged in across a refresh"
// needs, with no extra wiring.
export const supabase = createClient(supabaseUrl, supabaseAnonKey);
