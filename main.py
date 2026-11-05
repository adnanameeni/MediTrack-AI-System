from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.errors import register_error_handlers
from app.routes import auth, blood_pressure, charts, glucose, health, reports, stats

STATIC_DIR = Path(__file__).resolve().parent / "app" / "static"

app = FastAPI(title="MediTrack AI")

register_error_handlers(app)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(glucose.router)
app.include_router(blood_pressure.router)
app.include_router(stats.router)
app.include_router(charts.router)
app.include_router(reports.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def home_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")