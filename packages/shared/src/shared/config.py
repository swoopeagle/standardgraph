import os
from pathlib import Path

_HERE = Path(__file__).parent          # packages/shared/src/shared/
PROJECT_ROOT = _HERE.parents[3]        # packages/shared/src/ -> packages/shared/ -> packages/ -> project root

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://169.254.1.1:11434")
EMBED_MODEL     = "nomic-embed-text"
LLM_MODEL       = "gemma4:31b-it-q8_0"

DB_PATH = Path(os.getenv("DB_PATH", str(PROJECT_ROOT / "data" / "common_core.db")))
