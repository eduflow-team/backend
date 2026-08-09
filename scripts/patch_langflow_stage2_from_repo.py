"""Replace deployed Stage2 Langflow flow graph with ai/flows/stage2-hallucination-gen.json.

Keeps the existing flow ID so backend .env LANGFLOW_STAGE2_FLOW_ID stays valid.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPO_FLOW = ROOT.parent / "ai" / "flows" / "stage2-hallucination-gen.json"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


async def main() -> int:
    _load_dotenv()
    base_url = os.environ.get("LANGFLOW_URL", "http://127.0.0.1:7860").rstrip("/")
    if "host.docker.internal" in base_url:
        base_url = base_url.replace("host.docker.internal", "127.0.0.1")
    flow_id = os.environ.get("LANGFLOW_STAGE2_FLOW_ID", "").strip()
    api_key = os.environ.get("LANGFLOW_API_KEY", "").strip()

    if not flow_id:
        print("LANGFLOW_STAGE2_FLOW_ID is empty in .env", file=sys.stderr)
        return 1
    if not REPO_FLOW.exists():
        print(f"repo flow not found: {REPO_FLOW}", file=sys.stderr)
        return 1

    repo = json.loads(REPO_FLOW.read_text(encoding="utf-8"))
    repo_data = repo.get("data")
    if not isinstance(repo_data, dict):
        print("invalid repo flow JSON: missing data", file=sys.stderr)
        return 1

    headers: dict[str, str] = {}
    if api_key:
        headers["x-api-key"] = api_key

    async with httpx.AsyncClient(timeout=120.0) as client:
        get_url = f"{base_url}/api/v1/flows/{flow_id}"
        response = await client.get(get_url, headers=headers)
        if response.status_code >= 400:
            print(f"GET flow failed: {response.status_code}\n{response.text}", file=sys.stderr)
            return 1

        current = response.json()
        cur_edges = len(current.get("data", {}).get("edges", []))
        cur_nodes = len(current.get("data", {}).get("nodes", []))
        repo_edges = len(repo_data.get("edges", []))
        repo_nodes = len(repo_data.get("nodes", []))

        payload = {
            "name": current.get("name") or "stage2",
            "description": current.get("description") or "",
            "data": repo_data,
            "is_component": current.get("is_component", False),
            "endpoint_name": current.get("endpoint_name"),
            "tags": current.get("tags", []),
        }
        patch = await client.patch(
            get_url,
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
        )
        if patch.status_code >= 400:
            print(f"PATCH flow failed: {patch.status_code}\n{patch.text}", file=sys.stderr)
            return 1

    print(f"patched flow {flow_id}")
    print(f"nodes: {cur_nodes} -> {repo_nodes}")
    print(f"edges: {cur_edges} -> {repo_edges}")
    print("next: set Ollama/OpenAI credentials in Langflow UI if needed, then run stage2_langflow_raw_probe.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
