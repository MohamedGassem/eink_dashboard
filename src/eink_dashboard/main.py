from fastapi import FastAPI

from eink_dashboard.api.routes import health
from eink_dashboard.core.logging import configure_logging

configure_logging()

app = FastAPI(title="eink-dashboard")
app.include_router(health.router)
