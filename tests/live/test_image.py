"""The built image loads the embedding model with no network at all.
Skipped when Docker or the image isn't available. Build it with:
    docker build -t ai-analytics-copilot:latest .
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

IMAGE = "ai-analytics-copilot:latest"
SCRIPT = (
    "import tempfile; from src.config import Settings; from src.rag.vector_store import KnowledgeBaseStore; "
    "s = Settings(_env_file=None, chroma_persist_dir=tempfile.mkdtemp()); "
    "kb = KnowledgeBaseStore(s); kb.add(['a'], ['win rate dropped after a timeout spike'], ['t']); "
    "hits = kb.query('why did win rate drop', min_similarity=0.0); "
    "assert hits, 'no result'; print('offline ok')"
)


def test_model_loads_offline():
    if shutil.which("docker") is None:
        pytest.skip("docker not installed")
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        pytest.skip(f"image {IMAGE} not built")
    done = subprocess.run(["docker", "run", "--rm", "--network", "none", IMAGE, "python", "-c", SCRIPT],
                          capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "offline ok" in done.stdout
