import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import get_settings
from app.core.model_secrets import decrypt_key, encrypt_key
from app.models import AccountModels, Course, KnowledgeChunk, KnowledgeEmbedding, ModelProfile, User
from app.services.model_api import local_endpoint


def default_config(kind, settings=None):
    settings = settings or get_settings()
    result = {
        "provider": getattr(settings, f"{kind}_provider"),
        "base_url": getattr(settings, f"{kind}_base_url"),
        "model": getattr(settings, f"{kind}_model"),
    }
    if kind == "embedding":
        result.update(
            dimensions=settings.embedding_dimensions,
            revision=settings.embedding_revision,
            send_dimensions=settings.embedding_send_dimensions,
        )
    else:
        result.update(
            vision=settings.llm_vision,
            structured_output=settings.llm_structured_output,
            enable_thinking=settings.llm_enable_thinking,
        )
    return result


def fingerprint(config):
    value = {**config, "text_format": "knowledge-title-summary-body-v1"}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def profile_for(db, user_id, kind, *, pending=False):
    account = db.get(AccountModels, user_id)
    key = None
    if account:
        key = (
            account.llm_id
            if kind == "llm"
            else (account.pending_embedding_id if pending else account.embedding_id)
        )
    profile = db.get(ModelProfile, key) if key else None
    if profile and profile.user_id == user_id and profile.kind == kind:
        return profile
    return None


def settings_for_profile(profile, base=None):
    settings = base or get_settings()
    config = profile.config
    updates = {
        f"{profile.kind}_provider": config["provider"],
        f"{profile.kind}_base_url": config["base_url"],
        f"{profile.kind}_model": config["model"],
        f"{profile.kind}_api_key": decrypt_key(profile.user_id, profile.encrypted_key),
    }
    if profile.kind == "embedding":
        updates.update(
            embedding_dimensions=config["dimensions"],
            embedding_revision=config["revision"],
            embedding_send_dimensions=config["send_dimensions"],
        )
    else:
        updates.update(
            llm_vision=config["vision"],
            llm_structured_output=config["structured_output"],
            llm_enable_thinking=config.get("enable_thinking", settings.llm_enable_thinking),
        )
    return settings.model_copy(update=updates)


def resolve_settings(db, user_id):
    settings = get_settings()
    for kind in ("llm", "embedding"):
        if profile := profile_for(db, user_id, kind):
            settings = settings_for_profile(profile, settings)
    return settings


def is_configured(settings, kind):
    endpoint = getattr(settings, f"{kind}_base_url")
    return bool(
        endpoint
        and getattr(settings, f"{kind}_model")
        and (getattr(settings, f"{kind}_api_key").get_secret_value() or local_endpoint(endpoint))
    )


def public_profile(profile, kind):
    if profile:
        config = dict(profile.config)
        if kind == "llm":
            config.setdefault("enable_thinking", get_settings().llm_enable_thinking)
        has_key = bool(decrypt_key(profile.user_id, profile.encrypted_key).get_secret_value())
    else:
        config = default_config(kind)
        has_key = bool(getattr(get_settings(), f"{kind}_api_key").get_secret_value())
    return {**config, "has_api_key": has_key, "source": "account" if profile else "system"}


def input_config(payload, kind):
    keys = (
        ("provider", "base_url", "model", "revision", "dimensions", "send_dimensions")
        if kind == "embedding"
        else ("provider", "base_url", "model", "vision", "structured_output", "enable_thinking")
    )
    if kind == "embedding" and payload.provider == "deepseek":
        raise HTTPException(422, "DeepSeek 接口仅用于 LLM，请为 Embedding 选择向量模型接口。")
    config = {key: getattr(payload, key) for key in keys}
    if kind == "llm" and config["enable_thinking"] is None:
        config["enable_thinking"] = get_settings().llm_enable_thinking
    return config


def input_key(db, user_id, kind, payload):
    config = input_config(payload, kind)
    if payload.api_key is not None:
        key = payload.api_key.get_secret_value().strip()
    else:
        candidates = [profile_for(db, user_id, kind, pending=True)] if kind == "embedding" else []
        candidates.append(profile_for(db, user_id, kind))
        key = None
        for candidate in candidates:
            previous = candidate.config if candidate else default_config(kind)
            if all(previous[field] == config[field] for field in ("provider", "base_url")):
                key = (
                    decrypt_key(user_id, candidate.encrypted_key).get_secret_value()
                    if candidate
                    else getattr(get_settings(), f"{kind}_api_key").get_secret_value()
                )
                break
        if key is None:
            raise HTTPException(400, "API 地址或提供商已变更，请为新接口填写 API Key。")
    if (not key and not local_endpoint(config["base_url"])) or any(ord(char) < 32 for char in key):
        raise HTTPException(400, "请填写有效的 API Key。")
    return key


def make_profile(db, user_id, kind, config, key):
    profile = ModelProfile(
        user_id=user_id,
        kind=kind,
        config=config,
        encrypted_key=encrypt_key(user_id, key),
        fingerprint=fingerprint(config),
    )
    db.add(profile)
    db.flush()
    return profile


def account_lock(db, user_id, expected=None):
    db.scalar(select(User).where(User.id == user_id).with_for_update())
    account = db.scalar(
        select(AccountModels)
        .where(AccountModels.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    if expected is not None and (account.version if account else 0) != expected:
        raise HTTPException(409, "模型设置已变更，请刷新后再保存。")
    if not account:
        account = AccountModels(user_id=user_id)
        db.add(account)
        db.flush()
    return account


def save_model(db, user_id, kind, payload):
    account = account_lock(db, user_id, payload.expected_version)
    config, key = input_config(payload, kind), input_key(db, user_id, kind, payload)
    if kind == "llm":
        old = profile_for(db, user_id, kind)
        profile = make_profile(db, user_id, kind, config, key)
        account.llm_id = profile.id
        db.flush()
        if old:
            db.delete(old)
    else:
        if not account.embedding_id:
            original = default_config("embedding")
            active = make_profile(
                db, user_id, kind, original, get_settings().embedding_api_key.get_secret_value()
            )
            account.embedding_id = active.id
            # 旧向量只在完整配置指纹相同时复用，未知来源的向量保持待重建。
            chunks = db.scalars(
                select(KnowledgeChunk)
                .join(Course, Course.id == KnowledgeChunk.course_id)
                .where(
                    Course.user_id == user_id,
                    KnowledgeChunk.embedding_status == "ready",
                    KnowledgeChunk.embedding.is_not(None),
                    KnowledgeChunk.embedding_fingerprint == active.fingerprint,
                )
            )
            for chunk in chunks:
                db.add(
                    KnowledgeEmbedding(
                        chunk_id=chunk.id,
                        profile_id=active.id,
                        embedding=chunk.embedding,
                        status="ready",
                    )
                )
            db.flush()
        active = profile_for(db, user_id, kind)
        pending = profile_for(db, user_id, kind, pending=True)
        identity = fingerprint(config)
        same = next(
            (item for item in (active, pending) if item and item.fingerprint == identity), None
        )
        if same:
            same.encrypted_key = encrypt_key(user_id, key)
            if same.id == active.id and pending:
                account.pending_embedding_id = None
                db.flush()
                db.delete(pending)
        else:
            profile = make_profile(db, user_id, kind, config, key)
            account.pending_embedding_id = profile.id
            db.flush()
            if pending:
                db.delete(pending)
    account.version += 1
    db.commit()
    return account
