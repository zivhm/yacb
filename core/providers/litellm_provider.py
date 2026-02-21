"""LiteLLM provider implementation."""

import json
import os
from typing import Any

import litellm
from litellm import acompletion
from loguru import logger

from core.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from core.providers.registry import find_by_model, find_by_name, normalize_model_name


class LiteLLMProvider(LLMProvider):
    """LLM provider using LiteLLM for multi-provider support."""

    def __init__(
        self,
        api_key: str | None = None,
        api_base: str | None = None,
        default_model: str = "anthropic/claude-sonnet-4-20250514",
        extra_headers: dict[str, str] | None = None,
        provider_name: str | None = None,
        fallback_models: list[str] | None = None,
        fallback_max_attempts: int = 2,
        provider_api_keys: dict[str, str] | None = None,
    ):
        super().__init__(api_key, api_base)
        self.default_model = normalize_model_name(default_model)
        self.extra_headers = extra_headers or {}
        self._provider_name = provider_name
        self.fallback_models = [normalize_model_name(m) for m in (fallback_models or [])]
        self.fallback_max_attempts = max(1, fallback_max_attempts)

        if api_key:
            self._setup_env(api_key, api_base, self.default_model)
        self._setup_known_provider_envs(provider_api_keys)

        if api_base:
            litellm.api_base = api_base

        litellm.suppress_debug_info = True
        litellm.drop_params = True

    def _setup_env(self, api_key: str, api_base: str | None, model: str) -> None:
        spec = find_by_model(model)
        if self._provider_name:
            spec = find_by_name(self._provider_name) or spec
        if spec:
            os.environ.setdefault(spec.env_key, api_key)

    def _setup_known_provider_envs(self, provider_api_keys: dict[str, str] | None) -> None:
        """Seed known provider keys so cross-provider fallbacks can work."""
        if not provider_api_keys:
            return
        for name, api_key in provider_api_keys.items():
            if not api_key:
                continue
            spec = find_by_name(name)
            if spec:
                os.environ.setdefault(spec.env_key, api_key)

    def _resolve_model(self, model: str) -> str:
        normalized = normalize_model_name(model)
        spec = find_by_model(normalized)
        if spec and spec.strip_model_prefix:
            provider_prefix = f"{spec.name}/"
            if normalized.lower().startswith(provider_prefix):
                normalized = normalized[len(provider_prefix):]
        if spec and spec.litellm_prefix:
            if not any(normalized.startswith(s) for s in spec.skip_prefixes):
                normalized = f"{spec.litellm_prefix}/{normalized}"
        return normalized

    def _build_model_candidates(self, model: str | None) -> list[str]:
        """Return deduped model candidates in try order."""
        requested = self._resolve_model(model or self.default_model)
        default = self._resolve_model(self.default_model)

        candidates = [requested]
        candidates.extend(self._resolve_model(m) for m in self.fallback_models)
        if default != requested:
            candidates.append(default)

        deduped: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            if item in seen:
                continue
            seen.add(item)
            deduped.append(item)
            if len(deduped) >= self.fallback_max_attempts:
                break
        return deduped

    @staticmethod
    def _is_retryable_error(err: Exception) -> bool:
        """Retry only transient errors (timeouts/rate limits/server failures)."""
        message = str(err).lower()

        # Non-retryable first
        non_retryable_markers = (
            "invalid api key",
            "authentication",
            "unauthorized",
            "forbidden",
            "invalid request",
            "bad request",
            "context length",
            "unsupported model",
            "not found",
        )
        if any(marker in message for marker in non_retryable_markers):
            return False

        status = getattr(err, "status_code", None)
        if status is None:
            status = getattr(err, "status", None)
        try:
            status_int = int(status) if status is not None else None
        except Exception:
            status_int = None

        if status_int in {408, 409, 425, 429}:
            return True
        if status_int is not None and 500 <= status_int < 600:
            return True
        if status_int is not None:
            return False

        retryable_markers = (
            "timeout",
            "timed out",
            "rate limit",
            "too many requests",
            "temporar",
            "overloaded",
            "connection reset",
            "network error",
            "service unavailable",
            "internal server error",
        )
        return any(marker in message for marker in retryable_markers)

    def _build_request_kwargs(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        candidates = self._build_model_candidates(model)
        last_error: Exception | None = None

        for idx, candidate in enumerate(candidates):
            kwargs = self._build_request_kwargs(
                model=candidate,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            try:
                response = await acompletion(**kwargs)
                if idx > 0:
                    logger.warning(f"LLM fallback succeeded using model '{candidate}'")
                return self._parse_response(response)
            except Exception as e:
                last_error = e
                retryable = self._is_retryable_error(e)
                has_more = idx < len(candidates) - 1
                if not has_more or not retryable:
                    return LLMResponse(content=f"Error calling LLM: {e}", finish_reason="error")
                logger.warning(
                    f"LLM call failed on '{candidate}' ({e}); trying fallback model"
                )

        return LLMResponse(
            content=f"Error calling LLM: {last_error or 'unknown error'}",
            finish_reason="error",
        )

    def _parse_response(self, response: Any) -> LLMResponse:
        usage = {}
        if hasattr(response, "usage") and response.usage:
            usage = {
                "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
                "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
            }

        choices = getattr(response, "choices", None) or []
        if not choices:
            logger.warning("LiteLLM response had no choices; returning empty content")
            return LLMResponse(content="", finish_reason="stop", usage=usage)

        choice = choices[0]
        message = getattr(choice, "message", None)
        content: str | None = None
        finish_reason = getattr(choice, "finish_reason", None) or "stop"

        tool_calls = []
        if message is not None:
            content = self._coerce_content(getattr(message, "content", None))
            raw_tool_calls = getattr(message, "tool_calls", None) or []
            for tc in raw_tool_calls:
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", "")
                if not name:
                    continue
                args = getattr(fn, "arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {"raw": args}
                tc_id = getattr(tc, "id", f"tool-{len(tool_calls) + 1}")
                tool_calls.append(ToolCallRequest(id=tc_id, name=name, arguments=args))
        else:
            content = self._coerce_content(getattr(choice, "text", None))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    @staticmethod
    def _coerce_content(content: Any) -> str | None:
        """Normalize provider-specific content payloads into plain text."""
        if content is None:
            return None
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, str):
                    parts.append(part)
                    continue
                if isinstance(part, dict):
                    text = part.get("text") or part.get("content")
                    if isinstance(text, str):
                        parts.append(text)
            joined = "".join(parts).strip()
            return joined or None
        if isinstance(content, dict):
            text = content.get("text") or content.get("content")
            if isinstance(text, str):
                return text
        return str(content)

    def get_default_model(self) -> str:
        return self.default_model
