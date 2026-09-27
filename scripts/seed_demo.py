"""Create two isolated demo workspaces and upload the fictional sample policies."""

import argparse
import secrets
import time

import httpx

from scripts.make_sample_pdfs import generate_pdfs
from scripts.sample_data import PDF_DIR, PolicyData, load_data


def seed(base_url: str, timeout_seconds: int, frontend_url: str) -> dict[str, dict[str, str]]:
    policies = load_data("policies.yaml", PolicyData)
    generate_pdfs()
    credentials: dict[str, dict[str, str]] = {}
    for organization in policies.organizations:
        password = secrets.token_urlsafe(18)
        email = f"demo-{organization.slug}-{secrets.token_hex(4)}@example.com"
        with httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Origin": base_url.rstrip("/")},
            timeout=30,
        ) as client:
            registration = client.post(
                "/api/auth/register",
                json={
                    "organization_name": organization.name,
                    "full_name": "Demo Owner",
                    "email": email,
                    "password": password,
                },
            )
            registration.raise_for_status()
            assistant = client.get("/api/assistant")
            assistant.raise_for_status()
            link_data = assistant.json()
            token = link_data["token"]
            if link_data["organization_id"] != registration.json()["organization"]["id"]:
                raise RuntimeError("The assistant token does not belong to the new workspace.")
            for document in organization.documents:
                path = PDF_DIR / organization.slug / document.filename
                with path.open("rb") as pdf:
                    response = client.post(
                        "/api/documents",
                        files={"file": (path.name, pdf, "application/pdf")},
                    )
                response.raise_for_status()
                document_id = response.json()["id"]
                deadline = time.monotonic() + timeout_seconds
                while time.monotonic() < deadline:
                    status = client.get(f"/api/documents/{document_id}")
                    status.raise_for_status()
                    result = status.json()
                    if result["status"] == "ready":
                        print(
                            f"{organization.slug}: {document.filename} ready "
                            f"({result['pages']} pages)"
                        )
                        break
                    if result["status"] == "failed":
                        raise RuntimeError(
                            f"{organization.slug}: {document.filename} failed: {result['error']}"
                        )
                    time.sleep(1)
                else:
                    raise TimeoutError(f"{organization.slug}: {document.filename} did not index")
        credentials[organization.slug] = {"email": email, "password": password}
        print(f"{organization.slug} demo owner: {email} / {password}")
        print(f"{organization.slug} assistant: {frontend_url.rstrip('/')}/a/{token}")
    return credentials


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed two isolated demo organisations via the API."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--frontend-url", default="http://127.0.0.1:5173")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()
    print("Demo owner credentials are printed once per workspace; keep them private.")
    seed(args.base_url, args.timeout_seconds, args.frontend_url)


if __name__ == "__main__":
    main()
