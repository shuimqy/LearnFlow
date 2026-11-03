from fastapi import APIRouter

from app.api import (
    account,
    auth,
    chat,
    courses,
    document_structure,
    documents,
    extraction,
    knowledge,
    tasks,
    workbooks,
)

router = APIRouter(prefix="/api")
for module in (
    auth,
    courses,
    documents,
    tasks,
    knowledge,
    extraction,
    chat,
    account,
    workbooks,
    document_structure,
):
    router.include_router(module.router)
