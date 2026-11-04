from fastapi import FastAPI
from app.routes import health

app = FastAPI(title="MediTrack AI")

app.include_router(health.router)
