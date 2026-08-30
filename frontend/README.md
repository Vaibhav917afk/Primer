# Primer — Upload UI

Next.js + TypeScript + Tailwind + shadcn conventions + Framer Motion. Drop a
file, it uploads to Supabase Storage, inserts a `jobs` row, and the backend
picks it up automatically — status updates live on screen via Supabase
Realtime, no refresh needed.

## Before running this — Supabase policies

The browser only ever uses the **anon** key (never `service_role` — that
stays backend-only). By default, an unauthenticated anon key can't write to
your `jobs` table or `raw-uploads` bucket, even though the backend's
service_role key can. Run this once in Supabase's SQL Editor:

```sql
-- Allow the anon key to insert and read job rows
alter table jobs enable row level security;

create policy "anyone can insert a job"
  on jobs for insert
  to anon
  with check (true);

create policy "anyone can read jobs"
  on jobs for select
  to anon
  using (true);

-- Allow the anon key to upload into the raw-uploads bucket
create policy "anyone can upload raw files"
  on storage.objects for insert
  to anon
  with check (bucket_id = 'raw-uploads');
```

**Known limitation, worth knowing:** this makes uploads and job visibility
fully public — anyone with your site's URL can queue a transcription and see
the job list. Fine for a capstone demo; before this is anything more than
that, add real authentication (Supabase Auth) and scope these policies to
`auth.uid()` instead of `anon`/`true`.

## Setup

```bash
npm install
cp .env.local.example .env.local
```

Fill in `.env.local` with your Supabase Project URL and **anon** key
(Project Settings → API — the `anon public` one, not `service_role`).

```bash
npm run dev
```

Open `http://localhost:3000`.

## Deploying (Vercel)

1. Push this to the same `primer` GitHub repo, in a `frontend/` folder
   (same pattern as `backend/`).
2. [vercel.com](https://vercel.com) → New Project → import `primer` →
   **Root Directory: `frontend`**.
3. Add the two environment variables from `.env.local.example` with real
   values.
4. Deploy.

## What's been verified

- Full `npm install` — clean, 0 vulnerabilities (the originally-considered
  Next.js 14.2.15 had a known security advisory; pinned to the current
  patched 16.3.3 instead, with matching `eslint-config-next`).
- `npx tsc --noEmit` — zero type errors across every file.
- Full production build (`next build`) — compiles and generates the static
  page successfully. The only failure in this sandbox was Google Fonts
  being unreachable from this specific offline environment (fonts fetch at
  build time) — confirmed by temporarily swapping to system fonts, seeing
  the build fully succeed, then restoring the real font imports. This will
  fetch normally on your machine or on Vercel, both of which have real
  internet access.

**Not testable here** (no real Supabase project reachable from this
sandbox): an actual file upload, a real Realtime subscription firing, or
confirming the RLS policies above are sufficient — these need a live
Supabase connection to prove end to end.
