from datetime import timedelta

from fastapi import HTTPException
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import NoSuchJobError
from rq.job import Job
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Course, Document, ProcessingTask
from app.models.base import new_id, utcnow
from app.services.account_models import is_configured, resolve_settings

QUEUE_NAME = "documents"


def redis_connection():
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=5)


def submit_extraction(db: Session, document: Document):
    task = db.scalar(
        select(ProcessingTask)
        .where(ProcessingTask.document_id == document.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if task.status in {"queued", "running"}:
        return task
    if task.status == "completed":
        if task.stage == "awaiting_review":
            from app.services.extraction import import_existing_document

            import_existing_document(db, document.id)
            return task
        raise HTTPException(409, "课件已完成提取，结果已存入课程知识库")
    settings = get_settings()
    model_settings = resolve_settings(db, db.get(Course, document.course_id).user_id)
    error = None
    if document.page_count > settings.extraction_max_pages:
        error = f"单次最多处理 {settings.extraction_max_pages} 页，请拆分 PDF 后重新上传。"
    elif not is_configured(model_settings, "llm"):
        error = "尚未配置生成模型，请配置 LLM 后重试。"
    elif not model_settings.llm_vision:
        error = "当前账号的 LLM 未启用图片识别，请在账号设置中选择支持图片的模型。"
    run_id = new_id()
    task.run_id, task.error, task.finished_at = run_id, error, None
    task.started_at, task.progress = utcnow(), 0
    task.status, task.stage = ("failed", "extraction_failed") if error else ("queued", "queued")
    document.status = "uploaded" if error else "processing"
    db.commit()
    if error:
        return task
    try:
        connection = redis_connection()
        connection.ping()
        Queue(QUEUE_NAME, connection=connection).enqueue(
            "app.services.extraction.process_document",
            task.id,
            run_id,
            job_id="extract-" + run_id,
            job_timeout=21600,
            result_ttl=86400,
            failure_ttl=86400,
        )
    except RedisError:
        db.execute(
            update(ProcessingTask)
            .where(
                ProcessingTask.id == task.id,
                ProcessingTask.run_id == run_id,
                ProcessingTask.status == "queued",
            )
            .values(
                status="failed",
                stage="queue_unavailable",
                error="文件已保存，但处理队列暂时无法连接。请启动 Redis 和后台处理服务后重试。",
                finished_at=utcnow(),
            )
        )
        db.commit()
        db.refresh(task)
    return task


def reconcile_task(db: Session, task: ProcessingTask):
    if task.status not in {"queued", "running"} or not task.run_id:
        return
    try:
        job = Job.fetch("extract-" + task.run_id, connection=redis_connection())
        interrupted = job.get_status(refresh=True) in {"failed", "stopped", "canceled"}
        if task.status == "running" and job.last_heartbeat:
            interrupted = interrupted or utcnow() - job.last_heartbeat > timedelta(minutes=3)
    except NoSuchJobError:
        interrupted = bool(
            task.started_at
            and utcnow() - task.started_at.replace(tzinfo=utcnow().tzinfo) > timedelta(minutes=2)
        )
    except RedisError:
        return
    if interrupted:
        db.execute(
            update(ProcessingTask)
            .where(
                ProcessingTask.id == task.id,
                ProcessingTask.run_id == task.run_id,
                ProcessingTask.status.in_(["queued", "running"]),
            )
            .values(
                status="failed",
                stage="extraction_failed",
                error="后台处理已中断，已完成页面保留，可以重试。",
                finished_at=utcnow(),
            )
        )
        db.commit()
        db.refresh(task)
