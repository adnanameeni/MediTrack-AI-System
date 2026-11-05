# MediTrack AI

A healthcare record management application. The backend is a FastAPI app with a health check.

## How to Run (Windows)

From the project root, with the existing virtual environment:

1. Activate the virtual environment:

   ```
   .\venv\Scripts\activate
   ```

2. Install the pinned dependencies if they are not already installed:

   ```
   pip install -r requirements.txt
   ```

3. Start the app:

   ```
   uvicorn main:app --reload
   ```

4. Open these URLs:

   - Health check: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
   - Interactive API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

`GET /health` returns `{"status": "healthy"}`.

## Project Structure

- `main.py`: FastAPI entry point. Creates the app titled "MediTrack AI" and registers the health router.
- `app/__init__.py`: Backend package.
- `app/routes/__init__.py`: Routes package.
- `app/routes/health.py`: `GET /health` route.
- `app/database/base.py`: SQLAlchemy declarative base.
- `app/database/session.py`: Engine, session factory, and `get_db` dependency. Reads `DATABASE_URL` from `.env`.
- `tests/test_database.py`: Database connection tests.
- `requirements.txt`: Pinned Python dependencies. Direct packages are FastAPI, Uvicorn, SQLAlchemy, python-dotenv, and pytest.
- `.env.example`: Placeholder environment variables. Copy it to `.env` locally.
- `.gitignore`: Ignores the virtual environment, environment files, bytecode, pytest cache, and SQLite database files.
- `README.md`: Project instructions.

Local-only items that are not part of the application source:

- `venv/`: Virtual environment (gitignored).
- `.env`: Local environment file (gitignored). The app reads `DATABASE_URL` from it.

## Notes

- Do not commit secrets or environment files to Git.
- Patient models, medical record models, and authentication are not implemented yet.
