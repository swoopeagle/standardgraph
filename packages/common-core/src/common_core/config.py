import os
from pathlib import Path

# For distributed installs (uvx / PyPI), the database lives in ~/.standardgraph/.
# For local dev, override via the DB_PATH env var.
DB_PATH = Path(os.getenv("DB_PATH", str(Path.home() / ".standardgraph" / "common_core.db")))

# Distributed users run Ollama locally; the 169.254.1.1 Thunderbolt Bridge address
# is overridden by OLLAMA_BASE_URL in the local dev / overnight pipeline environment.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"
