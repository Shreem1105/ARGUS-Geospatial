from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from app.api.routes.monitors import router as monitors_router
from app.db.session import ReadinessCheckError, check_database_readiness

app = FastAPI(title="ARGUS API")
app.include_router(monitors_router)


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
