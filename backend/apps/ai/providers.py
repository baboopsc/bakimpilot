"""
Pluggable LLM and embedding providers (D-022, D-023).

Configured with environment variables:
    LLM_PROVIDER=auto | mock | anthropic (default: auto = anthropic if a key is set, else mock)
    LLM_MODEL=claude-opus-5-5            (anthropic only; this is the default)
    LLM_API_KEY=...                      (or ANTHROPIC_API_KEY / an `ant auth login` profile)
    EMBEDDING_PROVIDER=mock

"mock" doesn't mean fake output. Every AI feature has a deterministic,
non-LLM implementation (extractive answers, a rule-based query parser,
template explanations). The mock provider tells the feature to use it.
The same deterministic path is the fallback when the real API is down,
so the app never breaks because an AI vendor is unavailable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The LLM couldn't produce an answer (no provider, network/API error, refusal)."""


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMProvider:
    name = "base"
    is_mock = False

    def complete(self, *, system: str, prompt: str, max_tokens: int = 4000) -> LLMResult:
        raise NotImplementedError

    def complete_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 4000) -> dict:
        raise NotImplementedError


class MockProvider(LLMProvider):
    """Signals 'use the deterministic implementation'. Never calls the network."""

    name = "mock"
    is_mock = True

    def complete(self, **kwargs) -> LLMResult:
        raise LLMUnavailable("mock provider: use the deterministic implementation")

    def complete_json(self, **kwargs) -> dict:
        raise LLMUnavailable("mock provider: use the deterministic implementation")


class AnthropicProvider(LLMProvider):
    """
    Claude through the official Anthropic SDK.

    * Adaptive thinking is always on for Claude Opus 5.5; we set effort to
      "medium" explicitly (assistant answers, not deep research).
    * Server-side refusal fallbacks are enabled (`fallbacks="default"`), so a
      request a safety classifier declines is retried on a fallback model
      inside the same call instead of failing.
    """

    name = "anthropic"
    DEFAULT_MODEL = "claude-opus-5-5"
    BETAS = ["server-side-fallback-2026-07-01"]

    def __init__(self, model: str | None = None, api_key: str | None = None, base_url: str | None = None):
        import anthropic  # imported lazily: the mock setup doesn't need the SDK at all

        kwargs = {"max_retries": 2, "timeout": 60.0}
        if api_key:
            kwargs["api_key"] = api_key  # otherwise the SDK reads ANTHROPIC_API_KEY or an `ant` profile
        if base_url:
            kwargs["base_url"] = base_url
        self._anthropic = anthropic
        self.client = anthropic.Anthropic(**kwargs)
        self.model = model or self.DEFAULT_MODEL

    def _create(self, *, system: str, prompt: str, max_tokens: int, output_config: dict):
        a = self._anthropic
        try:
            response = self.client.beta.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config=output_config,
                betas=self.BETAS,
                fallbacks="default",
            )
        except a.RateLimitError as exc:
            raise LLMUnavailable("rate limited") from exc
        except a.AuthenticationError as exc:
            raise LLMUnavailable("authentication failed: check LLM_API_KEY") from exc
        except a.BadRequestError as exc:
            log.error("LLM bad request: %s", exc.message)
            raise LLMUnavailable("bad request") from exc
        except a.APIStatusError as exc:
            raise LLMUnavailable(f"API error {exc.status_code}") from exc
        except a.APIConnectionError as exc:
            raise LLMUnavailable("network error") from exc

        if response.stop_reason == "refusal":
            raise LLMUnavailable("the model declined this request")
        if response.stop_reason == "max_tokens":
            log.warning("LLM response truncated at max_tokens (request %s)", response._request_id)
        text = "".join(b.text for b in response.content if b.type == "text")
        return LLMResult(
            text=text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    def complete(self, *, system: str, prompt: str, max_tokens: int = 4000) -> LLMResult:
        return self._create(
            system=system, prompt=prompt, max_tokens=max_tokens, output_config={"effort": "medium"}
        )

    def complete_json(self, *, system: str, prompt: str, schema: dict, max_tokens: int = 4000) -> dict:
        # Structured outputs: the API guarantees the text is JSON matching `schema`.
        result = self._create(
            system=system,
            prompt=prompt,
            max_tokens=max_tokens,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            return json.loads(result.text)
        except json.JSONDecodeError as exc:  # e.g. truncated at max_tokens
            raise LLMUnavailable("model returned invalid JSON") from exc


def resolve_provider(provider: str, api_key: str) -> str:
    """'auto' picks Claude only when there is a key, so a deploy without one just works (D-036)."""
    if provider == "auto":
        return "anthropic" if api_key else "mock"
    return provider


@lru_cache(maxsize=4)
def _build(provider: str, model: str, api_key: str, base_url: str) -> LLMProvider:
    provider = resolve_provider(provider, api_key)
    if provider == "mock":
        return MockProvider()
    if provider == "anthropic":
        try:
            return AnthropicProvider(model=model or None, api_key=api_key or None, base_url=base_url or None)
        except Exception as exc:  # e.g. no key and no `ant` profile: degrade, don't crash every AI page
            log.warning("Anthropic provider unavailable (%s); using the offline mock provider", exc)
            return MockProvider()
    raise ValueError(f"Unknown LLM_PROVIDER {provider!r} (expected 'auto', 'mock' or 'anthropic')")


def get_llm() -> LLMProvider:
    return _build(settings.LLM_PROVIDER, settings.LLM_MODEL, settings.LLM_API_KEY, settings.LLM_BASE_URL)


# --- embeddings --------------------------------------------------------------

TOKEN_RE = re.compile(r"[a-zA-Z0-9çğıöşüÇĞİÖŞÜ]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text)]


class HashingEmbedder:
    """
    Offline embedding: the "hashing trick" over words and word pairs, with
    sublinear term frequency, L2-normalised to `dim` dimensions.

    It captures *lexical* similarity (shared words), not meaning, so
    "torque" won't match "tightening force". That's enough to demo and test the
    whole RAG pipeline with no API. A semantic embedding provider plugs in
    behind the same interface (D-023).
    """

    name = "mock"

    def __init__(self, dim: int):
        self.dim = dim

    def _index(self, feature: str) -> tuple[int, float]:
        h = int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=8).digest(), "big")
        return h % self.dim, (1.0 if (h >> 63) & 1 else -1.0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            words = [w for w in tokenize(text) if len(w) > 2]
            counts: dict[str, int] = {}
            for feat in words + [f"{a}_{b}" for a, b in zip(words, words[1:], strict=False)]:
                counts[feat] = counts.get(feat, 0) + 1
            vec = [0.0] * self.dim
            for feat, n in counts.items():
                i, sign = self._index(feat)
                vec[i] += sign * (1 + math.log(n))
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


def get_embedder():
    if settings.EMBEDDING_PROVIDER == "mock":
        return HashingEmbedder(settings.EMBEDDING_DIM)
    raise ValueError(f"Unknown EMBEDDING_PROVIDER {settings.EMBEDDING_PROVIDER!r}")
