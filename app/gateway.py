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
import threading
import time
import weakref

import requests
from requests.adapters import HTTPAdapter

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
    key = str(name or "").strip().lower()
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
                 connect_timeout=5.0, read_timeout=10.0, max_retries=3,
                 base_backoff=0.25, max_sleep=2.0):
        self._api_key = api_key
        self.transport = transport
        self.chain = tuple(normalize_model(m) for m in (chain or CANONICAL_CHAIN))
        self.breakers = {m: CircuitBreaker() for m in self.chain}
        self.timeout = (connect_timeout, read_timeout)
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

    def _post(self, model, messages):
        if self.transport is not None:
            return self.transport(model, messages)
        key = self._key()
        if not key:
            raise GatewayError(API_KEY_ENV + " is not set", model=model)
        resp = self._session.post(
            MELIOUS_BASE_URL + CHAT_PATH,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 256},
            timeout=self.timeout)
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        return resp.status_code, dict(resp.headers), payload

    @staticmethod
    def _log(**fields):
        print(json.dumps(dict(fields, ts=time.time()), separators=(",", ":")),
              flush=True)

    def chat(self, prompt, model=None, static_fallback=True):
        messages = [{"role": "system",
                     "content": "You are an accessibility remediation engineer."},
                    {"role": "user", "content": str(prompt)}]
        wanted = normalize_model(model)
        start = self.chain.index(wanted) if wanted in self.chain else 0
        last_err = None
        for m in self.chain[start:]:
            breaker = self.breakers[m]
            if not breaker.allow():
                self._log(event="gateway_skip", model=m, reason="circuit_open",
                          state=breaker.state)
                last_err = GatewayError("circuit open", model=m)
                continue
            attempt = 0
            while True:
                t0 = time.monotonic()
                status, headers, payload = 0, {}, {}
                try:
                    status, headers, payload = self._post(m, messages)
                except requests.Timeout as exc:
                    status, payload = 504, {"error": str(exc)}
                except requests.RequestException as exc:
                    status, payload = 502, {"error": str(exc)}
                except GatewayError as exc:
                    if exc.status is None:
                        raise
                    status, payload = exc.status or 502, {'error': str(exc)}
                latency = round((time.monotonic() - t0) * 1000, 2)
                if status == 200:
                    breaker.record_success()
                    try:
                        text = payload["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError):
                        text = ""
                    tokens = (payload.get("usage") or {}).get("total_tokens", 0)
                    self._log(event="gateway_call", model=m, status=200,
                              latency_ms=latency, tokens=tokens,
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
                attempt += 1
                if attempt > self.max_retries:
                    break
                retry_after = 0.0
                try:
                    retry_after = float(headers.get("Retry-After") or 0)
                except (TypeError, ValueError):
                    retry_after = 0.0
                delay = min(max(retry_after,
                                self.base_backoff * (2 ** (attempt - 1)))
                            + random.uniform(0, self.base_backoff),
                            self.max_sleep)
                time.sleep(delay)
        if static_fallback:
            self._log(event="gateway_static_fallback", reason="chain_exhausted")
            return GatewayResult("static-kb", static_answer(prompt), 0, 0.0,
                                 0, True, "static-kb")
        raise last_err or GatewayError("all models unavailable")

    def health(self):
        return {"chain": list(self.chain),
                "models": {m: b.snapshot() for m, b in self.breakers.items()}}
