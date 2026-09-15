"""Resilient Melious frontier-model gateway router (production hardening).

Structural remediation for the gateway-cascade deadlock failure mode:
* per-model three-state circuit breakers (CLOSED -> OPEN -> HALF_OPEN)
* ordered zero-loss fallback chain across frontier models
* dedicated connection pooling (requests.Session + HTTPAdapter)
* bounded jittered retries honouring Retry-After on HTTP 429 / 5xx / timeout
* structured JSON telemetry per attempt (latency, tokens, circuit state)
* bearer credential resolved exclusively from $MELIOUS_API_KEY (never hardcoded)
* deterministic static-KB last-resort fallback (guaranteed zero-failure answer)
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
import weakref

import requests
from requests.adapters import HTTPAdapter

from . import telemetry

# Cumulative token ceiling for ONE chat() across every model/retry in the
# fallback chain. Exhausted budget -> deterministic static-KB (never a 5xx).
DEFAULT_TOKEN_BUDGET = 6000

# Slow reasoning models need a longer read window than the 15 s default or
# they time out (504) on every call and become dead weight in the chain.
# Live Melious benchmark: kimi-k3 P50 ~16.5 s. Override per model with
# GATEWAY_READ_TIMEOUT_<MODEL> (non-alnum -> _, upper-case).
MODEL_READ_TIMEOUTS = {"glm-5.3-flash": 25.0, "qwen3.8-27b": 25.0, "kimi-k3": 30.0}

MELIOUS_BASE_URL = os.getenv("MELIOUS_BASE_URL", "https://api.melious.ai/v1")
CHAT_PATH = "/chat/completions"
API_KEY_ENV = "MELIOUS_API_KEY"

CANONICAL_CHAIN = ("glm-5.3", "glm-5.3-flash", "qwen3.8-27b", "kimi-k3")
_ALIASES = {
    "glm5.3": "glm-5.3",
    "glm-5-3": "glm-5.3",
    "glm-flash": "glm-5.3-flash",
    "glm-5.3-flash": "glm-5.3-flash",
    "kimi-k3": "kimi-k3",
    "kimi-k3-2026": "kimi-k3",
    "kimi": "kimi-k3",
    "qwen-3.8-27b": "qwen3.8-27b",
    "qwen3.8-27b": "qwen3.8-27b",
    "qwen-38-27b": "qwen3.8-27b",
    "qwen-27b": "qwen3.8-27b",
}


def normalize_model(name):
    """Map vendor aliases onto canonical Melious model identifiers."""
    key = re.sub(r"[\s_]+", "-", str(name or "").strip().lower())
    return _ALIASES.get(key, key)


class GatewayError(Exception):
    """Raised when the gateway cannot serve a request at all."""

    def __init__(self, message, status=None, model=None):
        super().__init__(message)
        self.status = status
        self.model = model


class CircuitBreaker:
    """Thread-safe 3-state breaker: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""

    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"

    def __init__(self, failure_threshold=3, recovery_timeout=30.0,
                 half_open_max_trials=2):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_trials = half_open_max_trials
        self._lock = threading.Lock()
        self.state = self.CLOSED
        self.consecutive_failures = 0
        self._opened_at = 0.0
        self._trials = 0
        self.successes = 0
        self.failures = 0

    def allow(self):
        with self._lock:
            if self.state == self.CLOSED:
                return True
            if self.state == self.OPEN:
                if time.monotonic() - self._opened_at >= self.recovery_timeout:
                    self.state = self.HALF_OPEN
                    self._trials = 0
                else:
                    return False
            if self.state == self.HALF_OPEN:
                if self._trials < self.half_open_max_trials:
                    self._trials += 1
                    return True
                return False
            return True

    def record_success(self):
        with self._lock:
            self.state = self.CLOSED
            self.consecutive_failures = 0
            self._trials = 0
            self.successes += 1

    def record_failure(self):
        with self._lock:
            self.failures += 1
            self.consecutive_failures += 1
            if self.state == self.HALF_OPEN:
                self.state = self.OPEN
                self._opened_at = time.monotonic()
            elif self.state == self.CLOSED and                     self.consecutive_failures >= self.failure_threshold:
                self.state = self.OPEN
                self._opened_at = time.monotonic()

    def snapshot(self):
        with self._lock:
            return {"state": self.state,
                    "consecutive_failures": self.consecutive_failures,
                    "successes": self.successes, "failures": self.failures}


_STATIC_KB = (
    ("1.1.1", "WCAG 1.1.1 Non-text Content: provide a text alternative for every "
              "non-text control (alt attribute or aria-label) conveying the same "
              "purpose; decorative images get alt=''."),
    ("1.4.3", "WCAG 1.4.3 Contrast (Minimum): ensure body text reaches a 4.5:1 "
              "contrast ratio (3:1 for large text)."),
    ("2.4.7", "WCAG 2.4.7 Focus Visible: keep a visible keyboard focus indicator on "
              "all interactive elements."),
    ("4.1.2", "WCAG 4.1.2 Name, Role, Value: expose name/role/state for every "
              "custom control via ARIA or native semantics."),
)


def extract_text(payload):
    """Robustly pull assistant text from an OpenAI-compatible completion.
    Handles string content, multi-part content lists and reasoning-only replies."""
    try:
        msg = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content
                          if isinstance(p, dict) and p.get("type", "text") == "text"
                          and isinstance(p.get("text"), str))
    text = (content or "").strip() if isinstance(content, str) else ""
    if not text:
        text = (msg.get("reasoning_content") or "").strip() if isinstance(msg.get("reasoning_content"), str) else ""
    return text


def static_answer(prompt):
    """Deterministic offline knowledge-base answer (last-resort fallback)."""
    text = str(prompt or "").lower()
    for tag, answer in _STATIC_KB:
        if tag in text:
            return answer
    return ("Static KB fallback: audit the reported violations against WCAG 2.2 "
            "success criteria, prioritise critical/serious impacts, and record "
            "remediation provenance in the evidence receipt.")


class GatewayResult:
    def __init__(self, model, text, tokens, latency_ms, attempts, fallback,
                 telemetry):
        self.model = model
        self.text = text
        self.tokens = tokens
        self.latency_ms = latency_ms
        self.attempts = attempts
        self.fallback = fallback
        self.telemetry = telemetry

    def as_dict(self):
        return {"model": self.model, "text": self.text, "tokens": self.tokens,
                "latency_ms": self.latency_ms, "attempts": self.attempts,
                "fallback": self.fallback}


class ModelGateway:
    """Circuit-breaking, pooling, fallback-routing Melious chat client."""

    def __init__(self, api_key=None, transport=None, chain=None,
                 connect_timeout=5.0, read_timeout=None, max_retries=3,
                 base_backoff=0.25, max_sleep=2.0, budget_seconds=None,
                 token_budget=None, max_response_bytes=None):
        self.max_response_bytes = int(max_response_bytes if max_response_bytes is not None
                                      else os.getenv("GATEWAY_MAX_RESPONSE_BYTES", "1048576"))
        if self.max_response_bytes <= 0:
            raise ValueError("GATEWAY_MAX_RESPONSE_BYTES must be positive")
        self._api_key = api_key
        self.transport = transport
        self.chain = tuple(normalize_model(m) for m in (chain or CANONICAL_CHAIN))
        self.breakers = {m: CircuitBreaker() for m in self.chain}
        if read_timeout is None:
            read_timeout = float(os.getenv("GATEWAY_READ_TIMEOUT_SECONDS", "15"))
        self.timeout = (connect_timeout, read_timeout)
        # Admission deadline shared by models/retries: exhausted -> static-KB.
        # Requests connect/read inactivity timeouts are NOT strict cancellation
        # of DNS, connection+read duration, or a slow-drip response body.
        self.budget_seconds = float(budget_seconds if budget_seconds is not None
                                    else os.getenv("GATEWAY_BUDGET_SECONDS", "40"))
        self.token_budget = int(token_budget if token_budget is not None
                                else os.getenv("GATEWAY_TOKEN_BUDGET", str(DEFAULT_TOKEN_BUDGET)))
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_sleep = max_sleep
        self._session = requests.Session()
        adapter = HTTPAdapter(pool_connections=25, pool_maxsize=100)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        weakref.finalize(self, self._session.close)

    def _key(self):
        return self._api_key or os.getenv(API_KEY_ENV, "")

    def read_timeout_for(self, model, remaining=None):
        """Per-model read window, clamped to the remaining wall-clock budget."""
        env = os.getenv("GATEWAY_READ_TIMEOUT_" + re.sub(r"[^A-Za-z0-9]", "_", model).upper())
        try:
            t = float(env) if env else MODEL_READ_TIMEOUTS.get(model, self.timeout[1])
        except ValueError:
            t = self.timeout[1]
        t = max(t, self.timeout[1]) if env is None else t
        if remaining is not None:
            t = min(t, remaining)
        return t

    def _post(self, model, messages, max_tokens=None, remaining=None):
        if self.transport is not None:
            return self.transport(model, messages)
        key = self._key()
        if not key:
            raise GatewayError(API_KEY_ENV + " is not set", model=model)
        if remaining is not None and remaining <= 0:
            raise GatewayError("gateway time budget exhausted", status=504, model=model)
        response_deadline = time.monotonic() + remaining if remaining is not None else None
        resp = self._session.post(
            MELIOUS_BASE_URL + CHAT_PATH,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json",
                     "traceparent": telemetry.traceparent_header()},
            json={"model": model, "messages": messages,
                  "max_tokens": int(max_tokens or os.getenv("GATEWAY_MAX_TOKENS", "1024"))},
            stream=True,
            timeout=(min(self.timeout[0], remaining) if remaining is not None else self.timeout[0],
                     self.read_timeout_for(model, remaining)))
        try:
            # Error bodies are neither needed for routing nor safe to buffer.
            # Preserve Retry-After while closing the stream in the finally block.
            if resp.status_code != 200:
                return resp.status_code, dict(resp.headers), {}
            body = bytearray()
            for chunk in resp.iter_content(chunk_size=min(16384, self.max_response_bytes + 1)):
                if response_deadline is not None and time.monotonic() >= response_deadline:
                    raise GatewayError("gateway response deadline exceeded", status=504, model=model)
                # iter_content yields decoded bytes: also bounds gzip expansion.
                if len(body) + len(chunk) > self.max_response_bytes:
                    raise GatewayError("gateway response exceeds decoded byte limit", status=502, model=model)
                body.extend(chunk)
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    payload = {}
            except (ValueError, RecursionError):
                payload = {}
            return resp.status_code, dict(resp.headers), payload
        finally:
            resp.close()

    @staticmethod
    def _log(**fields):
        telemetry.log_event(fields.pop("event", "gateway"), **fields)

    def chat(self, prompt, model=None, static_fallback=True, budget_seconds=None):
        deadline = time.monotonic() + float(budget_seconds if budget_seconds is not None else self.budget_seconds)
        budget_hit = False
        tokens_spent = 0
        token_budget_hit = False
        messages = [{"role": "system",
                     "content": "You are an accessibility remediation engineer."},
                    {"role": "user", "content": str(prompt)}]
        wanted = normalize_model(model)
        start = self.chain.index(wanted) if wanted in self.chain else 0
        last_err = None
        for m in self.chain[start:]:
            if time.monotonic() >= deadline:
                budget_hit = True
                self._log(event="gateway_budget_exhausted", model=m)
                last_err = GatewayError("gateway time budget exhausted", status=504, model=m)
                break
            if tokens_spent >= self.token_budget:
                token_budget_hit = True
                self._log(event="gateway_token_budget_exhausted", model=m,
                          tokens_spent=tokens_spent, token_budget=self.token_budget)
                last_err = GatewayError("gateway token budget exhausted", status=429, model=m)
                break
            breaker = self.breakers[m]
            if not breaker.allow():
                self._log(event="gateway_skip", model=m, reason="circuit_open",
                          state=breaker.state)
                last_err = GatewayError("circuit open", model=m)
                continue
            attempt = 0
            while True:
                # Retries share the same budget as fallback models. Recheck
                # after backoff, before making another billable network call.
                if time.monotonic() >= deadline:
                    budget_hit = True
                    last_err = GatewayError("gateway time budget exhausted", status=504, model=m)
                    break
                if tokens_spent >= self.token_budget:
                    token_budget_hit = True
                    last_err = GatewayError("gateway token budget exhausted", status=429, model=m)
                    break
                t0 = time.monotonic()
                status, headers, payload = 0, {}, {}
                try:
                    per_call = min(int(os.getenv("GATEWAY_MAX_TOKENS", "1024")),
                                   self.token_budget - tokens_spent)
                    status, headers, payload = self._post(
                        m, messages, per_call, remaining=deadline - time.monotonic())
                except requests.Timeout as exc:
                    status, payload = 504, {"error": str(exc)}
                except requests.RequestException as exc:
                    status, payload = 502, {"error": str(exc)}
                except GatewayError as exc:
                    if exc.status is None:
                        raise
                    status, payload = exc.status or 502, {'error': str(exc)}
                latency = round((time.monotonic() - t0) * 1000, 2)
                # Provider JSON is untrusted, including usage on success.
                try:
                    tokens = max(0, int(((payload or {}).get("usage") or {}).get("total_tokens") or 0))
                except (TypeError, ValueError, AttributeError, OverflowError):
                    tokens = 0
                tokens_spent += tokens
                text = extract_text(payload) if status == 200 else ""
                if status == 200 and not text:
                    # Reasoning models can spend the whole completion budget on
                    # hidden thinking and return an empty answer with a 200. A
                    # 200 with no content is a failed attempt, never a success.
                    status = 502
                    payload = {"error": "empty completion"}
                if status == 200:
                    breaker.record_success()
                    self._log(event="gateway_call", model=m, status=200,
                              latency_ms=latency, tokens=tokens,
                              tokens_spent=tokens_spent,
                              circuit=breaker.state, attempt=attempt + 1)
                    return GatewayResult(m, text, tokens, latency,
                                         attempt + 1, False, m)
                transient = status == 429 or status == 408 or status >= 500
                breaker.record_failure()
                self._log(event="gateway_call", model=m, status=status,
                          latency_ms=latency, circuit=breaker.state,
                          attempt=attempt + 1)
                if not transient:
                    last_err = GatewayError("gateway rejected request",
                                            status=status, model=m)
                    break
                last_err = GatewayError("transient gateway failure",
                                        status=status, model=m)
                if status == 504:
                    # A timeout already cost a full read window; retrying the
                    # same model would burn the budget. Fail over immediately.
                    break
                attempt += 1
                if attempt > self.max_retries:
                    break
                if time.monotonic() >= deadline:
                    budget_hit = True
                    break
                retry_after = 0.0
                try:
                    retry_after = float(headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    retry_after = 0.0
                delay = min(deadline - time.monotonic(), max(retry_after,
                                self.base_backoff * (2 ** (attempt - 1)))
                            + random.uniform(0, self.base_backoff),
                            self.max_sleep)
                time.sleep(max(0.0, delay))
        if static_fallback:
            self._log(event="gateway_static_fallback",
                      reason="budget_exhausted" if budget_hit else
                      ("token_budget_exhausted" if token_budget_hit else "chain_exhausted"),
                      tokens_spent=tokens_spent)
            return GatewayResult("static-kb", static_answer(prompt), 0, 0.0,
                                 0, True, "static-kb")
        raise last_err or GatewayError("all models unavailable")

    def health(self):
        return {"chain": list(self.chain),
                "token_budget": self.token_budget,
                "budget_seconds": self.budget_seconds,
                "tracing": "opentelemetry" if telemetry.otel_enabled() else "w3c-traceparent",
                "models": {m: b.snapshot() for m, b in self.breakers.items()}}
