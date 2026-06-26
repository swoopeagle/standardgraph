"""Stage 5: Generate embeddings for all standards via Ollama nomic-embed-text."""
import sqlite3

import httpx
import numpy as np

from shared.config import DB_PATH, OLLAMA_BASE_URL, EMBED_MODEL

BATCH_SIZE = 20
MAX_RETRIES = 3


def embed_texts(texts: list[str], client: httpx.Client) -> np.ndarray:
    import time
    for attempt in range(MAX_RETRIES):
        try:
            resp = client.post(
                f"{OLLAMA_BASE_URL}/api/embed",
                json={"model": EMBED_MODEL, "input": texts, "keep_alive": "2h"},
                timeout=120,
            )
            resp.raise_for_status()
            return np.array(resp.json()["embeddings"], dtype=np.float32)
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            if attempt == MAX_RETRIES - 1:
                raise
            wait = 10 * (attempt + 1)
            print(f"  retry {attempt+1}/{MAX_RETRIES} after {wait}s: {e}")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def main() -> None:
    print("Stage 5: Generating embeddings...")
    conn = sqlite3.connect(DB_PATH)

    pending = conn.execute("""
        SELECT s.id, s.standard_text
        FROM standards s
        LEFT JOIN embeddings e ON e.standard_id = s.id
        WHERE e.standard_id IS NULL
    """).fetchall()

    if not pending:
        total = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        print(f"  All {total} standards already embedded.")
        conn.close()
        return

    print(f"  Embedding {len(pending)} standards in batches of {BATCH_SIZE}...")

    with httpx.Client() as client:
        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i : i + BATCH_SIZE]
            ids   = [r[0] for r in batch]
            texts = [r[1] for r in batch]

            vecs = embed_texts(texts, client)
            dims = vecs.shape[1]

            with conn:
                conn.executemany(
                    """INSERT OR REPLACE INTO embeddings
                       (standard_id, model, vector, dimensions)
                       VALUES (?,?,?,?)""",
                    [
                        (sid, EMBED_MODEL, vecs[j].tobytes(), dims)
                        for j, sid in enumerate(ids)
                    ],
                )

            done = min(i + BATCH_SIZE, len(pending))
            print(f"  [{done}/{len(pending)}] dim={dims}")

    total = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    conn.close()
    print(f"  Done. {total} embeddings stored.")


if __name__ == "__main__":
    main()
