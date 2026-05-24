"""Inference proxy with a hard 120s read timeout (SC-008).

Routes to the correct upstream API based on hardware type:
- CPU  → HuggingFace TGI at ``/generate``  (``{"inputs": prompt}``)
- GPU  → vLLM OpenAI-compat at ``/v1/chat/completions``

Both paths present an OpenAI-style ``choices[0].message.content`` response to
the caller so the UI/API contract stays uniform.
"""
from __future__ import annotations

import time

import httpx

from . import metrics_recorder

INFERENCE_READ_TIMEOUT_SECONDS = 120


_TIMEOUT = httpx.Timeout(
    connect=10.0,
    read=INFERENCE_READ_TIMEOUT_SECONDS,
    write=10.0,
    pool=5.0,
)


class InferenceProxyError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def forward(
    *,
    endpoint_url: str,
    body: dict,
    hardware_type: str = "cpu",
    model_id: str | None = None,
    deployment_id: str | None = None,
    user_id: str | None = None,
) -> dict:
    """Forward an OpenAI-style chat payload to the deployed inference endpoint."""
    labels = (
        deployment_id is not None
        and user_id is not None
    )
    started = time.perf_counter()
    try:
        if hardware_type == "gpu":
            result = await _forward_vllm(
                endpoint_url=endpoint_url, body=body, model_id=model_id or "default"
            )
        else:
            result = await _forward_tgi(endpoint_url=endpoint_url, body=body)
    except (InferenceProxyError, httpx.ReadTimeout, httpx.RequestError):
        if labels:
            metrics_recorder.record_outcome(
                deployment_id=deployment_id,
                user_id=user_id,
                hardware_type=hardware_type,
                outcome="error",
            )
        raise

    ttft_seconds = time.perf_counter() - started
    if labels:
        token_count = _count_output_tokens(result)
        metrics_recorder.record_success(
            deployment_id=deployment_id,
            user_id=user_id,
            hardware_type=hardware_type,
            ttft_seconds=ttft_seconds,
            token_count=token_count,
        )
    return result


# ---------------------------------------------------------------------------
# CPU path — HuggingFace TGI
# ---------------------------------------------------------------------------

async def _forward_tgi(*, endpoint_url: str, body: dict) -> dict:
    url = endpoint_url.rstrip("/") + "/generate"
    prompt = _messages_to_prompt(body.get("messages", []))
    parameters: dict = {}
    if "max_tokens" in body:
        parameters["max_new_tokens"] = body["max_tokens"]
    if "temperature" in body:
        parameters["temperature"] = body["temperature"]
    if parameters.get("temperature", 1.0) == 0:
        parameters["do_sample"] = False

    tgi_payload: dict = {"inputs": prompt}
    if parameters:
        tgi_payload["parameters"] = parameters

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(url, json=tgi_payload)

    if response.status_code >= 400:
        raise InferenceProxyError(
            code="upstream_error",
            message=f"Upstream returned {response.status_code}: {response.text[:500]}",
            status_code=response.status_code,
        )

    data = response.json()
    text = data.get("generated_text")
    if not isinstance(text, str):
        raise InferenceProxyError(
            code="upstream_invalid_response",
            message="Upstream response did not include 'generated_text'.",
            status_code=502,
        )
    return _to_openai_chat_response(text)


# ---------------------------------------------------------------------------
# GPU path — vLLM OpenAI-compatible server
# ---------------------------------------------------------------------------

async def _forward_vllm(*, endpoint_url: str, body: dict, model_id: str) -> dict:
    url = endpoint_url.rstrip("/") + "/v1/chat/completions"

    messages = body.get("messages", [])
    if not messages:
        raise InferenceProxyError(
            code="invalid_request",
            message="Request must include at least one message.",
            status_code=400,
        )

    vllm_payload: dict = {
        "model": model_id,
        "messages": messages,
    }
    if "max_tokens" in body:
        vllm_payload["max_tokens"] = body["max_tokens"]
    if "temperature" in body:
        vllm_payload["temperature"] = body["temperature"]
    if "stream" in body:
        vllm_payload["stream"] = body["stream"]

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(url, json=vllm_payload)

    if response.status_code >= 400:
        raise InferenceProxyError(
            code="upstream_error",
            message=f"Upstream returned {response.status_code}: {response.text[:500]}",
            status_code=response.status_code,
        )

    return response.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _messages_to_prompt(messages: list[dict]) -> str:
    if not messages:
        raise InferenceProxyError(
            code="invalid_request",
            message="Request must include at least one message.",
            status_code=400,
        )
    parts: list[str] = []
    for msg in messages:
        role = str(msg.get("role", "user")).strip() or "user"
        content = str(msg.get("content", "")).strip()
        if not content:
            continue
        parts.append(f"{role}: {content}")
    if not parts:
        raise InferenceProxyError(
            code="invalid_request",
            message="All messages were empty.",
            status_code=400,
        )
    parts.append("assistant:")
    return "\n".join(parts)


def _to_openai_chat_response(text: str) -> dict:
    return {
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
    }


def _count_output_tokens(result: dict) -> int:
    usage = result.get("usage") or {}
    completion = usage.get("completion_tokens")
    if isinstance(completion, int) and completion > 0:
        return completion
    choices = result.get("choices") or []
    if not choices:
        return 0
    content = choices[0].get("message", {}).get("content", "")
    if not isinstance(content, str) or not content.strip():
        return 0
    return max(1, len(content.split()))


__all__ = ["forward", "InferenceProxyError", "INFERENCE_READ_TIMEOUT_SECONDS"]
