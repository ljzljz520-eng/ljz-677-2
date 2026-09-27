"""社保缴费清单上送台 — 应用入口"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, SessionLocal, engine
from .routers import tasks as tasks_router
from .routers import units as units_router
from .seed import seed_units
from .services.external_client import SimulatedExternalClient
from .services.runner import BackgroundRunner

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_units(db)
    finally:
        db.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="社保缴费清单上送台", version="1.0.0", lifespan=lifespan)

    # 模拟外部平台客户端（生产环境替换为真实 HTTP 客户端）
    app.state.external_client = SimulatedExternalClient(
        latency=float(os.getenv("SIP_EXT_LATENCY", "0.3")),
        fail_rate=float(os.getenv("SIP_EXT_FAIL_RATE", "0.08")),
        timeout_rate=float(os.getenv("SIP_EXT_TIMEOUT_RATE", "0.10")),
    )
    # SIP_SYNC=1 时后台任务同步执行（测试用）
    app.state.runner = BackgroundRunner(sync=os.getenv("SIP_SYNC", "") == "1")

    app.include_router(tasks_router.router, prefix="/api")
    app.include_router(units_router.router, prefix="/api")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    return app


app = create_app()
