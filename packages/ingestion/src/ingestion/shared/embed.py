"""Stage 5: Generate embeddings for all standards via Ollama nomic-embed-text."""
import sqlite3
import struct

import httpx

from shared.config import DB_PATH, OLLAMA_BASE_URL, EMBED_MODEL

BATCH_SIZE = 20


def embed_texts(texts: list[str], client: httpx.Client) -> list[list[float]]:
    resp = client.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"]


def pack_vector(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def main() -> None:
    print("Stage 5: Generating embeddings...")
    conn = sqlite3.connect(DB_PATH)

    pending = conn.execute("""
        SELECT s.id, s.description
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
            ids = [r[0] for r in batch]
            texts = [r[1] for r in batch]

            vecs = embed_texts(texts, client)
            dim = len(vecs[0])

            with conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO embeddings (standard_id, model, vector) VALUES (?,?,?)",
                    [(sid, EMBED_MODEL, pack_vector(vec)) for sid, vec in zip(ids, vecs)],
                )

            done = min(i + BATCH_SIZE, len(pending))
            print(f"  [{done}/{len(pending)}] dim={dim}")

    total = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
    conn.close()
    print(f"  Done. {total} embeddings stored.")


if __name__ == "__main__":
    main()
