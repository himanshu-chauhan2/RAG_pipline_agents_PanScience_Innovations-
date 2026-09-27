import re
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictBool

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "sample_data"
PDF_DIR = DATA_DIR / "pdfs"
NonEmptyText = Annotated[str, Field(min_length=1)]
QuestionLabel = Literal[
    "direct", "policy", "procedural", "eligibility", "comparison", "out_of_scope"
]
CATEGORIES = {"direct", "policy", "procedural", "multi_condition", "comparison", "no_answer"}
CLASSIFIER_LABELS = {"direct", "policy", "procedural", "eligibility", "comparison", "out_of_scope"}


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PolicyPage(DataModel):
    heading: NonEmptyText
    paragraphs: list[NonEmptyText] = Field(min_length=1)


class PolicyDocument(DataModel):
    filename: str = Field(pattern=r"^[A-Za-z0-9_]+\.pdf$")
    title: NonEmptyText
    pages: list[PolicyPage] = Field(min_length=1, max_length=20)


class Organization(DataModel):
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    name: NonEmptyText
    documents: list[PolicyDocument] = Field(min_length=2, max_length=3)


class PolicyData(DataModel):
    organizations: list[Organization] = Field(min_length=2)


class SourceReference(DataModel):
    document: NonEmptyText
    page: int = Field(ge=1, le=20)


class ChatMessage(DataModel):
    role: Literal["user", "assistant"]
    content: NonEmptyText


class ExpectedOutcome(DataModel):
    status: Literal["answered", "needs_info", "insufficient_evidence", "needs_review"]
    verdict: Literal["eligible", "not_eligible"] | None = None
    required_facts: dict[str, JsonValue] = Field(default_factory=dict)
    decision_checks: dict[str, StrictBool | None] = Field(default_factory=dict)
    sources: list[SourceReference] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)


class EvaluationCase(DataModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    org: NonEmptyText
    category: Literal[
        "direct", "policy", "procedural", "multi_condition", "comparison", "no_answer"
    ]
    question: NonEmptyText
    history: list[ChatMessage] = Field(default_factory=list, max_length=8)
    decision_types: list[Literal["classification", "choice", "boolean", "score"]] = Field(
        default_factory=list
    )
    mandatory_demo: bool = False
    expected: ExpectedOutcome


class EvaluationData(DataModel):
    cases: list[EvaluationCase] = Field(min_length=15)


class ClassifierData(DataModel):
    training: dict[QuestionLabel, list[NonEmptyText]]
    validation: dict[QuestionLabel, list[NonEmptyText]]


class DatasetSummary(DataModel):
    organizations: int
    documents: int
    pages: int
    evaluation_cases: int
    training_examples: int
    validation_examples: int
    categories: dict[str, int]


def load_data[T: BaseModel](filename: str, model: type[T], directory: Path = DATA_DIR) -> T:
    with (directory / filename).open(encoding="utf-8") as source:
        return model.model_validate(yaml.safe_load(source))


def normalized_question(question: str) -> str:
    return re.sub(r"\W+", " ", question.casefold()).strip()


def require_unique(values: list[str], description: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {description} in sample data")


def validate_dataset(directory: Path = DATA_DIR) -> DatasetSummary:
    policies = load_data("policies.yaml", PolicyData, directory)
    evaluation = load_data("test_questions.yaml", EvaluationData, directory)
    classifier = load_data("classifier_examples.yaml", ClassifierData, directory)
    require_unique([org.slug for org in policies.organizations], "organisation slugs")
    require_unique([case.id for case in evaluation.cases], "evaluation IDs")
    documents = {
        org.slug: {doc.filename: doc for doc in org.documents} for org in policies.organizations
    }
    for org in policies.organizations:
        require_unique([doc.filename.casefold() for doc in org.documents], "PDF filenames")
    counts = Counter(case.category for case in evaluation.cases)
    if set(counts) != CATEGORIES or counts["multi_condition"] < 2:
        raise ValueError("Evaluation must cover all six categories and two multi-condition cases")
    if not any(len(set(case.decision_types)) >= 2 for case in evaluation.cases):
        raise ValueError("Evaluation needs a case with multiple structured decision types")
    for case in evaluation.cases:
        if case.org not in documents:
            raise ValueError(f"{case.id}: unknown organisation")
        if len(case.question) > 2000 or sum(len(item.content) for item in case.history) > 8000:
            raise ValueError(f"{case.id}: question/history exceeds the API contract")
        for reference in case.expected.sources:
            document = documents[case.org].get(reference.document)
            if document is None or reference.page > len(document.pages):
                raise ValueError(f"{case.id}: source does not belong to this org/page")
        if case.expected.status == "answered" and not case.expected.sources:
            raise ValueError(f"{case.id}: an answered fixture must name its evidence")
        if case.expected.status != "answered" and case.expected.verdict is not None:
            raise ValueError(f"{case.id}: a non-answer cannot carry an eligibility verdict")
        if case.expected.status == "needs_info" and not case.expected.missing_fields:
            raise ValueError(f"{case.id}: clarification must identify missing fields")
    split_questions: list[list[str]] = []
    for name, split in (("training", classifier.training), ("validation", classifier.validation)):
        if set(split) != CLASSIFIER_LABELS or any(not examples for examples in split.values()):
            raise ValueError(f"{name}: all six classifier labels need examples")
        split_questions.append(
            [normalized_question(question) for examples in split.values() for question in examples]
        )
    held_out = [normalized_question(case.question) for case in evaluation.cases]
    require_unique(
        split_questions[0] + split_questions[1] + held_out, "train/validation/eval questions"
    )
    return DatasetSummary(
        organizations=len(policies.organizations),
        documents=sum(len(org.documents) for org in policies.organizations),
        pages=sum(len(doc.pages) for org in policies.organizations for doc in org.documents),
        evaluation_cases=len(evaluation.cases),
        training_examples=len(split_questions[0]),
        validation_examples=len(split_questions[1]),
        categories=dict(sorted(counts.items())),
    )
