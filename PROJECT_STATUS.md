# MediTrack AI: Project Status and Handover

**Document date:** 2026-11-07
**Owner:** Adnan (beginner developer; Windows 11, Cursor IDE, PowerShell, Python 3.14.5 virtual environment)
**Project folder:** `D:\Different Data\Generative_AI\MediTrack-AI`
**GitHub:** https://github.com/adnanameeni/MediTrack-AI-System
**Live site (Vercel):** https://medi-track-ai-system.vercel.app/

> **Status words**
> - **Verified (user):** the owner ran it and pasted the output.
> - **Verified (sandbox):** the assistant ran it in its own environment (Python 3.12, throwaway keys, files extracted from the owner's archives, a real PostgreSQL 16 server). Useful evidence, not proof it works on the owner's machine or on Vercel.
> - **Reported / Not verified:** said done without output / nobody confirmed.

---

## 1. Project overview

Healthcare record app: users sign up and log in, record blood glucose and blood pressure, see statistics and charts, download PDF reports and chat with a Groq-powered assistant that gives factual summaries only. Administrators manage users through a protected admin API and page.

**Hard product rules:** no diagnosis, medicine or treatment advice anywhere. Statistics are plain numbers. Administrators see counts only, never other users' readings or conversation text. Real patient data must not be used until the security review is finished.

**Stack:** FastAPI, SQLAlchemy 2.x, SQLite (local) and PostgreSQL via Psycopg 3 (Neon, planned for Vercel), Pydantic, PyJWT, Argon2 | HTML, CSS, Bootstrap 5, JavaScript, Chart.js | LangGraph, langchain-groq | ReportLab, Pillow | Pytest.

**Architecture:** `routes/` (thin HTTP) -> `schemas/` -> `services/` -> `models/` -> `database/`. `core/` has config, security and the safe validation-error handler. `assistant/` is the LangGraph chatbot. `reporting/` builds PDFs. `static/` has the pages (login, dashboard, chat, admin, about).

---

## 2. What exists (from the owner's archive of 2026-11-07)

All of these are present in the code (Verified (sandbox): 370 tests passed on the unmodified archive):

- Authentication (signup, login, JWT, Argon2), safe validation errors.
- Glucose and blood pressure CRUD, statistics, charts, PDF reports.
- AI assistant and stored chat conversations (Groq, LangGraph, safety checks).
- Roles: `users.role` (`user` or `admin`), `AdminAuditLog` table, `require_admin`, `scripts/make_admin.py`, `scripts/add_role_column.py`.
- **Admin backend (Batch 2), complete in the archive:** `/admin/me`, `/admin/overview`, `/admin/users` (search, role filter, pagination), `/admin/users/{id}`, `PATCH /admin/users/{id}/role`, `PATCH /admin/users/{id}/status`, `/admin/activity`. Router-level admin check (401 not logged in, 403 not admin), self-demotion and last-admin protection, audit entries, counts-only privacy. Files: `app/routes/admin.py`, `app/schemas/admin.py`, `app/services/admin_service.py`, `tests/test_admin_api.py` (104 tests).
- Admin page `app/static/admin.html` with `js/admin.js` and `css/admin.css`, and an About page.

---

## 3. Current task: PostgreSQL and Vercel (work done this session)

### Diagnosis of the Vercel login failure (Verified (sandbox), reproduced)
The login page shows "Something went wrong" for any server error. The error is `no such table: users` (PostgreSQL: `relation "users" does not exist`): **nothing in the deployed app creates the database tables.** Only `python -m scripts.create_tables` does, and it only ran on the owner's PC. `/health` and the login page still work because they do not touch the database. A new empty Neon database has the same problem, so PostgreSQL alone does not fix login: the tables must be created in Neon (guide step 4). Not confirmed against the real Vercel logs (the assistant cannot see them); the owner can confirm by opening the failed `POST /auth/login` in Vercel Logs.

### Code changes (11 files; everything else untouched)
| File | Change |
|---|---|
| `app/database/session.py` | `normalize_database_url` (postgres:// and postgresql:// become `postgresql+psycopg://`, stray quotes and spaces removed), serverless-friendly pool and connect options for PostgreSQL (`pool_pre_ping`, `pool_recycle=300`, small pool, `connect_timeout`, `prepare_threshold=None` for Neon's pooler). SQLite behaviour identical to before. |
| `app/routes/health.py` | New `GET /health/db` returns `{"status":"ready"}` or 503 `{"status":"database_not_ready"}`; no details or secrets. `GET /health` unchanged. |
| `requirements.txt` | `psycopg[binary]` pinned to `3.3.8` (was `>=3.2,<4`). Wheels checked to exist for Windows Python 3.14 and Linux Python 3.12 and 3.13. |
| `scripts/migrate_sqlite_to_postgres.py` | New. Read-only source, rehearsal by default (`--execute` to save), refuses a non-empty target, one transaction with row-by-row verification, copies password hashes exactly, keeps ids and relationships, resets PostgreSQL id counters, backup made only right before a real write, never prints passwords. Target is read from `TARGET_DATABASE_URL`. |
| `tests/conftest.py` | Tests always use in-memory SQLite even if `DATABASE_URL` is set in the shell. Optional `TEST_DATABASE_URL` runs the whole suite on PostgreSQL (database name must contain "test"; tables are dropped per test). |
| `tests/test_admin_api.py` | One test fixed (`test_activity_copes_with_a_deleted_target`): it inserted an audit row for a user id that never existed, which PostgreSQL correctly rejects. |
| New tests | `test_database_url.py`, `test_health_db.py`, `test_postgres_compat.py` (PostgreSQL only), `test_migrate_sqlite_to_postgres.py` |
| `DEPLOYMENT_NEON_VERCEL.md` | New step-by-step guide. |

Not changed: models, routes, authentication, password hashing, glucose and blood pressure logic, charts, PDFs, chatbot, admin features, frontend, `app/core/config.py`, `main.py`, `scripts/create_tables.py`. No models needed changes: the code had no SQLite-only logic apart from `session.py` (already guarded by a dialect check).

### Test results (Verified (sandbox))
- Unmodified archive on SQLite: 370 passed.
- After changes, SQLite (default): **413 passed, 33 skipped** (skips are the PostgreSQL-only tests).
- After changes, **entire suite on real PostgreSQL 16: 443 passed, 3 skipped** (skips only apply to a SQLite target).
- End-to-end on PostgreSQL: empty database reproduces login 500 and `/health/db` 503; creating tables fixes it; migrating an old SQLite file keeps accounts, hashes, admin role, readings; login works with the original passwords; new ids continue after the copied ones (no duplicate-key errors); the SQLite file is byte-for-byte unchanged.
- Deliberately breaking the migration script (7 bugs) is caught by the tests.
- **Not tested:** a real Neon connection, a real Vercel deployment, Python 3.14 on the owner's machine.

---

## 4. What remains (owner actions first)

1. Copy the 11 files into the project (the update ZIP), run `python -m pytest -q` on the owner's PC, send the last line. Expect about 413 passed, 33 skipped.
2. Follow `DEPLOYMENT_NEON_VERCEL.md`: create the Neon database, set `DATABASE_URL`, `SECRET_KEY`, `GROQ_API_KEY` in Vercel and **redeploy**, run `python -m scripts.create_tables` against Neon, open `/health/db` on the live site, sign up, make an admin.
3. **Decision for the owner:** migrate `meditrack.db` to Neon only if it holds fake test data. Real health data must wait for the security review.
4. Push to GitHub when the owner asks (the assistant never pushes). Before that confirm `.gitignore` lists `.env` and `*.db` (the latest archive had no `.gitignore` file; verify in the real repository) and that `git ls-files` shows no `.env`, `.db` or `venv/`.
5. If any key or connection string was ever committed or shared (the archives contained `.env`, which the assistant did not open or extract), rotate it (Neon password, Groq key, SECRET_KEY).

### Later
- Update `README.md` (out of date). Remove the stray `app/assistant/Untitled` file (looks like a copy of `llm.py`).
- Security hardening before real data: login rate limiting, token storage review, CORS and security headers, HTTPS, Alembic migrations (the add-column script is a stop-gap), logging review, dependency audit, `pip freeze`.
- Consider moving `pytest` out of production requirements, and putting the Neon database in the same region as the Vercel functions.
- Optional: automatic table creation or Alembic migrations in the deployment pipeline.

---

## 5. Known issues and notes

- FastAPI 0.162 nests included routers: use `app.openapi()["paths"]` to list routes in tests.
- Signup returns 409 for an existing email (reveals registration). Accepted for now.
- Admin overview loads all registration dates into memory (fine at this scale).
- `tests/test_database.py` expects the app engine to be SQLite: that is why conftest forces `DATABASE_URL=sqlite://`.
- Use `python -m pytest`, not plain `pytest`. Pasted commands sometimes lose their first letter (`it status` instead of `git status`).

---

## 6. How to run

```
python -m scripts.create_tables
python -m uvicorn main:app --host 127.0.0.1 --port 8000
python -m pytest -q
```

Local server on `127.0.0.1` only. Fake `example.com` data only.

---

## 7. Instructions for the next AI assistant

**Owner preferences:** beginner; wants complete files, never fragments; for the PostgreSQL task the owner explicitly asked for everything together and allowed a ZIP (in the earlier admin batch the owner did not want ZIPs: follow the latest instruction). Do not rewrite the project, do not change unrelated files or existing package versions, do not invent files or fields.

**Rules:** never ask for or open `.env`, keys, passwords, connection strings, database files, `venv/` or `.git/`. Never push or commit unless asked. Every health-record query filters by the logged-in user's id; admins see counts only. No diagnosis or treatment advice. Never claim a test passed without running it.

**Where to start:** ask for the owner's `python -m pytest -q` last line and for the result of `/health/db` on the live site. If login still fails on Vercel, ask the owner to open the failed request in Vercel Logs and paste only the final error line (no connection strings).

---

## 8. Security and privacy

- This document contains no secrets, connection strings or health records. Keep it that way.
- Complete the hardening phase before any real patient information is used.
