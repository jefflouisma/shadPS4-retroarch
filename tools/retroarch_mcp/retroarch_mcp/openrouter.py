from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx


@dataclass
class OpenRouterResult:
    passed: bool
    reason: str
    raw_content: str
    parsed_json: Optional[Dict[str, Any]] = None


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    candidates = [text]
    fenced = re.findall(r"```(?:json)?\n(.*?)```", text, flags=re.DOTALL)
    candidates.extend(fenced)

    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None

    return None


def _data_url_for_image(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "google/gemini-3-flash-preview",
        timeout_seconds: float = 90.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout = timeout_seconds

    def validate_image(
        self,
        *,
        prompt: str,
        image_path: Path,
        model: Optional[str] = None,
    ) -> OpenRouterResult:
        resolved_model = model or self._default_model
        data_url = _data_url_for_image(image_path)

        payload = {
            "model": resolved_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "temperature": 0.2,
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        response = httpx.post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()

        content = ""
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
        parsed = _extract_json(content)

        if parsed and isinstance(parsed.get("pass"), bool):
            passed = parsed.get("pass", False)
            reason = str(parsed.get("reason", ""))
        else:
            passed = False
            reason = "Model response did not contain required JSON payload."

        return OpenRouterResult(
            passed=passed,
            reason=reason,
            raw_content=content,
            parsed_json=parsed,
        )
