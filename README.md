# Job Tracker (Inbox → applications)

Personal **job-application tracker**: connect **Gmail**, run a sync that scans recent mail with job-related wording, extracts **company / role / status** with the **Gemini API**, saves rows per user in **SQLite**, and can **mirror** them into a **Google Sheet** you own.

**Stack:** FastAPI · SQLAlchemy · JWT · React (TypeScript) · Vite · Tailwind CSS

---

## Features

- **Auth** — Register and log in; JWT on protected API routes; data scoped per user.
- **Gmail OAuth** — Connect or disconnect Google in Settings (same OAuth client used for Sheets access).
- **Sync** — On demand, pulls candidate messages from a configurable **lookback window**, skips already-seen IDs, parses with Gemini, and inserts or updates `applications` rows.
- **Applications UI** — Table of synced applications with status badges and dates.
- **Google Sheet** — Optional spreadsheet ID (saved in Settings or via `GOOGLE_SHEET_ID` in `.env`); rebuild writes application rows from the database.

See **Requirements** below for Gemini and Google Cloud setup.

## Tech stack

| Layer | Choice |
|-------|--------|
| API | Python, **FastAPI**, **Uvicorn** |
| Data | **SQLAlchemy**, **Pydantic** / Pydantic Settings |
| Auth | **JWT** (python-jose), **bcrypt** |
| DB (local) | **SQLite** via `DATABASE_URL` |
| Gmail & Sheets | **Google APIs** (`google-api-python-client`, OAuth) |
| Extraction | **Google Generative AI** (`google-generativeai`, Gemini) |
| UI | **React 19**, **TypeScript**, **Vite 8**, **Tailwind CSS v4**, **React Router** |

## Architecture (high level)

```text
Browser ──► Vite dev server ──► FastAPI (/api/*, JWT)
                                    │
                         ┌──────────┼──────────┐
                         ▼          ▼          ▼
                     Auth CRUD    Gmail     Gemini
                         │          oauth    extract
                         ▼                       │
                    SQLite ◄─────────────────────┘
                         │
                         └──► optional Google Sheets API
```

## Local setup

### Prerequisites

- **Python 3.11+**
- **Node.js** (LTS) with `npm`
- Google Cloud **OAuth** client (Web application) with redirect URI matching `GOOGLE_REDIRECT_URI`
- **Gemini API key** for sync extraction

### Backend

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create **`backend/.env`** (exact name). Copy from `backend/.env.example` and set at least:

- `JWT_SECRET_KEY` — long random string (do not commit).
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REDIRECT_URI` (see example).
- `GEMINI_API_KEY` — required for Gmail sync extraction.

Then run:

```bash
uvicorn app.main:app --reload
```

- API: `http://127.0.0.1:8000`
- Docs: `http://127.0.0.1:8000/docs`
- Health: `GET /health`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Start the **backend first** on port **8000**. Default dev setup proxies `/api` to the API via `vite.config.ts`.

Optional: copy `frontend/.env.example` → **`frontend/.env`** and set `VITE_API_URL` if you are not using the default proxy.

### First-time flow

1. Open the app (usually `http://localhost:5173`), **Register**, then **log in**.
2. **Settings** → connect Gmail, set **Google Sheet ID** if you use Sheets.
3. **Applications** → **Sync Gmail** and confirm rows appear.

**“Failed to fetch”** usually means the API is not running or the URL/port does not match; check `/health` in the browser.

## Environment variables

All backend settings are read from **`backend/.env`**. **`backend/.env.example`** is a template only.

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | SQLAlchemy URL (default: SQLite file next to cwd). |
| `JWT_SECRET_KEY` | Signs access tokens. |
| `JWT_ALGORITHM` | Default `HS256`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Token lifetime. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth for Gmail refresh token / Sheets. |
| `GOOGLE_REDIRECT_URI` | Must match Cloud Console redirect (e.g. `http://127.0.0.1:8000/api/gmail/oauth/callback`). |
| `FRONTEND_URL` | Used after OAuth redirect (e.g. `http://localhost:5173`). |
| `GOOGLE_SHEET_ID` | Optional default spreadsheet when user has not saved one in Settings. |
| `GMAIL_SYNC_NEWER_THAN_DAYS` | Gmail “newer than” window for sync (default in code / example). |
| `GEMINI_API_KEY` | Required for extraction during sync. |
| `GEMINI_MODEL` | Optional override (defaults in code, e.g. `gemini-2.5-flash`). |

**Frontend (`frontend/.env`):**

| Variable | Purpose |
|----------|---------|
| `VITE_API_URL` | Backend base URL (no trailing slash) if not using Vite proxy. |

## API summary

| Area | Notes |
|------|------|
| `/api/auth/register`, `/api/auth/login` | JWT + user payload. |
| `/api/auth/me` | Current user (auth required). |
| `GET /api/applications` | List current user’s applications. |
| `POST /api/sync` | Run Gmail sync (requires connected Gmail). |
| `GET /api/settings`, `PUT /api/settings/sheet-id` | Sheet ID and Gmail status hints. |
| `POST /api/settings/rebuild-sheet` | Rewrite Sheet from DB. |
| `POST /api/settings/clear-processed-emails` | Forget processed Gmail message IDs for next sync. |
| `/api/gmail/oauth/start`, `/api/gmail/oauth/callback`, `POST /api/gmail/disconnect` | Gmail OAuth. |
| `/health` | Liveness check. |

## Database (conceptual)

- **`users`** — Credentials, optional Google refresh token, sheet ID, last sync time.
- **`applications`** — One row per user + Gmail thread/message (company, role, status, dates).
- **`seen_message_ids`** (or equivalent) — Tracks processed Gmail IDs per user.

## Deployment (outline)

Production is not scripted in-repo; typical steps:

1. Postgres (or managed DB): set `DATABASE_URL` on the API host.
2. Run FastAPI with Uvicorn, bind `$PORT`; set secrets and Gemini key.
3. **Tighten CORS** in `app/main.py` — replace `allow_origins=["*"]` with your frontend origin(s).
4. Build the frontend (`npm run build`) and serve `dist/` with HTTPS against the API.

## License / contributions

Personal project folder; adjust as you prefer for GitHub visibility.
