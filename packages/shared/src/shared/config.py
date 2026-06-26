import os
from pathlib import Path

_HERE = Path(__file__).parent          # packages/shared/src/shared/
PROJECT_ROOT = _HERE.parents[3]        # packages/shared/src/ -> packages/shared/ -> packages/ -> project root

# Default to localhost. In the reference dev setup a Mac Studio is connected via
# Thunderbolt Bridge at 169.254.1.1 — override with OLLAMA_BASE_URL env var.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL     = "nomic-embed-text"
LLM_MODEL       = os.getenv("OLLAMA_MODEL", "qwen2.5:72b")
OLLAMA_MODEL    = LLM_MODEL

DB_PATH = Path(os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "common_core.db")))
