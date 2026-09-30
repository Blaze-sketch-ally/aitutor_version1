import os

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.chat import router as chat_router
from api.session import router as session_router
from api.pdf import router as pdf_router
from memory.session_manager import SessionOwnershipError
from models.errors import ServiceUnavailableError


app = FastAPI(
    title="AI Tutor API",
    version="1.0"
)

# ==========================================
# CORS
# ==========================================
# Origins come from CORS_ALLOWED_ORIGINS (comma-separated) so the
# deployed frontend's real URL never has to be hardcoded here — set it
# in the backend's production environment. Falls back to the local dev
# origins so `uvicorn main:app --reload` keeps working out of the box
# with no env var required.

_default_origins = "http://localhost:3000,http://127.0.0.1:3000"

allowed_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOWED_ORIGINS", _default_origins).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# EXCEPTION HANDLERS
# ==========================================
# Single place SessionOwnershipError (memory/session_manager.py) is
# translated to HTTP — 404, not 403, so a session_id that exists but
# belongs to someone else and one that doesn't exist at all are
# indistinguishable to the caller.

@app.exception_handler(SessionOwnershipError)
def handle_session_ownership_error(request: Request, exc: SessionOwnershipError):
    return JSONResponse(
        status_code=404,
        content={"detail": "Session not found"}
    )

# Backing-service failures: model provider (LLMServiceError: retired
# model, auth, rate limit, outage) and vector search (RetrievalError).
# The detailed cause was already logged server-side where it was
# raised; the client only gets the secret-free user_message. 503 so
# the frontend (and anyone reading logs) can tell "a service failed"
# apart from a bug in this API (500).

# Database/storage connection failures that survived the one automatic
# retry (database/retry_transport.py). Safe, generic, retryable — never
# the raw httpx/h2 error text.

@app.exception_handler(httpx.TransportError)
def handle_transport_error(request: Request, exc: httpx.TransportError):
    print(f"Database connection error on {request.url.path}: {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=503,
        content={"detail": "Temporary connection problem. Please try again."}
    )


@app.exception_handler(ServiceUnavailableError)
def handle_service_unavailable(request: Request, exc: ServiceUnavailableError):
    return JSONResponse(
        status_code=503,
        content={"detail": exc.user_message}
    )

# ==========================================
# ROUTERS
# ==========================================
# Registration/login/logout/password-reset are handled entirely by
# Supabase Auth from the frontend now — there is no local auth router.
# Every route below authenticates via auth/jwt_bearer.py's
# get_current_user() dependency instead of a client-supplied identity.

app.include_router(session_router)
app.include_router(chat_router)
app.include_router(pdf_router)

# ==========================================
# ROOT
# ==========================================

@app.get("/")
def home():
    return {
        "message": "AI Tutor Backend Running 🚀"
    }

# ==========================================
# HEALTH CHECK
# ==========================================
# Render's health check target. Deliberately checks only that the FastAPI
# process itself is up -- no Supabase/Groq/etc calls -- so it can't fail
# (and take the service down) due to a slow or degraded third-party
# dependency. Returns no version/environment/config details.

@app.get("/health")
def health():
    return {
        "status": "ok"
    }
