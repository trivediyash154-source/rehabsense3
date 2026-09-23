"""Shared response envelopes and query validation."""

from __future__ import annotations

from datetime import date
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")

RESPONSIBLE_USE = (
    "Estimated decision-support indicator produced by a research prototype. "
    "Not a diagnosis, clinical measurement, or replacement for clinical evaluation."
)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class DateRange(BaseModel):
    start_date: date | None = None
    end_date: date | None = None

    def validate_range(self) -> "DateRange":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    detail: ErrorBody
