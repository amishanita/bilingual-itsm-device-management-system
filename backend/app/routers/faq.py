"""FAQ endpoints.

Everyone signed in can read articles in their language (Accept-Language,
Japanese by default). IT staff can add and edit articles, and read both
languages of one article for the edit form.
"""

from typing import Annotated

from fastapi import APIRouter, Header, Query

from app.core.deps import CurrentUser, DbSession, ItAdmin
from app.schemas.common import Limit, Page, SearchText
from app.schemas.faq import FaqCreate, FaqFull, FaqOut, FaqUpdate
from app.schemas.tickets import Category
from app.services import faq_service

router = APIRouter(prefix="/faq", tags=["faq"])

AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language")]


@router.get("", response_model=Page[FaqOut])
def list_faq(
    db: DbSession,
    _user: CurrentUser,
    accept_language: AcceptLanguage = None,
    q: SearchText = None,
    category: Category | None = None,
    lang: Annotated[str | None, Query(pattern="^(ja|en)$")] = None,
    limit: Limit = 50,
) -> Page[FaqOut]:
    """Articles in one language. q searches title and body; the best matches come first."""
    language = lang or faq_service.language_from_header(accept_language)
    articles = faq_service.search(db, language, q, category, limit)
    items = [FaqOut(**faq_service.localized(a, language)) for a in articles]
    return Page[FaqOut](items=items, total=len(items))


@router.post("", response_model=FaqFull, status_code=201)
def create_faq(body: FaqCreate, db: DbSession, admin: ItAdmin) -> FaqFull:
    """Add an article. Both languages are required."""
    article = faq_service.create_article(db, body.model_dump(), admin)
    db.commit()
    db.refresh(article)
    return FaqFull.model_validate(article)


@router.get("/{article_id}", response_model=FaqOut)
def read_faq(
    article_id: int, db: DbSession, _user: CurrentUser, accept_language: AcceptLanguage = None
) -> FaqOut:
    """One article in the reader's language."""
    language = faq_service.language_from_header(accept_language)
    return FaqOut(**faq_service.localized(faq_service.get_article(db, article_id), language))


@router.get("/{article_id}/full", response_model=FaqFull)
def read_faq_full(article_id: int, db: DbSession, _admin: ItAdmin) -> FaqFull:
    """One article in both languages, for the edit form."""
    return FaqFull.model_validate(faq_service.get_article(db, article_id))


@router.put("/{article_id}", response_model=FaqFull)
def update_faq(article_id: int, body: FaqUpdate, db: DbSession, admin: ItAdmin) -> FaqFull:
    """Edit an article. Only the fields sent are changed."""
    article = faq_service.update_article(db, article_id, body.changes(), admin)
    db.commit()
    db.refresh(article)
    return FaqFull.model_validate(article)
