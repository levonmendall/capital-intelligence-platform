"""Read-only Ask the CIO API surface."""
from __future__ import annotations

from fastapi import APIRouter, Query

from intelligence.ask_cio import AskCIOService


router = APIRouter(prefix="/v1/cio", tags=["cio"])


@router.get("/ask")
def ask_cio(
    question: str = Query(min_length=1, max_length=2000),
) -> dict:
    """Answer from canonical post-cycle evidence without portfolio authority."""

    return AskCIOService().answer(question).to_dict()


__all__ = ["router"]
