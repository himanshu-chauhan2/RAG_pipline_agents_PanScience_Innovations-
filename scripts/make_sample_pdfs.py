import argparse
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

from scripts.sample_data import (
    DATA_DIR,
    PDF_DIR,
    Organization,
    PolicyData,
    PolicyDocument,
    load_data,
    validate_dataset,
)

MAX_PDF_BYTES = 10_000_000


def write_pdf(organization: Organization, document: PolicyDocument, output: Path) -> Path:
    destination = output / organization.slug / document.filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(destination), pagesize=A4, invariant=1, pageCompression=1)
    width, height = A4
    margin = 48
    canvas.setTitle(document.title)
    canvas.setAuthor(f"{organization.name} - fictional demonstration data")
    for number, page in enumerate(document.pages, 1):
        canvas.setFont("Helvetica", 9)
        canvas.drawString(margin, height - margin, organization.name)
        canvas.setFont("Helvetica-Bold", 16)
        canvas.drawString(margin, height - margin - 28, page.heading)
        y = height - margin - 60
        canvas.setFont("Helvetica", 11)
        for paragraph in page.paragraphs:
            for line in simpleSplit(paragraph, "Helvetica", 11, width - 2 * margin):
                if y < margin + 30:
                    raise ValueError(
                        f"{document.filename}, page {number}: content exceeds one page"
                    )
                canvas.drawString(margin, y, line)
                y -= 16
            y -= 12
        canvas.setFont("Helvetica", 9)
        canvas.drawString(margin, margin, "Fictional sample policy - not real institutional advice")
        canvas.drawRightString(width - margin, margin, f"Page {number} of {len(document.pages)}")
        canvas.showPage()
    canvas.save()
    validate_pdf(destination, document)
    return destination


def validate_pdf(path: Path, document: PolicyDocument) -> None:
    if path.stat().st_size > MAX_PDF_BYTES:
        raise ValueError(f"{path.name}: exceeds the 10 MB limit")
    reader = PdfReader(path)
    if reader.is_encrypted or len(reader.pages) != len(document.pages):
        raise ValueError(f"{path.name}: encryption or unstable page count")
    for number, (actual, expected) in enumerate(zip(reader.pages, document.pages, strict=True), 1):
        text = actual.extract_text()
        if expected.heading not in text:
            raise ValueError(f"{path.name}, page {number}: expected heading is not extractable")
        normalized_text = " ".join(text.split())
        for paragraph in expected.paragraphs:
            if " ".join(paragraph.split()) not in normalized_text:
                raise ValueError(
                    f"{path.name}, page {number}: policy text was lost during rendering"
                )


def generate_pdfs(output: Path = PDF_DIR, directory: Path = DATA_DIR) -> list[Path]:
    validate_dataset(directory)
    policies = load_data("policies.yaml", PolicyData, directory)
    return [
        write_pdf(org, document, output)
        for org in policies.organizations
        for document in org.documents
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic, page-checked demo PDFs.")
    parser.add_argument("--output-dir", type=Path, default=PDF_DIR)
    arguments = parser.parse_args()
    paths = generate_pdfs(arguments.output_dir)
    for path in paths:
        print(f"Created {path.relative_to(arguments.output_dir)}")
    print(f"Validated {len(paths)} PDFs; all source paragraphs and page references are preserved.")


if __name__ == "__main__":
    main()
