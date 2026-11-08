from fastapi import APIRouter

from app.api import auth, cbam, carbon_market, chat, emission_sources, forecast, news, projects, reports, timeseries

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(emission_sources.router)
api_router.include_router(emission_sources.calc_router)
api_router.include_router(chat.router)
api_router.include_router(reports.router)
api_router.include_router(carbon_market.router)
api_router.include_router(cbam.router)
api_router.include_router(news.router)
api_router.include_router(forecast.router)

api_router.include_router(timeseries.router)

