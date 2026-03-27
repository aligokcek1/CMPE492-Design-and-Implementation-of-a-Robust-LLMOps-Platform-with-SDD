from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, upload, models, deployment
from .api.errors import http_exception_handler
from fastapi import HTTPException

app = FastAPI(title="LLMOps Platform API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(HTTPException, http_exception_handler)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(upload.router, prefix="/api/upload", tags=["upload"])
app.include_router(models.router, prefix="/api", tags=["models"])
app.include_router(deployment.router, prefix="/api/deployment", tags=["deployment"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
