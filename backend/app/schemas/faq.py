"""Schemas for FAQ articles.

Readers get one language (chosen by Accept-Language); IT staff editing an
article get both languages side by side.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.schemas.common import PartialUpdate, StrictModel
from app.schemas.tickets import Category

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class FaqCreate(StrictModel):
    """Body for POST /api/faq. Both languages are required, so no reader sees a gap."""

    category: Category
    title_en: Title
    body_en: Body
    title_ja: Title
    body_ja: Body


class FaqUpdate(PartialUpdate):
    """Body for PUT /api/faq/{id}. Only the fields sent are changed."""

    category: Category | None = None
    title_en: Title | None = None
    body_en: Body | None = None
    title_ja: Title | None = None
    body_ja: Body | None = None


class FaqOut(BaseModel):
    """An article in the reader's language."""

    id: int
    category: Category
    language: Literal["ja", "en"]
    title: str
    body: str
    updated_at: datetime


class FaqFull(BaseModel):
    """An article with both languages, for editing."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    category: Category
    title_en: str
    body_en: str
    title_ja: str
    body_ja: str
    updated_by: int | None
    created_at: datetime
    updated_at: datetime
