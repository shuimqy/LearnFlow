import logging
from pathlib import Path
from uuid import uuid4

import pymupdf
from fastapi import HTTPException, UploadFile

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def storage_file(key: str) -> Path:
    root = get_settings().storage_path.resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Invalid storage key")
    return path


def save_pdf(upload: UploadFile) -> tuple[str, int, int, str]:
    filename = (upload.filename or "").replace("\\", "/").split("/")[-1]
    if not filename.lower().endswith(".pdf") or len(filename) > 255:
        raise HTTPException(422, "请选择 PDF 文件，文件名不超过 255 个字符")
    if upload.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(422, "文件类型必须为 PDF")

    key = f"documents/{uuid4()}.pdf"
    path = storage_file(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    limit = get_settings().max_upload_mb * 1024 * 1024
    try:
        with path.open("xb") as target:
            while chunk := upload.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"文件不能超过 {get_settings().max_upload_mb} MB")
                target.write(chunk)
        with path.open("rb") as source:
            if b"%PDF-" not in source.read(1024):
                raise HTTPException(422, "文件内容不是有效的 PDF")
        try:
            # 损坏 PDF 从文件打开时可能遗留句柄，Windows 下会阻止清理。
            with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as pdf:
                if pdf.needs_pass:
                    raise HTTPException(422, "请先移除 PDF 密码后再上传")
                if not pdf.page_count:
                    raise HTTPException(422, "PDF 中没有可读取的页面")
                pages = pdf.page_count
        except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
            raise HTTPException(422, "PDF 已损坏或无法读取") from exc
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return key, size, pages, filename


def remove_file(key: str) -> None:
    try:
        storage_file(key).unlink(missing_ok=True)
    except OSError:
        logger.exception("Failed to remove stored file: %s", key)
