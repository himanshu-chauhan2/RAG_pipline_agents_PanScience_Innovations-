from pathlib import Path

import numpy as np
import pytest
import yaml

from app.decisions.rules import Conversation, MissingEvidence, RuleOutcome, classify, evaluate
from app.kb.index import IndexedChunk

SAMPLE = Path(__file__).resolve().parents[2] / "sample_data"


def org_chunks(slug: str) -> list[IndexedChunk]:
    policies = yaml.safe_load((SAMPLE / "policies.yaml").read_text(encoding="utf-8"))
    organization = next(o for o in policies["organizations"] if o["slug"] == slug)
    chunks = []
    for document in organization["documents"]:
        for page, content in enumerate(document["pages"], 1):
            text = " ".join([content["heading"], *content["paragraphs"]])
            chunks.append(
                IndexedChunk(
                    f"{document['filename']}-{page}",
                    document["filename"],
                    document["filename"],
                    page,
                    text,
                    np.ones(4, dtype=np.float32),
                )
            )
    return chunks


def decision_cases() -> list[dict]:
    cases = yaml.safe_load((SAMPLE / "test_questions.yaml").read_text(encoding="utf-8"))["cases"]
    return [c for c in cases if "decision_checks" in c["expected"]]


def conversation_for(case: dict) -> Conversation:
    history = case.get("history", [])
    if not history:
        return Conversation(case["question"], case["question"], None)
    prior = " ".join(t["content"] for t in history if t["role"] == "user")
    return Conversation(case["question"], f"{prior} {case['question']}", "gpa")


@pytest.mark.parametrize("case", decision_cases(), ids=lambda c: c["id"])
def test_sample_decisions_match_expected_checks(case: dict) -> None:
    chunks = org_chunks(case["org"])
    outcome = evaluate(conversation_for(case), chunks)
    assert isinstance(outcome, RuleOutcome), outcome
    expected = case["expected"]
    assert {c.id: c.result for c in outcome.checks} == expected["decision_checks"]
    if "verdict" in expected:
        assert outcome.verdict == expected["verdict"]
    status = "needs_info" if outcome.verdict == "needs_info" else "answered"
    assert status == expected["status"]
    assert outcome.missing_fields == expected.get("missing_fields", [])
    cited = {(s.chunk.document_name, s.chunk.page) for c in outcome.checks for s in c.spans}
    cited |= {(s.chunk.document_name, s.chunk.page) for s in outcome.notes}
    for source in expected["sources"]:
        assert (source["document"], source["page"]) in cited
    for check in outcome.checks:
        for span in check.spans:
            assert span.quote in span.chunk.text


def test_sports_scholarship_is_not_a_stacking_exception() -> None:
    question = (
        "I am in year 2, my GPA is 3.6 out of 4, and I hold a sports scholarship. "
        "Can I get the Merit Scholarship?"
    )
    outcome = evaluate(Conversation(question, question, None), org_chunks("northbridge-university"))
    assert isinstance(outcome, RuleOutcome)
    assert outcome.verdict == "not_eligible"
    stacking = next(c for c in outcome.checks if c.id == "stacking_met")
    assert any("Sports scholarships" in s.quote for s in stacking.spans)
    assert stacking.result is False and "NOT met" in outcome.answer


def test_rules_refuse_without_tenant_policy_evidence() -> None:
    question = "Am I eligible for the Merit Scholarship with GPA 3.9 in year 3?"
    outcome = evaluate(Conversation(question, question, None), org_chunks("acme-logistics"))
    assert isinstance(outcome, MissingEvidence)


def test_thresholds_come_from_documents_not_code() -> None:
    chunks = org_chunks("northbridge-university")
    edited = [
        IndexedChunk(
            c.id,
            c.document_id,
            c.document_name,
            c.page,
            c.text.replace("at least 3.50", "at least 3.70"),
            c.embedding,
        )
        for c in chunks
    ]
    question = "Year 3, GPA 3.6, no scholarships. Do I qualify for the Merit Scholarship?"
    outcome = evaluate(Conversation(question, question, None), edited)
    assert isinstance(outcome, RuleOutcome) and outcome.verdict == "not_eligible"


def test_classifier_categories() -> None:
    assert classify("Compare a single room with a twin room") == "comparison"
    assert classify("Walk me through requesting an exam re-evaluation") == "procedural"
    assert classify("At what times are quiet hours?") == "direct"
