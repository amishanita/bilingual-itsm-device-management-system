"""FAQ articles: language selection, search, and edits.

Search works for English and Japanese without a database extension. Japanese
has no spaces between words, so the query is split into runs of katakana,
kanji, and Latin letters or digits ("VPNに接続できない" -> "vpn", "接続").
Hiragana runs are mostly particles and verb endings, so they are dropped.
An article scores 3 for each term in its title and 1 for each term in its
body; the highest scores come first. The chatbot's search_faq tool uses the
same function, so the FAQ page and the bot agree on what is relevant.
"""

import re
import unicodedata
from typing import Any

from sqlalchemy import Integer, case, literal, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import FaqArticle, User
from app.schemas.common import like_pattern
from app.services import audit_service

LANGUAGES = ("ja", "en")
DEFAULT_LANGUAGE = "ja"
MAX_TERMS = 10
TERM_PATTERN = re.compile(r"[a-z0-9]+|[ァ-ヺー]+|[一-鿿々]+")


def language_from_header(header: str | None) -> str:
    """Pick "en" or "ja" from an Accept-Language header; Japanese by default."""
    for part in (header or "").split(","):
        tag = part.split(";")[0].strip().lower()
        if tag.startswith("en"):
            return "en"
        if tag.startswith("ja"):
            return "ja"
    return DEFAULT_LANGUAGE


def search_terms(query: str) -> list[str]:
    """Split a search query into terms, as described in the module docstring."""
    normalized = unicodedata.normalize("NFKC", query).lower()
    terms: list[str] = []
    for term in TERM_PATTERN.findall(normalized):
        if len(term) >= 2 and term not in terms:
            terms.append(term)
    return terms[:MAX_TERMS]


def columns(language: str) -> tuple[Any, Any]:
    """The title and body columns for a language."""
    if language == "en":
        return FaqArticle.title_en, FaqArticle.body_en
    return FaqArticle.title_ja, FaqArticle.body_ja


def search(
    db: Session,
    language: str,
    query: str | None = None,
    category: str | None = None,
    limit: int = 50,
) -> list[FaqArticle]:
    """Articles matching the query in one language, best match first.

    Without a query, every article (optionally in one category) is returned
    ordered by category and id.
    """
    title, body = columns(language)
    statement = select(FaqArticle)
    if category:
        statement = statement.where(FaqArticle.category == category)
    if not query or not query.strip():
        return list(db.scalars(statement.order_by(FaqArticle.category, FaqArticle.id).limit(limit)))

    # Queries with no usable term (one kana, punctuation) fall back to a phrase match.
    terms = search_terms(query) or [query.strip()]
    score = literal(0, type_=Integer)
    for term in terms:
        pattern = like_pattern(term)
        score = (
            score
            + case((title.ilike(pattern, escape="\\"), 3), else_=0)
            + case((body.ilike(pattern, escape="\\"), 1), else_=0)
        )
    ranked = (
        statement.add_columns(score.label("score"))
        .where(score > 0)
        .order_by(score.desc(), FaqArticle.id)
        .limit(limit)
    )
    return [row[0] for row in db.execute(ranked)]


def localized(article: FaqArticle, language: str) -> dict[str, Any]:
    """An article as one language, for readers and the chatbot."""
    english = language == "en"
    return {
        "id": article.id,
        "category": article.category,
        "language": "en" if english else "ja",
        "title": article.title_en if english else article.title_ja,
        "body": article.body_en if english else article.body_ja,
        "updated_at": article.updated_at,
    }


def get_article(db: Session, article_id: int) -> FaqArticle:
    """One article, or 404 FAQ_NOT_FOUND."""
    article = db.get(FaqArticle, article_id)
    if article is None:
        raise AppError(404, "FAQ_NOT_FOUND", "The FAQ article does not exist.")
    return article


def create_article(db: Session, values: dict[str, Any], actor: User) -> FaqArticle:
    """Add an article in both languages and record it in the audit log."""
    article = FaqArticle(**values, updated_by=actor.id)
    db.add(article)
    db.flush()
    audit_service.record(
        db, actor, "FAQ_CREATED", "faq", article.id, {"category": article.category}
    )
    return article


def update_article(
    db: Session, article_id: int, changes: dict[str, Any], actor: User
) -> FaqArticle:
    """Change the fields sent. The audit row lists which fields changed, not the text."""
    article = get_article(db, article_id)
    changed = [field for field, value in changes.items() if getattr(article, field) != value]
    for field in changed:
        setattr(article, field, changes[field])
    if changed:
        article.updated_by = actor.id
        audit_service.record(
            db, actor, "FAQ_UPDATED", "faq", article.id, {"fields": sorted(changed)}
        )
    db.flush()
    return article
