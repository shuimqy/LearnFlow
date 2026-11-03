import contextlib
import json
import os
import tempfile

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.core.config import ROOT, get_settings
from app.services.model_api import ModelAPIError


def cipher():
    key = get_settings().model_encryption_key.get_secret_value()
    if not key:
        target = ROOT / ".local" / "model-encryption.key"
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix="model-key-")
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(Fernet.generate_key())
                with contextlib.suppress(FileExistsError):
                    os.link(temporary, target)
            finally:
                os.unlink(temporary)
        key = target.read_bytes()
    try:
        return Fernet(key)
    except (ValueError, TypeError):
        raise ModelAPIError("模型密钥加密配置无效，请检查服务端配置。") from None


def encrypt_key(user_id, value):
    data = json.dumps({"user_id": user_id, "key": value}).encode()
    return cipher().encrypt(data).decode()


def decrypt_key(user_id, value):
    try:
        data = json.loads(cipher().decrypt(value.encode()))
        if data["user_id"] != user_id:
            raise ValueError("Credential owner mismatch")
        return SecretStr(data["key"])
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise ModelAPIError("无法解密模型密钥，请重新保存该账号的模型配置。") from None
