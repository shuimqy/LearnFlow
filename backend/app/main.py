import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException

from app.api.router import router
from app.core.config import get_settings
from app.core.database import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("learnflow")
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    yield
    engine.dispose()


app = FastAPI(title="LearnFlow", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = str(uuid4())
    request.state.request_id = request_id
    started = perf_counter()
    origin = request.headers.get("origin")
    if (
        request.method in {"POST", "PATCH", "DELETE", "PUT"}
        and origin
        and origin not in settings.allowed_origins
    ):
        return JSONResponse(
            {"detail": "请求来源不受信任", "request_id": request_id}, status_code=403
        )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    logger.info(
        "%s %s %s %.0fms %s",
        request.method,
        request.url.path,
        response.status_code,
        (perf_counter() - started) * 1000,
        request_id,
    )
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    return JSONResponse(
        {"detail": exc.detail, "request_id": request.state.request_id},
        status_code=exc.status_code,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    fields = [".".join(str(part) for part in error["loc"][1:]) for error in exc.errors()]
    detail = "请检查输入内容的格式和长度"
    if request.url.path.startswith("/api/account/models/"):
        labels = {
            "provider": "接口类型",
            "base_url": "API 地址",
            "model": "模型名称",
            "api_key": "API Key",
            "dimensions": "向量维度",
            "revision": "模型版本",
            "expected_version": "设置版本",
            "structured_output": "结构化输出",
            "vision": "图片识别选项",
            "enable_thinking": "思考模式选项",
            "send_dimensions": "dimensions 参数选项",
        }
        names = list(dict.fromkeys(labels[field] for field in fields if field in labels))
        if names:
            detail = "请检查模型设置：" + "、".join(names) + "。"
    return JSONResponse(
        {
            "detail": detail,
            "fields": fields,
            "request_id": request.state.request_id,
        },
        status_code=422,
    )


@app.exception_handler(IntegrityError)
async def conflict_error(request: Request, exc: IntegrityError):
    return JSONResponse(
        {"detail": "记录已存在，请刷新后重试", "request_id": request.state.request_id},
        status_code=409,
    )


@app.exception_handler(StaleDataError)
async def stale_version(request: Request, exc: StaleDataError):
    return JSONResponse(
        {
            "detail": "知识点已被更新，请刷新后比较最新内容再修改",
            "request_id": request.state.request_id,
        },
        status_code=409,
    )


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.exception("Unhandled error %s", request.state.request_id, exc_info=exc)
    return JSONResponse(
        {"detail": "暂时无法完成操作，请稍后重试", "request_id": request.state.request_id},
        status_code=500,
    )


@app.get("/api/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
        vector_version = None
        if engine.dialect.name == "postgresql":
            vector_version = connection.scalar(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
            if not vector_version:
                raise HTTPException(503, "pgvector 尚未启用，请执行数据库迁移")
    return {"status": "ok", "database": engine.dialect.name, "pgvector": vector_version}


app.include_router(router)
