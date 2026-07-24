"""Langflow HTTP 클라이언트 (Stage1 chat).

Flow ID·Prompt/Model 노드 ID가 없으면 503. mock 없음.
"""

from __future__ import annotations

import logging

import httpx

from app.core.config import settings
from app.core.exceptions import Stage1LangflowServiceUnavailableError

logger = logging.getLogger(__name__)


class LangflowClient:
    async def run_stage1_chat(
        self,
        *,
        message: str,
        context: str,
        temperature: float,
    ) -> str:
        if not settings.LANGFLOW_STAGE1_CHAT_FLOW_ID.strip():
            raise Stage1LangflowServiceUnavailableError()
        return await self._run_stage1_http(
            message=message,
            context=context,
            temperature=temperature,
        )

    async def _run_stage1_http(
        self,
        *,
        message: str,
        context: str,
        temperature: float,
    ) -> str:
        prompt_node_id = settings.LANGFLOW_STAGE1_PROMPT_NODE_ID.strip()
        model_node_id = settings.LANGFLOW_STAGE1_MODEL_NODE_ID.strip()
        if not prompt_node_id or not model_node_id:
            raise Stage1LangflowServiceUnavailableError()

        payload = {
            "input_value": message,
            "input_type": "chat",
            "output_type": "chat",
            "tweaks": {
                prompt_node_id: {"context": context},
                model_node_id: {"temperature": temperature},
            },
        }
        url = (
            f"{settings.LANGFLOW_URL.rstrip('/')}"
            f"/api/v1/run/{settings.LANGFLOW_STAGE1_CHAT_FLOW_ID}"
        )
        headers = {"Content-Type": "application/json"}
        if settings.LANGFLOW_API_KEY:
            headers["x-api-key"] = settings.LANGFLOW_API_KEY

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.exception("stage1 langflow HTTP failed")
            raise Stage1LangflowServiceUnavailableError() from exc

        text = self._parse_chat_output(data)
        if not text:
            raise Stage1LangflowServiceUnavailableError()
        return text

    def _parse_chat_output(self, data: dict) -> str:
        texts: list[str] = []
        for run_output in data.get("outputs", []):
            for inner in run_output.get("outputs", []):
                results = inner.get("results", {})
                message = results.get("message") or results.get("text")
                if isinstance(message, dict) and message.get("text"):
                    texts.append(str(message["text"]))
                elif isinstance(message, str) and message.strip():
                    texts.append(message)
        return texts[-1].strip() if texts else ""
