-- ============================================================
-- Supabase Auth migration for AI Tutor
-- ============================================================
-- Adds a `profiles` table keyed to Supabase Auth (auth.users), a
-- trigger to auto-populate it on signup, and Row Level Security
-- policies across every table the app touches.
--
-- IMPORTANT — RLS here is DEFENSE IN DEPTH, not the primary
-- authorization boundary. The FastAPI backend talks to Supabase using
-- the service-role key (see database/supabase_client.py's SUPABASE_KEY,
-- format "sb_secret_..."), which bypasses RLS entirely by design. The
-- actual authorization boundary is the FastAPI/service layer:
--   - auth/jwt_bearer.py verifies the caller's JWT and derives user_id
--   - memory/session_manager.py's SessionManager scopes every query by
--     that verified user_id, and _assert_session_owned() rejects
--     cross-user session_id access before it reaches these tables
-- These RLS policies only matter if the anon/publishable key is ever
-- used to talk to Supabase directly from the browser (not the case
-- today — the frontend only talks to FastAPI) or if the service-role
-- key ever leaks. Enabling RLS is still correct hygiene regardless.
--
-- CLEAN CUTOVER NOTE: the old custom-auth `users` table and every row
-- in `sessions`/`messages`/`pdfs`/`selected_pdfs`/`document_chunks`
-- created under it are intentionally left as-is and NOT migrated —
-- see the migration plan. New rows going forward hold `auth.users`
-- UUIDs in their `user_id`/transitive-ownership columns.
--
-- BEFORE RUNNING: check whether `sessions.user_id` has an existing
-- foreign key constraint pointing at the old `users` table. If it
-- does, drop that constraint first (old rows are orphaned by the
-- clean-cutover decision, and new rows will reference auth.users, not
-- the old table) — e.g.:
--   select conname from pg_constraint
--     where conrelid = 'sessions'::regclass and contype = 'f';
--   alter table sessions drop constraint <name_from_above>;
-- ============================================================

-- ------------------------------------------------------------
-- 1. profiles
-- ------------------------------------------------------------
-- Minimal application-side user record. Credentials themselves live
-- entirely in Supabase's own auth.users — this table never stores or
-- duplicates them, only display/profile data keyed 1:1 to it.

create table if not exists profiles (
    id          uuid primary key references auth.users(id) on delete cascade,
    email       text,
    full_name   text,
    avatar_url  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

-- Auto-create a profile row whenever a new Supabase Auth user is
-- created, whether via Google OAuth or email/password signup. Google
-- populates full_name/avatar_url in raw_user_meta_data automatically;
-- email/password signups will have those as null until the user sets
-- them, which is fine (profiles.full_name/avatar_url are optional).
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
    insert into public.profiles (id, email, full_name, avatar_url)
    values (
        new.id,
        new.email,
        new.raw_user_meta_data ->> 'full_name',
        new.raw_user_meta_data ->> 'avatar_url'
    )
    on conflict (id) do nothing;

    return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;

create trigger on_auth_user_created
    after insert on auth.users
    for each row
    execute function public.handle_new_user();

-- ------------------------------------------------------------
-- 2. Row Level Security
-- ------------------------------------------------------------
-- Every comparison against auth.uid() (which returns uuid) is cast to
-- ::text on both sides. This app's tables were created over several
-- iterations (custom-auth era, then Supabase Auth), so id/user_id/
-- session_id columns aren't guaranteed to be uuid vs text consistently
-- across sessions/messages/pdfs/selected_pdfs/document_chunks — casting
-- both sides to text makes every comparison work regardless of which
-- underlying type a given column actually ended up as, instead of
-- guessing and hitting "operator does not exist: text = uuid" again.
--
-- `drop policy if exists` before each `create policy` so this whole
-- file can be safely re-run after a partial failure (unlike `create
-- table`/`create or replace function`, CREATE POLICY has no built-in
-- idempotent form).

alter table profiles enable row level security;

drop policy if exists "select own profile" on profiles;
create policy "select own profile"
    on profiles for select
    using (auth.uid()::text = id::text);

drop policy if exists "update own profile" on profiles;
create policy "update own profile"
    on profiles for update
    using (auth.uid()::text = id::text)
    with check (auth.uid()::text = id::text);

-- No insert/delete policy: rows are created only by the
-- security-definer trigger above and cascade-deleted with auth.users.

alter table sessions enable row level security;

drop policy if exists "crud own sessions" on sessions;
create policy "crud own sessions"
    on sessions for all
    using (auth.uid()::text = user_id::text)
    with check (auth.uid()::text = user_id::text);

alter table messages enable row level security;

drop policy if exists "crud own messages" on messages;
create policy "crud own messages"
    on messages for all
    using (
        session_id::text in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    )
    with check (
        session_id::text in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    );

alter table pdfs enable row level security;

drop policy if exists "crud own pdfs" on pdfs;
create policy "crud own pdfs"
    on pdfs for all
    using (
        session_id::text in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    )
    with check (
        session_id::text in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    );

alter table selected_pdfs enable row level security;

drop policy if exists "crud own selected_pdfs" on selected_pdfs;
create policy "crud own selected_pdfs"
    on selected_pdfs for all
    using (
        session_id::text in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    )
    with check (
        session_id::text in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    );

alter table document_chunks enable row level security;

drop policy if exists "crud own document_chunks" on document_chunks;
create policy "crud own document_chunks"
    on document_chunks for all
    using (
        session_id::text in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    )
    with check (
        session_id::text in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    );

-- Storage bucket "pdfs" — objects are stored at "{session_id}/{pdf_name}"
-- (see storage/storage_manager.py), so ownership is derived from the
-- first path segment the same way the table policies derive it from
-- session_id. The path segment is always plain text (it's a URL path),
-- so this compares it directly against sessions.id cast to text rather
-- than casting the segment to uuid — no need to assume it parses as one.
drop policy if exists "crud own pdf storage objects" on storage.objects;
create policy "crud own pdf storage objects"
    on storage.objects for all
    using (
        bucket_id = 'pdfs'
        and (storage.foldername(name))[1] in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    )
    with check (
        bucket_id = 'pdfs'
        and (storage.foldername(name))[1] in (
            select id::text from sessions where user_id::text = auth.uid()::text
        )
    );
