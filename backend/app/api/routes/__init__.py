from app.api.routes.account import router as account_router
from app.api.routes.admin import router as admin_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.auth import router as auth_router
from app.api.routes.explore import router as explore_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.monitors import router as monitors_router

__all__ = [
    "account_router",
    "admin_router",
    "alerts_router",
    "auth_router",
    "explore_router",
    "jobs_router",
    "monitors_router",
]
