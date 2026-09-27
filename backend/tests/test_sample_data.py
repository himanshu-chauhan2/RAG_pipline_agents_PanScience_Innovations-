from pathlib import Path
from shutil import copyfile

import pytest
import yaml

from scripts.make_sample_pdfs import generate_pdfs, validate_pdf
from scripts.sample_data import (
    DATA_DIR,
    PDF_DIR,
    EvaluationData,
    PolicyData,
    load_data,
    validate_dataset,
)


def test_required_coverage_and_disjoint_classifier_splits() -> None:
    summary = validate_dataset()
    assert summary.organizations == 2
    assert summary.documents == 6
    assert summary.pages == 13
    assert summary.evaluation_cases == 23
    assert summary.training_examples == 96
    assert summary.validation_examples == 24
    assert summary.categories["multi_condition"] >= 2
    assert summary.categories["comparison"] >= 1
    assert summary.categories["no_answer"] >= 1


def test_checked_in_pdfs_have_the_expected_text_and_page_references() -> None:
    policies = load_data("policies.yaml", PolicyData)
    for organization in policies.organizations:
        for document in organization.documents:
            validate_pdf(PDF_DIR / organization.slug / document.filename, document)


def test_pdf_generation_is_reproducible(tmp_path: Path) -> None:
    first = generate_pdfs(tmp_path / "first")
    second = generate_pdfs(tmp_path / "second")
    assert len(first) == len(second) == 6
    for left, right in zip(first, second, strict=True):
        assert left.read_bytes() == right.read_bytes()


@pytest.fixture
def dataset_directory(tmp_path: Path) -> Path:
    for name in ("policies.yaml", "classifier_examples.yaml", "test_questions.yaml"):
        copyfile(DATA_DIR / name, tmp_path / name)
    return tmp_path


def test_a_source_from_another_tenant_is_rejected(dataset_directory: Path) -> None:
    evaluation = load_data("test_questions.yaml", EvaluationData, dataset_directory)
    evaluation.cases[0].expected.sources[0].document = "Leave_Policy.pdf"
    (dataset_directory / "test_questions.yaml").write_text(
        yaml.safe_dump(evaluation.model_dump(mode="json")), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="source does not belong to this org"):
        validate_dataset(dataset_directory)


def test_a_nonexistent_page_is_rejected(dataset_directory: Path) -> None:
    evaluation = load_data("test_questions.yaml", EvaluationData, dataset_directory)
    evaluation.cases[0].expected.sources[0].page = 20
    (dataset_directory / "test_questions.yaml").write_text(
        yaml.safe_dump(evaluation.model_dump(mode="json")), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="source does not belong to this org/page"):
        validate_dataset(dataset_directory)


def test_eval_question_cannot_leak_into_classifier_training(dataset_directory: Path) -> None:
    path = dataset_directory / "classifier_examples.yaml"
    classifier = yaml.safe_load(path.read_text(encoding="utf-8"))
    evaluation = load_data("test_questions.yaml", EvaluationData, dataset_directory)
    classifier["training"]["direct"][0] = evaluation.cases[0].question
    path.write_text(yaml.safe_dump(classifier), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate train/validation/eval questions"):
        validate_dataset(dataset_directory)
