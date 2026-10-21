"""
Minimal OpenAI-compatible chat client with an automatic fallback.

Providers, tried in order:
  1. Yours, if configured:
       * OpenRouter free models -> https://openrouter.ai/api/v1
       * Groq free tier         -> https://api.groq.com/openai/v1
       * Local Ollama           -> http://localhost:11434/v1  (no key)
  2. A free, no-signup endpoint (LLM_KEYLESS_FALLBACK, on by default) so the
     app gives real online AI answers even with an empty .env.

If every provider fails the caller falls back to the offline heuristic, so a
bad AI provider never breaks a search.
"""

from __future__ import annotations

import time

import httpx

from app.config import Settings

from .errors import ProviderError

# The free keyless endpoint is shared per network and can answer with HTTP 402/429
# when its quota is used. When that happens we "cool down": stop calling it for a
# while so searches stay fast, and quietly fall back to the offline heuristic.
_COOLDOWN_UNTIL = 0.0
_SHORT_COOLDOWN = 120.0
_LONG_COOLDOWN = 900.0


def _in_cooldown() -> bool:
    return time.monotonic() < _COOLDOWN_UNTIL


def _start_cooldown(seconds: float) -> None:
    global _COOLDOWN_UNTIL
    _COOLDOWN_UNTIL = max(_COOLDOWN_UNTIL, time.monotonic() + seconds)


def _clear_cooldown() -> None:
    global _COOLDOWN_UNTIL
    _COOLDOWN_UNTIL = 0.0


class _Candidate:
    """One concrete place to send a chat-completions request."""

    __slots__ = ("name", "url", "api_key", "model")

    def __init__(self, name: str, url: str, api_key: str, model: str) -> None:
        self.name = name
        self.url = url
        self.api_key = api_key
        self.model = model


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        """Kept for backwards compatibility: is *any* AI usable?"""
        return self.settings.llm_available

    @property
    def available(self) -> bool:
        # A configured endpoint is always attempted; the shared free one backs
        # off after a quota/rate-limit failure.
        if self.settings.llm_enabled:
            return True
        return self.settings.llm_keyless_fallback and not _in_cooldown()

    def _candidates(self) -> list[_Candidate]:
        options: list[_Candidate] = []
        if self.settings.llm_enabled:
            options.append(
                _Candidate(
                    name="AI",
                    url=self.settings.llm_base_url.rstrip("/") + "/chat/completions",
                    api_key=self.settings.llm_api_key,
                    model=self.settings.llm_model,
                )
            )
        if self.settings.llm_keyless_fallback and self.settings.llm_fallback_url:
            options.append(
                _Candidate(
                    name="AI (free)",
                    url=self.settings.llm_fallback_url,
                    api_key="",
                    model=self.settings.llm_fallback_model,
                )
            )
        return options

    async def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 320,
        temperature: float = 0.2,
    ) -> str:
        # Keyless-only and cooling down: fail instantly instead of stalling.
        if (
            not self.settings.llm_enabled
            and self.settings.llm_keyless_fallback
            and _in_cooldown()
        ):
            raise ProviderError("AI", "the free AI is cooling down")

        candidates = self._candidates()
        if not candidates:
            raise ProviderError("AI", "no AI provider is configured")

        last_error: ProviderError | None = None
        for candidate in candidates:
            try:
                answer = await self._call(
                    candidate,
                    system=system,
                    user=user,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                _clear_cooldown()
                return answer
            except ProviderError as exc:
                # Try the next provider (e.g. the configured key failed) and
                # remember the most recent reason for a friendly error message.
                last_error = exc
                if not candidate.api_key:
                    # Keyless endpoint: back off so we do not stall every search.
                    if exc.status in {402, 429}:
                        _start_cooldown(_LONG_COOLDOWN)
                    else:
                        _start_cooldown(_SHORT_COOLDOWN)
                    break

        raise last_error or ProviderError("AI", "the AI provider could not be reached")

    async def _call(
        self,
        candidate: _Candidate,
        *,
        system: str,
        user: str,
        max_tokens: int,
        temperature: float,
    ) -> str:
        headers = {"Content-Type": "application/json"}
        if candidate.api_key:
            headers["Authorization"] = f"Bearer {candidate.api_key}"

        payload = {
            "model": candidate.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            async with httpx.AsyncClient(timeout=self.settings.llm_timeout_seconds) as client:
                response = await client.post(candidate.url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                candidate.name,
                f"HTTP {exc.response.status_code}",
                status=exc.response.status_code,
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(candidate.name, "the AI provider could not be reached") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(candidate.name, "the AI provider returned an unexpected response") from exc

        if not isinstance(content, str) or not content.strip():
            raise ProviderError(candidate.name, "the AI provider returned an empty answer")
        return content.strip()
