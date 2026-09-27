from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["answered", "needs_info", "insufficient_evidence"]
Category = Literal["direct", "procedural", "policy", "comparison", "multi_condition", "no_answer"]


class HistoryTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=128)
    question: str = Field(min_length=1, max_length=1000)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=10)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Enter a question.")
        return value.strip()


class Citation(BaseModel):
    id: str
    document_id: str
    document_name: str
    page: int
    quote: str


class Classification(BaseModel):
    category: Category
    method: Literal["rules"] = "rules"


class DecisionCheck(BaseModel):
    id: str
    label: str
    result: bool | None
    observed: str | None
    requirement: str
    reference_ids: list[str]


class Decision(BaseModel):
    rule_set: str
    verdict: Literal["eligible", "not_eligible", "needs_info", "required", "not_required"]
    checks: list[DecisionCheck]
    missing_fields: list[str]
    score: float = Field(ge=0, le=1)


class TraceStep(BaseModel):
    step: str
    status: Literal["ok", "skipped", "failed"]
    detail: str


class AskResponse(BaseModel):
    status: Status
    answer: str
    follow_up_question: str | None = None
    references: list[Citation]
    classification: Classification
    verdict: str | None = None
    decision_trace: Decision | None = None
    confidence: float = Field(ge=0, le=1)
    trace: list[TraceStep]
