"""FAQ articles stored in both English and Japanese."""

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class FaqArticle(TimestampMixin, Base):
    """A help article with an English and a Japanese version side by side."""

    __tablename__ = "faq_articles"
    __table_args__ = (Index("ix_faq_articles_category", "category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(50))
    title_en: Mapped[str] = mapped_column(String(200))
    body_en: Mapped[str] = mapped_column(Text)
    title_ja: Mapped[str] = mapped_column(String(200))
    body_ja: Mapped[str] = mapped_column(Text)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
