from typing import Literal

import pymupdf
from fastapi import APIRouter, HTTPException, Query
from pydantic import SecretStr
from sqlalchemy import select

from app.core.auth import DB, CurrentUser
from app.core.config import get_settings
from app.core.model_runtime import use_model_settings
from app.models import AccountModels, Course
from app.schemas.account import AccountUpdate, ModelInput, ProbeResult
from app.schemas.auth import UserOut
from app.services import account_index
from app.services.account_models import (
    account_lock,
    input_config,
    input_key,
    profile_for,
    public_profile,
    resolve_settings,
    save_model,
)
from app.services.embeddings import EmbeddingClient
from app.services.llm import LLMClient
from app.services.model_api import ModelAPIError
from app.services.vector_index import enqueue_course_index, index_status

router = APIRouter(prefix="/account", tags=["account"])
Kind = Literal["llm", "embedding"]


def models_out(db, user_id):
    account = db.get(AccountModels, user_id)
    active = profile_for(db, user_id, "embedding")
    pending = profile_for(db, user_id, "embedding", pending=True)
    if active:
        progress = account_index.status(db, active)
    else:
        states = [
            index_status(db, course_id)
            for course_id in db.scalars(select(Course.id).where(Course.user_id == user_id))
        ]
        progress = {
            key: sum(state[key] for state in states)
            for key in ("total", "ready", "failed", "pending")
        }
    return {
        "version": account.version if account else 0,
        "llm": public_profile(profile_for(db, user_id, "llm"), "llm"),
        "embedding": public_profile(active, "embedding"),
        "pending_embedding": public_profile(pending, "embedding") if pending else None,
        "index": progress,
        "rebuild": account_index.status(db, pending) if pending else None,
    }


@router.patch("/profile", response_model=UserOut)
def update_profile(payload: AccountUpdate, user: CurrentUser, db: DB):
    user.name = payload.name
    db.commit()
    return user


@router.get("/models")
def model_settings(user: CurrentUser, db: DB):
    return models_out(db, user.id)


@router.put("/models/{kind}")
def update_model(kind: Kind, payload: ModelInput, user: CurrentUser, db: DB):
    try:
        save_model(db, user.id, kind, payload)
        queued = None
        if kind == "embedding":
            account_index.try_activate(db, user.id)
            if get_settings().embedding_auto_index:
                queued = account_index.enqueue_account(db, user.id, force=True)
        return {**models_out(db, user.id), "queued": queued}
    except ModelAPIError:
        db.rollback()
        raise HTTPException(503, "模型密钥暂时无法保存，请检查服务端加密配置。") from None


@router.delete("/models/embedding/pending")
def cancel_rebuild(user: CurrentUser, db: DB, expected_version: int = Query(ge=0)):
    account = account_lock(db, user.id, expected_version)
    pending = profile_for(db, user.id, "embedding", pending=True)
    if pending:
        account.pending_embedding_id = None
        account.version += 1
        db.flush()
        db.delete(pending)
    db.commit()
    return models_out(db, user.id)


@router.post("/models/embedding/rebuild", status_code=202)
def rebuild_index(user: CurrentUser, db: DB):
    account_index.try_activate(db, user.id)
    result = account_index.enqueue_account(db, user.id, force=True)
    if result is None:
        result = True
        for course_id in db.scalars(select(Course.id).where(Course.user_id == user.id)):
            result = enqueue_course_index(db, course_id, force=True) and result
    if not result:
        raise HTTPException(
            503, "模型设置已保存，但索引队列暂时不可用，请检查 Redis 和 Worker 后重试。"
        )
    return {"queued": True}


@router.post("/models/{kind}/test")
def test_model(kind: Kind, payload: ModelInput, user: CurrentUser, db: DB):
    config, key = input_config(payload, kind), input_key(db, user.id, kind, payload)
    settings = resolve_settings(db, user.id)
    updates = {f"{kind}_{field}": config[field] for field in ("provider", "base_url", "model")}
    updates[f"{kind}_api_key"] = SecretStr(key)
    if kind == "embedding":
        updates.update(
            embedding_dimensions=config["dimensions"],
            embedding_revision=config["revision"],
            embedding_send_dimensions=config["send_dimensions"],
        )
    else:
        updates.update(
            llm_vision=config["vision"],
            llm_structured_output=config["structured_output"],
            llm_enable_thinking=config["enable_thinking"],
        )
    settings = settings.model_copy(update=updates)
    db.commit()
    try:
        with use_model_settings(settings):
            if kind == "embedding":
                result = EmbeddingClient().embed(
                    ["线性无关的向量组，其零线性组合只有全零系数。", "怎样判断向量组是否线性独立？"]
                )
                return {
                    "available": True,
                    "model": result.model,
                    "dimensions": result.dimensions,
                    "tokens": result.total_tokens,
                    "message": "向量接口可用，返回维度符合设置。",
                }
            images = None
            prompt = (
                '请只返回数据对象 {"status":"ok","answer":"LearnFlow OK"}，不要返回 JSON Schema。'
            )
            if config["vision"]:
                with pymupdf.open() as sample:
                    page = sample.new_page(width=240, height=80)
                    page.insert_text((20, 45), "LearnFlow OK", fontsize=20)
                    images = [page.get_pixmap().tobytes("png")]
                prompt = "请识别图片中的英文文字，原样写入 answer，status 设为 ok。"
            result = LLMClient().complete(
                [
                    {
                        "role": "system",
                        "content": "这是固定连通性测试，返回符合 JSON Schema 的对象，status 为 ok。",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_model=ProbeResult,
                max_tokens=4096 if settings.llm_enable_thinking else 256,
                images=images,
            )
            if (
                not isinstance(result.parsed, ProbeResult)
                or result.parsed.answer.strip() != "LearnFlow OK"
            ):
                raise ModelAPIError("The fixed model probe did not follow the instruction.")
            return {
                "available": True,
                "model": result.model,
                "vision_checked": bool(images),
                "message": "模型回复与结构化输出校验通过。",
            }
    except ModelAPIError:
        raise HTTPException(
            502, "测试未通过，请检查地址、API Key、模型名称及能力设置；向量维度需与模型输出一致。"
        ) from None
