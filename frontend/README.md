# Primer — Web App

Next.js 16 + TypeScript + Tailwind + Supabase Auth (SSR) + Framer Motion.
This is the foundation: auth, onboarding, session handling. The real
dashboard/prospects/upload pages are the next build, one tested page at
a time — same discipline as the backend.

## Required — run this before onboarding will work at all

`organizations` and `org_members` currently only have SELECT policies.
A brand-new user can't create their first org without this:

```sql
create policy "authenticated users can create an org"
  on organizations for insert
  to authenticated
  with check (true);

create policy "users can add themselves to an org"
  on org_members for insert
  to authenticated
  with check (user_id = auth.uid());
```

Note on the second policy: it only lets someone add *themselves* — not
add an arbitrary other user. That's deliberate for now. The `/team`
page's "add a rep" flow will need a small, separate mechanism (an admin
adding someone else's `user_id` isn't something RLS should allow blindly)
— to be decided when that page gets built, not before.

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

Open `http://localhost:3000` — should redirect to `/login`.

## Deploying (Vercel)

1. Push this to the `primer` repo, in a `frontend/` folder (same pattern
   as `backend/`).
2. [vercel.com](https://vercel.com) → New Project → import `primer` →
   **Root Directory: `frontend`**.
3. Add the two environment variables from `.env.local.example`.
4. Deploy.

## What's actually been verified

- Clean install, 0 vulnerabilities (caught `recharts` v2 flagged
  deprecated on install, switched to v3, confirmed React 18 compatible).
- `npx tsc --noEmit` — zero type errors. Caught and fixed two real
  implicit-`any` errors in the Supabase SSR cookie handlers before they
  shipped.
- Full production build (`next build`) — compiles clean, all 5 routes +
  middleware generated correctly. Verified by temporarily swapping out
  the Google Fonts import (unreachable from this sandbox specifically),
  confirming the build succeeds, then restoring the real fonts.
- One known, non-blocking deprecation warning: Next.js 16 wants the
  "middleware" file renamed to "proxy" eventually — functional today,
  just old naming. Not fixed yet, deliberately — noted as known debt
  rather than chasing every warning mid-build.

**Not testable here** (no live Supabase reachable from this sandbox): an
actual sign-up, the RLS policies above under real conditions, or a real
session round-trip through the middleware.
