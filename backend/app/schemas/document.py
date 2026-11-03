from datetime import datetime
from typing import Literal

from app.schemas.base import Output
from app.schemas.task import TaskOut

ExerciseMode = Literal["original", "generated", "both"]


class DocumentOut(Output):
    id: str
    course_id: str
    filename: str
    size_bytes: int
    page_count: int
    exercise_mode: str
    status: str
    created_at: datetime
    task: TaskOut
