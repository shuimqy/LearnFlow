import json
import os
import shutil
import subprocess
from threading import BoundedSemaphore

from fastapi import HTTPException

from app.core.config import ROOT

_render_slots = BoundedSemaphore(2)


def render_workbook_pdf(snapshot):
    node = shutil.which("node")
    if not node:
        raise HTTPException(503, "PDF 导出需要 Node.js，请先安装前端依赖后重试。")
    if not _render_slots.acquire(blocking=False):
        raise HTTPException(429, "正在生成其它做题本，请稍后重试。")
    try:
        result = subprocess.run(
            [node, str(ROOT / "frontend" / "scripts" / "render-workbook.mjs")],
            input=json.dumps(snapshot, ensure_ascii=False).encode("utf-8"),
            capture_output=True,
            timeout=90,
            cwd=ROOT / "frontend",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
        if result.returncode or not result.stdout.startswith(b"%PDF-"):
            # 浏览器错误可能包含题目正文，不写入日志或返回给网页。
            raise HTTPException(
                503, "PDF 生成失败。请确认前端依赖已安装，Windows 上已安装 Microsoft Edge 后重试。"
            )
        return result.stdout
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "PDF 生成超时，请减少题目数量后重试。") from None
    except OSError:
        raise HTTPException(503, "PDF 导出程序暂不可用，请检查 Node.js 和浏览器环境。") from None
    finally:
        _render_slots.release()
