from datetime import datetime

from app.schemas.base import Output


class TaskOut(Output):
    id: str
    document_id: str
    status: str
    stage: str
    progress: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    filename: str | None = None
    course_id: str | None = None
    course_name: str | None = None
