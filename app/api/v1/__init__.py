from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.users import router as users_router
from app.api.v1.brokers import router as brokers_router
from app.api.v1.market_data import router as market_data_router
from app.api.v1.news import router as news_router
from app.api.v1.waitlist import router as waitlist_router
from app.api.v1.graph import router as graph_router
from app.api.v1.fno import router as fno_router
from app.api.v1.admin_monitor import router as admin_monitor_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_router.include_router(users_router, prefix="/users", tags=["Users"])
api_router.include_router(brokers_router, prefix="/brokers", tags=["Brokers"])
api_router.include_router(market_data_router, prefix="/market", tags=["Market Data"])
api_router.include_router(news_router, prefix="/news", tags=["News"])
api_router.include_router(waitlist_router, prefix="/waitlist", tags=["Waitlist"])
api_router.include_router(graph_router, prefix="/graph", tags=["Graph Intelligence"])
api_router.include_router(fno_router, prefix="/fno", tags=["F&O"])
api_router.include_router(admin_monitor_router)
