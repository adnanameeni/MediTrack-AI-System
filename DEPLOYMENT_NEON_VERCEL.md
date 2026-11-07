# MediTrack AI: PostgreSQL (Neon) and Vercel

This guide moves MediTrack AI to PostgreSQL and fixes the login on Vercel.
Do the steps in order. Never paste a password, a connection string or a key
into a chat, a screenshot or a Git commit.

---

## 1. Why login shows "Something went wrong"

The login page shows that message for any server error. The server error is
that **the database has no tables**:

- Nothing in the deployed app creates the tables. Only
  `python -m scripts.create_tables` does, and it was only ever run on your PC.
- So on Vercel every database query fails (`relation "users" does not exist`,
  or `no such table: users` on SQLite). `/health` still works and the login
  page still loads, because they never touch the database.
- A SQLite file cannot fix this on Vercel. Its disk is temporary and read-only
  for your files, so nothing saved there would survive.

PostgreSQL alone does not fix it either: **a new, empty Neon database has no
tables until you create them (step 4).**

You can confirm this in Vercel: Project, Logs, then open the failed
`POST /auth/login` request. You will see `relation "users" does not exist`.

---

## 2. Create the Neon database

1. In Neon, create a project and a database (the default is fine).
2. Open **Connect** and copy the connection string. Use the one with
   **pooled connection** switched on (the host contains `-pooler`). It looks
   like `postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require`.
3. Keep it private. Put it only in the two places below.

The app accepts `postgresql://...` and `postgres://...` and switches them to
the Psycopg 3 driver by itself. It also removes quotes or spaces that were
pasted by mistake.

If the password contains characters such as `@ / ? #`, Neon already encodes
them in the string it gives you. Copy it exactly as shown.

---

## 3. Vercel environment variables

Project, Settings, Environment Variables. Add for **Production** (and Preview
if you use it):

| Name | Value |
|---|---|
| `DATABASE_URL` | the Neon connection string |
| `SECRET_KEY` | a long random value (32+ characters), the same one you already set |
| `GROQ_API_KEY` | your Groq key (the chatbot needs it) |

Optional: `ACCESS_TOKEN_EXPIRE_MINUTES`, `GROQ_PLANNER_MODEL`,
`GROQ_ANSWER_MODEL`, `GROQ_TIMEOUT_SECONDS`.

**Changing environment variables does nothing until you redeploy**
(Deployments, the three dots, Redeploy).

---

## 4. Create the tables in Neon (this fixes the login)

On your PC, in PowerShell, in the project folder with the virtual
environment active. The `$env:` line applies to this window only and takes
priority over your `.env` file:

```
pip install -r requirements.txt
$env:DATABASE_URL = "PASTE-THE-NEON-STRING-HERE"
python -m scripts.create_tables
Remove-Item Env:DATABASE_URL
```

It prints `Tables are ready.` It is safe to run again; it never deletes
anything. The last line removes the variable from the window.

Now open `https://medi-track-ai-system.vercel.app/health/db`. You should see:

```
{"status":"ready"}
```

`{"status":"database_not_ready"}` with code 503 means the connection string is
wrong or the tables are missing. That page never shows details or secrets.

Then sign up on the site. Login should work.

---

## 5. Make yourself an administrator on Neon

Sign up on the live site first, then:

```
$env:DATABASE_URL = "PASTE-THE-NEON-STRING-HERE"
python -m scripts.make_admin your-email@example.com
Remove-Item Env:DATABASE_URL
```

(Skip this if you migrate your old data in step 6; your admin role is copied.)

---

## 6. Move your existing SQLite data to Neon (optional)

**Decide first.** Your project rules say real health data must not be used
until the security review is done. If `meditrack.db` holds only fake test
data, migrate it freely. If it holds anything real, stop and finish the
security review first.

What the script does and does not do:

- It opens `meditrack.db` **read-only**. The file is never changed, moved or
  deleted.
- It copies users (with their password hashes **exactly as stored**, no
  re-hashing, so everyone keeps the same password), admin roles, glucose and
  blood pressure readings, chat history and the admin audit log. Ids and
  relationships are kept.
- It **never overwrites or merges**. If Neon already has any rows in these
  tables, it stops without changing anything.
- Everything is saved in one transaction and checked row by row. Any problem
  undoes the whole copy.
- With `--execute` it first saves a backup next to your database, named like
  `meditrack-backup-20261107-153108.db`. (`*.db` is ignored by Git. Keep the
  backup somewhere safe, it contains the same data.)

### Steps

Extra safety first: copy `meditrack.db` somewhere else yourself too.

```
$env:TARGET_DATABASE_URL = "PASTE-THE-NEON-STRING-HERE"

# A. Rehearsal. Copies and checks everything, then undoes it. Writes nothing.
python -m scripts.migrate_sqlite_to_postgres --source meditrack.db --create-tables

# B. The real copy. Only if A said "REHEARSAL OK".
python -m scripts.migrate_sqlite_to_postgres --source meditrack.db --create-tables --execute

Remove-Item Env:TARGET_DATABASE_URL
```

You should see a table of row counts that match, then `DONE`.
If it says `STOPPED`, read the reason. Nothing was changed in Neon.

Checks afterwards: open `/health/db`, log in with an old account and old
password, and look at the readings.

### If something is wrong afterwards

Your SQLite file and the backup are untouched, so nothing is lost. To start
over in Neon, delete the database (or restore a branch from before the copy
in the Neon console), run step 4 again and repeat step 6.

---

## 7. Check before you push or deploy

- `.gitignore` must contain `.env` and `*.db`. The project archive you shared
  did not include a `.gitignore`, so check that your repository has one:
  `git ls-files` must not list `.env`, any `.db` file or `venv/`.
- Never commit the Neon string, `SECRET_KEY` or `GROQ_API_KEY`.
  If one was ever committed or pasted somewhere public, rotate it (new
  password in Neon, new key in Groq).

---

## 8. Running the tests

Normal run (SQLite in memory, never touches a real database, even if
`DATABASE_URL` is set in your window):

```
python -m pytest -q
```

Optional: run the whole suite against PostgreSQL. You need a **throw-away**
PostgreSQL database whose name contains `test` (for example a separate Neon
branch or database called `meditrack_test`). Every table in it is dropped and
recreated for each test, so never point this at your real database. The tests
refuse to run unless the name contains `test`.

```
$env:TEST_DATABASE_URL = "postgresql+psycopg://USER:PASSWORD@HOST/meditrack_test?sslmode=require"
python -m pytest -q
Remove-Item Env:TEST_DATABASE_URL
```

---

## 9. What changed in the code

| File | Change |
|---|---|
| `app/database/session.py` | Cleans the database URL, selects Psycopg 3, and sets pool and connection options for PostgreSQL. SQLite settings are exactly as before. |
| `app/routes/health.py` | Adds `GET /health/db` (ready or database_not_ready). `GET /health` is unchanged. |
| `requirements.txt` | `psycopg[binary]` pinned to the tested version 3.3.8 (was a range). |
| `scripts/migrate_sqlite_to_postgres.py` | New. The safe migration described above. |
| `tests/conftest.py` | Tests always use in-memory SQLite and never a real database. Optional `TEST_DATABASE_URL` mode. |
| `tests/test_admin_api.py` | One test fixed: it inserted a reference to a user that never existed, which PostgreSQL correctly refuses. It now deletes a real user. |
| New tests | `test_database_url.py`, `test_health_db.py`, `test_postgres_compat.py`, `test_migrate_sqlite_to_postgres.py` |

Not changed: models, routes, authentication, password hashing, glucose and
blood pressure logic, charts, PDF reports, the chatbot, the admin features,
the frontend and `app/core/config.py`.
