import pymupdf
from fastapi import HTTPException

from app.models import Document
from app.services.storage import storage_file


def render_page(document: Document, page_number: int) -> bytes:
    if not 1 <= page_number <= document.page_count:
        raise HTTPException(422, "页码超出了课件范围")
    path = storage_file(document.storage_key)
    if not path.is_file():
        raise HTTPException(404, "原始文件已丢失，请重新上传")
    try:
        with pymupdf.open(stream=path.read_bytes(), filetype="pdf") as pdf:
            page = pdf[page_number - 1]
            scale = min(2.5, 2000 / max(page.rect.width, page.rect.height))
            pixmap = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False
            )
            return pixmap.tobytes("png")
    except (pymupdf.FileDataError, RuntimeError, IndexError, ZeroDivisionError) as exc:
        raise HTTPException(422, "该页暂时无法读取，请检查原始课件") from exc
