import os

import pytest


@pytest.fixture(autouse=True)
def isolated_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(("LLM_", "MODEL_", "MODELS_", "EMBEDDING_", "RERANKER_")):
            monkeypatch.delenv(name)
