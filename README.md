# MediTrack AI

A healthcare record management application.

## How to Run (Windows)

1. Activate your virtual environment:
   
   ```
   .\venv\Scripts\activate
   ```
2. Install dependencies:
   
   ```
   pip install -r requirements.txt
   ```
3. Start the FastAPI app:
   
   ```
   uvicorn main:app --reload
   ```
4. Visit [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health) to check the health endpoint.

## Project Structure

- `main.py`: Application entry point
- `app/`: Main backend code
  - `routes/`: API route definitions
  - `database/`: Database setup (empty for now)
  - `models/`: Database models (empty for now)
  - `schemas/`: Pydantic schemas (empty for now)
  - `services/`: Business logic (empty for now)
- `tests/`: Test files (empty for now)
- `requirements.txt`: Python dependencies
- `README.md`: Project instructions

## Notes
- Do not commit secrets or environment files to Git.
- Only FastAPI and Uvicorn are installed at this stage.
