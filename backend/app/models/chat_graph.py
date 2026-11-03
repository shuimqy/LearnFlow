from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatGraphThread(Base):
    __tablename__ = "chat_graph_threads"

    thread_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    run_id: Mapped[str] = mapped_column(String(36))
