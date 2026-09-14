from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.http_security import authorize_request
from app.api.routes.account import router as account_router
from app.api.routes.admin import router as admin_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.auth import router as auth_router
from app.api.routes.explore import router as explore_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.monitors import router as monitors_router
from app.core.config import get_settings
from app.db.session import ReadinessCheckError, check_database_readiness

app = FastAPI(title="ARGUS API")
settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.argus_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(monitors_router)
app.include_router(jobs_router)
app.include_router(auth_router)
app.include_router(alerts_router)
app.include_router(account_router)
app.include_router(admin_router)
app.include_router(explore_router)


@app.middleware("http")
async def authz_middleware(request, call_next):
    allowed, rejection, principal = authorize_request(request)
    if not allowed:
        return rejection

    if principal is not None:
        request.state.auth_principal = principal

    return await call_next(request)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"name": "ARGUS API", "status": "running"}


@app.get("/health")
def read_health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/ready")
def read_ready() -> JSONResponse:
    try:
        check_database_readiness()
    except ReadinessCheckError as exc:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "not_ready",
                "database": exc.database_status,
                "postgis": exc.postgis_status,
            },
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "status": "ready",
            "database": "connected",
            "postgis": "available",
        },
    )
