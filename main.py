
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.errors import register_error_handlers
from app.routes import (
    admin,
    auth,
    blood_pressure,
    charts,
    chat,
    glucose,
    health,
    reports,
    stats,
)

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
app.include_router(chat.router)
app.include_router(admin.router)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def home_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/admin", include_in_schema=False)
def admin_page() -> FileResponse:
    # Only the empty page shell is served here. It holds no private data, and
    # every /admin/... API behind it is protected by require_admin on the server.
    return FileResponse(STATIC_DIR / "admin.html")


@app.get("/about", include_in_schema=False)
def about_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "about.html")
