"""Shared schema pieces: strict input models, pagination, and search helpers."""

from typing import Annotated, ClassVar, Self

from fastapi import Query
from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

MAX_PAGE_SIZE = 200


class StrictModel(BaseModel):
    """Input model that rejects unknown fields, so a client cannot slip in extra
    attributes such as a role or an owner id."""

    model_config = ConfigDict(extra="forbid")


class PartialUpdate(StrictModel):
    """Base for PUT bodies where every field is optional.

    A field left out means "keep the current value". Sending null is only
    allowed for fields listed in NULLABLE; for any other field it is a 422.
    """

    NULLABLE: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def reject_nulls(self) -> Self:
        """Refuse explicit nulls for fields that cannot be cleared."""
        for name in self.model_fields_set - self.NULLABLE:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict[str, object]:
        """Return only the fields the client actually sent."""
        return {name: getattr(self, name) for name in self.model_fields_set}


class Page[T](BaseModel):
    """A page of results plus the total count for the same filters."""

    items: list[T]
    total: int


Limit = Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)]
Offset = Annotated[int, Query(ge=0)]
SearchText = Annotated[str | None, Query(max_length=100)]

# Emails are compared lowercase. Demo logins like admin@demo have no domain
# suffix, so this is a plain string with a length limit, not EmailStr.
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, min_length=3, max_length=254)
]


def like_pattern(text: str) -> str:
    """Build a case-insensitive contains pattern with LIKE wildcards escaped.

    Without escaping, a search for "50%" would match everything starting with 50.
    Use together with escape="\\" in .ilike().
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
