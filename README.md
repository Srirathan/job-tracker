# Inbox-to-Application Tracker

A full-stack MVP: **FastAPI backend** plus a **React (TypeScript, Vite) frontend** that talks to it over JWT-protected HTTP. It helps job and internship applicants track applications by **pasting job-related email text**, **classifying** it with deterministic rules, sending low-confidence results to a **review queue**, and persisting **confirmed** rows for analytics and CSV export.

## Why I built it

Spreadsheets and generic trackers rarely capture the real signal source: **email updates**. This app focuses on a clear pipeline: **ingest (manual paste for MVP) → parse → confidence → human review → confirmed records → dashboard → export**, without overbuilding automation or scraping job boards.

## Features (current MVP scope)

- **JWT auth**: register, login, protected routes; data scoped per user.
- **Manual email parse**: paste sender, subject, optional received date, body; get status, confidence, extracted fields, and a short parser reason.
- **Review queue**: list pending parses; edit, ignore, or confirm (confirm creates or updates an application and writes status history).
- **Application tracker**: full CRUD with filters (including date range on `date_applied`) and search.
- **Duplicate hints**: company + role matching suggests an existing application before confirm.
- **Dashboard**: summary metrics and chart-oriented payloads (applications by week, status breakdown, response rate by resume version when enough data).
- **CSV export**: filtered download of applications with current status and main fields.

**Not in MVP (honest scope):** Gmail OAuth, Google Sheets sync, LLM parsing, hosted deployment wiring in-repo (documented as next steps only).

## Tech stack

| Layer | Choice |
|--------|--------|
| API | Python 3, **FastAPI** |
| Data | **SQLAlchemy**, **Pydantic** / Pydantic Settings |
| Auth | **JWT** (python-jose), **bcrypt** (direct library) |
| DB (local) | **SQLite** via `DATABASE_URL` |
| DB (production) | **PostgreSQL** (same URL pattern; e.g. Neon, Supabase, RDS) |
| UI | **React 19**, **TypeScript**, **Vite 8**, **Tailwind CSS v4**, **React Router**, **Recharts** |

## Architecture (high level)

```text
Browser / API client
        |
        v
   FastAPI (JWT)
        |
   +----+----+
   |    |    |
   v    v    v
 Auth  CRUD  Parse --> Review --> Applications
   |              \___________/
   v                    v
 SQLite / Postgres   StatusHistory
```

1. **Auth** issues JWTs; every business route uses the current user id.
2. **Parse** stores an `EmailParse` row (`review_status = pending`).
3. **Confirm** upserts an `Application` and appends `StatusHistory` when status changes.
4. **Dashboard** and **export** read only that user’s `Application` rows.

## Screenshots

Add your own after the UI exists, for example:

- `docs/screenshots/login.png`
- `docs/screenshots/dashboard.png`
- `docs/screenshots/review-queue.png`

## Local setup

### Prerequisites

- Python 3.11+ recommended
- `pip` and a virtual environment tool

### Backend

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
```

Create **`backend/.env`** with that exact name. Copy from `backend/.env.example`: `Copy-Item backend\.env.example backend\.env` (PowerShell) or your editor’s “Save as”. The API **only reads `backend/.env`**; `.env.example` is a template and is never loaded. Set at least `JWT_SECRET_KEY` (long random string). For Gmail, add `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` there too. Do not commit `.env`.

```bash
uvicorn app.main:app --reload
```

- API root: `http://127.0.0.1:8000`
- OpenAPI docs: `http://127.0.0.1:8000/docs`
- Health: `GET /health`

On first run, SQLAlchemy creates tables from models (`create_all`). For production, prefer a migration tool (e.g. Alembic) once the schema stabilizes.

### Frontend

```bash
cd frontend
npm install
```

For **local development**, you can skip `frontend/.env`: the app calls `/api/...` on the same host as Vite, and **`vite.config.ts` proxies** those requests to `http://127.0.0.1:8000`. Start the backend on port **8000** first.

If you prefer a full URL instead, copy `frontend/.env.example` to **`frontend/.env`** (exact name; Vite does not load `.env.example`), set `VITE_API_URL`, and restart `npm run dev`.

Start the backend first, then:

```bash
npm run dev
```

Open the printed local URL (usually `http://localhost:5173`). Register or log in, then use Dashboard, Applications, Parse email, Review queue, and CSV export.

**Accounts:** You create your own user on **Register** (email + password). Nothing is pre-seeded; the backend stores users in SQLite/Postgres.

**If login/register shows “Failed to fetch”:**

1. **Start the API first** — In `backend/`, run `uvicorn app.main:app --reload` and confirm `http://127.0.0.1:8000/health` returns `{"status":"ok"}` in the browser.
2. **Match the API URL** — In `frontend/.env`, set `VITE_API_URL` to the same host the server uses (e.g. `http://127.0.0.1:8000` or `http://localhost:8000`). Restart `npm run dev` after changing `.env`.
3. **CORS** — The backend allows all origins with JWT in the `Authorization` header (no cookie credentials). If you still see errors, check the browser **Network** tab for the failed request URL and status.

## Environment variables

**Backend:** variables must live in **`backend/.env`** (filename exactly `.env`). **`backend/.env.example`** is documentation only.

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLAlchemy URL. Default in code: `sqlite:///./app.db` (relative to cwd when running uvicorn). For Postgres: `postgresql+psycopg2://user:pass@host:5432/dbname` (driver package not listed until you add Postgres client). |
| `JWT_SECRET_KEY` | Signing secret for access tokens. |
| `JWT_ALGORITHM` | Default `HS256`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Access token lifetime. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Gmail OAuth (optional). |
| `GOOGLE_REDIRECT_URI` / `FRONTEND_URL` | Gmail OAuth callback and post-login redirect (defaults in code). |

See `backend/.env.example` for a full template.

**Frontend (`frontend/.env`):**

| Variable | Purpose |
|----------|---------|
| `VITE_API_URL` | FastAPI base URL (no trailing slash), e.g. `http://127.0.0.1:8000`. |

See `frontend/.env.example`.

## API route summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/auth/register` | No | Create user; returns JWT + user. |
| `POST` | `/api/auth/login` | No | Login; returns JWT + user. |
| `GET` | `/api/auth/me` | Yes | Current user profile. |
| `GET` | `/api/applications` | Yes | List applications (filters: `status`, `company`, `role_type`, `resume_version`, `search`, `date_applied_from`, `date_applied_to`). |
| `POST` | `/api/applications` | Yes | Create application. |
| `GET` | `/api/applications/{id}` | Yes | Get one application. |
| `PUT` | `/api/applications/{id}` | Yes | Update application. |
| `DELETE` | `/api/applications/{id}` | Yes | Delete application. |
| `POST` | `/api/email/parse` | Yes | Parse pasted email; create pending `EmailParse`. |
| `GET` | `/api/email/review-queue` | Yes | List review items (`review_status` query, default `pending`). |
| `PUT` | `/api/email/review/{id}` | Yes | Edit extracted fields on a pending item. |
| `POST` | `/api/email/review/{id}/ignore` | Yes | Mark ignored. |
| `POST` | `/api/email/review/{id}/confirm` | Yes | Confirm into tracker; may update duplicate application. |
| `GET` | `/api/dashboard/summary` | Yes | Aggregate dashboard numbers. |
| `GET` | `/api/dashboard/charts` | Yes | Chart-friendly series. |
| `GET` | `/api/export/applications.csv` | Yes | CSV download (same-style filters as list). |
| `GET` | `/health` | No | Liveness check. |

## Database schema summary

| Table | Purpose |
|-------|---------|
| `users` | `id`, `email`, `hashed_password`, `created_at`. |
| `applications` | One row per tracked role at a company per user: company, role, links, location, role type, source, **status**, dates, resume version, notes, timestamps. |
| `email_parses` | Parsed paste: sender, subject, received date, body preview, extracted fields, confidence, parser reason, **review_status**, optional link to duplicate application id. |
| `status_history` | Optional audit trail when an application’s status changes (e.g. after email confirm). |

Statuses for applications and extracted email status align: Applied, Rejected, Interview, Online Assessment, Offer, Follow-up, Unknown.

## Deployment notes (later)

Typical split (not automated in this repo):

1. **Database**: Create a Postgres instance (Neon, Supabase, etc.); set `DATABASE_URL` on the API host.
2. **API**: Deploy FastAPI with Uvicorn (e.g. Render Web Service). Set env vars; bind `0.0.0.0:$PORT`.
3. **CORS**: Replace wide open `allow_origins=["*"]` in `app/main.py` with your real frontend origin(s).
4. **Frontend**: Static or SSR host (e.g. Vercel) calling the API with `Authorization: Bearer …`.

Use HTTPS everywhere in production and rotate `JWT_SECRET_KEY` if it is ever exposed.

## Future improvements

- **Gmail API** (read-only): pull candidate messages into the same review queue; minimal body storage and user deletion controls.
- **Google Sheets**: one-way export for reporting, not the source of truth.
- **Optional LLM**: only when rules are uncertain; output still goes through review.

## Resume bullet examples (truthful; adjust to what you ship)

- Built an **Inbox-to-Application Tracker** API with **FastAPI**, **JWT auth**, and **SQLAlchemy** models for users, applications, parsed emails, and status history.
- Implemented **deterministic email parsing** (keywords and patterns), **confidence scoring**, a **review queue** with confirm or ignore flows, and **duplicate-aware** application upserts.
- Exposed **dashboard analytics** and **filtered CSV export** endpoints scoped per user for internship application tracking.

After Gmail integration (only if you actually build it):

- Integrated **Gmail read-only** access to enqueue parsed job emails for user review without auto-saving final tracker rows.
#   j o b - t r a c k e r  
 