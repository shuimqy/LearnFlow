import base64
import copy

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import undefer

from app.models import WorkbookAsset


def attach_workbook_images(db, workbook, snapshot):
    snapshot = copy.deepcopy(snapshot)
    assets = {
        asset.id: asset
        for asset in db.scalars(
            select(WorkbookAsset)
            .options(undefer(WorkbookAsset.data))
            .where(WorkbookAsset.workbook_id == workbook.id)
        )
    }
    original = workbook.settings.get("print_mode", "text") == "original"
    missing = []
    for group in snapshot["sections"]:
        for item in group["items"]:
            item["question_images"], item["figures"] = [], []
            for reference in item.get("assets", []):
                asset = assets.get(reference["id"])
                if not asset or asset.draft_id != item["draft_id"]:
                    raise HTTPException(409, "做题本图片快照不完整，请重新载入原题裁片后保存。")
                target = "question_images" if asset.role == "question" else "figures"
                item[target].append(
                    "data:image/png;base64," + base64.b64encode(asset.data).decode("ascii")
                )
            if original and not item["question_images"]:
                missing.append(item["title"])
    if missing:
        raise HTTPException(
            422,
            "以下题目还没有已确认的原题裁片："
            + "、".join(missing[:8])
            + "。请核对裁片后重新加入，或改用文字重排。",
        )
    return snapshot
