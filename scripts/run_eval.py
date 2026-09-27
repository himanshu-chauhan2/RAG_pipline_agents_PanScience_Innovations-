"""Run held-out questions against two published assistant tokens."""

import argparse
import os

import httpx

from scripts.sample_data import EvaluationData, PolicyData, load_data


def evaluate(base_url: str, *, all_cases: bool = False) -> int:
    tokens = {
        "northbridge-university": os.environ.get("KDA_NORTHBRIDGE_TOKEN", ""),
        "acme-logistics": os.environ.get("KDA_ACME_TOKEN", ""),
    }
    if not all(tokens.values()):
        raise ValueError(
            "Set KDA_NORTHBRIDGE_TOKEN and KDA_ACME_TOKEN from the two owner dashboards."
        )
    cases = load_data("test_questions.yaml", EvaluationData).cases
    documents_by_org = {
        organization.slug: {
            document.filename: len(document.pages) for document in organization.documents
        }
        for organization in load_data("policies.yaml", PolicyData).organizations
    }
    selected = [case for case in cases if all_cases or case.mandatory_demo]
    failures = 0
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=90) as client:
        for case in selected:
            response = client.post(
                "/api/ask",
                json={
                    "token": tokens[case.org],
                    "question": case.question,
                    "history": [message.model_dump() for message in case.history],
                },
            )
            if response.status_code != 200:
                print(f"FAIL {case.id}: HTTP {response.status_code} {response.text[:240]}")
                failures += 1
                continue
            result = response.json()
            errors: list[str] = []
            if result.get("status") != case.expected.status:
                errors.append(f"status {result.get('status')!r} != {case.expected.status!r}")
            if case.expected.verdict is not None and result.get("verdict") != case.expected.verdict:
                errors.append(f"verdict {result.get('verdict')!r} != {case.expected.verdict!r}")
            answer = result.get("answer")
            if not isinstance(answer, str) or not answer.strip():
                errors.append("missing answer/explanation")
            answer_text = answer if isinstance(answer, str) else ""
            references = result.get("references")
            if not isinstance(references, list):
                errors.append("references is not a list")
                references = []
            if any(not isinstance(reference, dict) for reference in references):
                errors.append("reference is not an object")
            actual_sources = [
                (
                    reference.get("document_name", reference.get("document")),
                    reference.get("page"),
                )
                for reference in references
                if isinstance(reference, dict)
            ]
            for document, page in actual_sources:
                if (
                    not isinstance(document, str)
                    or document not in documents_by_org[case.org]
                    or not isinstance(page, int)
                    or isinstance(page, bool)
                    or page < 1
                    or page > documents_by_org[case.org].get(document, 0)
                ):
                    errors.append(f"citation outside this workspace: {document!r}, page {page!r}")
            for source in case.expected.sources:
                if (source.document, source.page) not in actual_sources:
                    errors.append(f"missing citation {source.document} — Page {source.page}")
            for forbidden in case.expected.forbidden_claims:
                if forbidden.casefold() in answer_text.casefold():
                    errors.append(f"forbidden claim: {forbidden}")
            if (
                case.decision_types
                and result.get("status") == "answered"
                and not result.get("decision_trace")
            ):
                errors.append("missing structured decision trace")
            decision = result.get("decision_trace")
            if case.expected.missing_fields or case.expected.decision_checks:
                if not isinstance(decision, dict):
                    errors.append("missing decision details")
                else:
                    missing = decision.get("missing_fields")
                    if not isinstance(missing, list) or not set(
                        case.expected.missing_fields
                    ).issubset(set(field for field in missing if isinstance(field, str))):
                        errors.append("missing required clarification fields")
                    checks = decision.get("checks")
                    actual_checks = (
                        {
                            check.get("id"): check.get("result")
                            for check in checks
                            if isinstance(check, dict) and isinstance(check.get("id"), str)
                        }
                        if isinstance(checks, list)
                        else {}
                    )
                    for check_id, expected_result in case.expected.decision_checks.items():
                        if (
                            check_id not in actual_checks
                            or actual_checks[check_id] is not expected_result
                        ):
                            errors.append(
                                f"decision check {check_id}: expected {expected_result!r}"
                            )
            if errors:
                failures += 1
                print(f"FAIL {case.id}: {'; '.join(errors)}")
            else:
                print(f"PASS {case.id}: {result['status']}")
    print(f"{len(selected) - failures}/{len(selected)} passed (status, verdict, citations, trace).")
    print("Factual completeness and citation support still require manual inspection.")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the published fictional policy assistants."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--all", action="store_true", help="Run all 23 cases, not just mandatory demos"
    )
    args = parser.parse_args()
    raise SystemExit(1 if evaluate(args.base_url, all_cases=args.all) else 0)


if __name__ == "__main__":
    main()
