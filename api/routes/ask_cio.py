"""Read-only Ask the CIO API surface."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from intelligence.ask_cio import AskCIOService


router = APIRouter(prefix="/v1/cio", tags=["cio"])


class AskCIORequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


@router.post("/ask")
def ask_cio(payload: AskCIORequest) -> dict:
    """Answer from canonical post-cycle evidence without portfolio authority."""

    return AskCIOService().answer(payload.question).to_dict()


__all__ = ["router"]
