"""Day 1 validation: confirm Mac Mini -> Mac Studio Thunderbolt path works."""
import json
import httpx

BASE = "http://169.254.1.1:11434"

print("Testing nomic-embed-text over Thunderbolt...")
r = httpx.post(f"{BASE}/api/embed", json={
    "model": "nomic-embed-text",
    "input": "Use ratio and rate reasoning to solve real-world problems.",
}, timeout=30)
vec = r.json()["embeddings"][0]
assert len(vec) == 768, f"Expected 768, got {len(vec)}"
print(f"  OK — 768-dim vector received")

print("Testing gemma4:31b over Thunderbolt...")
r = httpx.post(f"{BASE}/api/generate", json={
    "model": "gemma4:31b-it-q8_0",
    "prompt": 'Return only valid JSON: {"status": "ok"}. No explanation.',
    "stream": False,
}, timeout=120)
raw = r.json()["response"].strip()
parsed = json.loads(raw)
assert parsed.get("status") == "ok", f"Unexpected response: {raw}"
print(f"  OK — gemma4 returned valid JSON")

print("\nMac Mini -> Mac Studio Thunderbolt: all good.")
