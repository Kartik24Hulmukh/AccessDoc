"""Resilient Melious frontier-model gateway router (production hardening).

Structural remediation for the gateway-cascade deadlock failure mode:
* per-model three-state circuit breakers (CLOSED -> OPEN -> HALF_OPEN)
* ordered zero-loss fallback chain across frontier models
* owned aiohttp connection pools and cancellable c-ares DNS
* immediate failover on HTTP 429 / 5xx; bounded retries on HTTP 408
* structured JSON telemetry per attempt (latency, tokens, circuit state)
* bearer credential resolved exclusively from $MELIOUS_API_KEY (never hardcoded)
* deterministic static-KB last-resort fallback (guaranteed zero-failure answer)
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import queue
import threading
import time
import weakref

import requests
from .gateway_transport import PooledSession, CancelledAttempt
from .gateway_budget import TokenLedger

from . import telemetry

# Cumulative client authorization ceiling for ONE chat(), including
# conservative prompt bounds and every model/retry in the fallback chain. Exhausted budget -> deterministic static-KB (never a 5xx).
DEFAULT_TOKEN_BUDGET = 6000

# Every model in the canonical chain needs a read window wider than the 15 s
# default or it times out (504) on every call and becomes dead weight in the
# chain. Live Melious benchmarks: 2026-09-15 turn-10 measured the PRIMARY at
# 0/3 because it alone inherited the 15 s default (1024-token generations ran
# past 15 s); a 60 s-window probe the same day then measured it 5/5 at
# P50 ~1.1 s / max 9.8 s. Fourth model P50 ~16.5-20 s; turn-80 p95 was 29.26 s, so its window is 35 s. Override per model with
# GATEWAY_READ_TIMEOUT_<MODEL> (non-alnum -> _, upper-case). Windows are always
# clamped to the remaining GATEWAY_BUDGET_SECONDS, so the total wall clock for
# a chat() is unchanged: a slow primary now fails over with budget to spare
# instead of burning 15 s and returning nothing.
# Turn 81: #82 set 35 s; live K3 p95 measured 29.26 s against a 30 s window (turn 80), so a
# normal K3 reply was one jitter away from a timeout. K3 is last in the chain
# and every window is clamped to the remaining budget (default 40 s), so
# widening it to 40 s adds headroom without extending total chat() wall clock.
MODEL_READ_TIMEOUTS = {"glm-5.3": 25.0, "glm-5.3-flash": 25.0, "qwen3.8-27b": 25.0, "kimi-k3": 40.0}

MELIOUS_BASE_URL = os.getenv("MELIOUS_BASE_URL", "https://api.melious.ai/v1")
CHAT_PATH = "/chat/completions"
API_KEY_ENV = "MELIOUS_API_KEY"

BILLING_MARKER = "x-accessdoc-billing-exhausted"
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


CHAIN_ENV = "GATEWAY_MODELS"


def configured_chain(env=None):
    """Operator-pinnable fallback chain.

    ``GATEWAY_MODELS="a,b,c"`` pins the chain without a code change so a
    provider catalog rotation (live Melious re-listed the canonical chain
    between 2026-09-19 sessions) is an env flip, not a release. Entries are
    alias-normalised and de-duplicated in order; an empty/blank value or a
    value with no usable entries falls back to CANONICAL_CHAIN, so a typo can
    never yield an empty chain (which would make every call a static-KB miss).
    """
    raw = os.getenv(CHAIN_ENV, "") if env is None else env
    out = []
    for part in str(raw or "").replace(";", ",").split(","):
        m = normalize_model(part)
        if m and m not in out:
            out.append(m)
    return tuple(out) if out else CANONICAL_CHAIN


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
                 half_open_max_trials=2, timeout_weight=2,
                 max_recovery_timeout=300.0, clock=None):
        # Injectable monotonic clock: lets tests drive the open/half-open
        # lifecycle deterministically instead of racing wall-clock sleeps
        # (the sleep-based test flaked on loaded macOS CI runners).
        self._clock = clock or time.monotonic
        self.failure_threshold = failure_threshold
        # A read timeout burns the whole per-model window (25-30 s) while a
        # fast 5xx costs milliseconds; weight timeouts so a slow model is
        # ejected after two windows instead of three (live 2026-09-16 bench:
        # GLM-5.3 Flash timed out 3x25 s before opening).
        self.timeout_weight = max(1, int(timeout_weight))
        self.timeouts = 0
        self.recovery_timeout = recovery_timeout
        # A model that is persistently down (live 2026-09-16: Flash, 25 s read
        # timeouts) must not be re-probed every fixed 30 s: each half-open probe
        # costs a real request a slice of its 40 s budget. Consecutive open
        # cycles back the re-probe off exponentially, capped.
        self.max_recovery_timeout = float(max_recovery_timeout)
        self.open_cycles = 0
        self.half_open_max_trials = half_open_max_trials
        self._lock = threading.Lock()
        self.state = self.CLOSED
        self.consecutive_failures = 0
        self._opened_at = 0.0
        self._trials = 0
        # Admissions carry an epoch: an older in-flight success must not erase
        # a newer 429 trip, nor impersonate a current half-open recovery probe.
        self._epoch = 0
        self.successes = 0
        self.failures = 0

    def recovery_delay(self):
        """Re-probe delay for the current open cycle (exponential, capped)."""
        cycles = max(0, self.open_cycles - 1)
        # Saturate BEFORE exponentiation. A long outage (or many concurrent
        # 429s) can exceed 1024 cycles; constructing 2**cycles first both
        # allocates an unbounded integer and overflows float conversion.
        base, cap = self.recovery_timeout, self.max_recovery_timeout
        if base <= 0:
            return 0.0
        if cap <= base or cycles >= math.log2(cap) - math.log2(base):
            return cap
        return min(math.ldexp(base, cycles), cap)

    def allow(self):
        """Compatibility predicate; production attempts use epoch tickets."""
        return self.admit() is not None

    def admit(self):
        """Return an admission epoch, or None while the circuit rejects work."""
        with self._lock:
            if self.state == self.CLOSED:
                return self._epoch
            if self.state == self.OPEN:
                if self._clock() - self._opened_at >= self.recovery_delay():
                    self.state = self.HALF_OPEN
                    self._trials = 0
                else:
                    return None
            if self.state == self.HALF_OPEN:
                if self._trials < self.half_open_max_trials:
                    self._trials += 1
                    return self._epoch
                return None
            return self._epoch

    def abandon(self, ticket):
        """Release a current recovery trial that never produced an outcome."""
        with self._lock:
            if ticket == self._epoch and self.state == self.HALF_OPEN:
                self._trials = max(0, self._trials - 1)

    def record_success(self, ticket=None):
        with self._lock:
            self.successes += 1
            if ticket is not None and ticket != self._epoch:
                return
            if self.state == self.HALF_OPEN:
                # Other probes from this recovery wave are now stale too.
                self._epoch += 1
            self.state = self.CLOSED
            self.consecutive_failures = 0
            self._trials = 0
            self.open_cycles = 0

    def _failure_locked(self, weight):
        self.consecutive_failures += weight
        if (self.state == self.HALF_OPEN or
                (self.state == self.CLOSED and
                 self.consecutive_failures >= self.failure_threshold)):
            self.state = self.OPEN
            self._opened_at = self._clock()
            self.open_cycles += 1
            self._epoch += 1

    def record_failure(self, ticket=None):
        with self._lock:
            self.failures += 1
            if ticket is not None and ticket != self._epoch:
                return
            self._failure_locked(1)

    def record_timeout(self, ticket=None):
        """A timeout is one real failure counted with extra weight toward opening."""
        with self._lock:
            self.timeouts += 1
            self.failures += 1
            if ticket is not None and ticket != self._epoch:
                return
            self._failure_locked(self.timeout_weight)

    def unhealthy(self):
        """True while the model has unresolved consecutive failures or is not CLOSED."""
        with self._lock:
            return self.state != self.CLOSED or self.consecutive_failures > 0

    def trip(self, ticket=None):
        """Record one failure and open atomically; never synthesize failures."""
        with self._lock:
            self.failures += 1
            if ticket is not None and ticket != self._epoch:
                return
            self.consecutive_failures += 1
            self.state = self.OPEN
            self._opened_at = self._clock()
            self._trials = 0
            self.open_cycles += 1
            self._epoch += 1

    def snapshot(self):
        with self._lock:
            return {"state": self.state,
                    "consecutive_failures": self.consecutive_failures,
                    "successes": self.successes, "failures": self.failures,
                    "timeouts": self.timeouts,
                    "open_cycles": self.open_cycles,
                    "recovery_delay": round(self.recovery_delay(), 3)}


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
        self.token_usage_known = True
        self.token_budget = None

    def as_dict(self):
        return {"model": self.model, "text": self.text, "tokens": self.tokens,
                "latency_ms": self.latency_ms, "attempts": self.attempts,
                "fallback": self.fallback, "token_usage_known": self.token_usage_known,
                "token_budget": self.token_budget}


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
        self.chain = tuple(normalize_model(m) for m in chain) if chain else configured_chain()
        self.breakers = {m: CircuitBreaker() for m in self.chain}
        if read_timeout is None:
            read_timeout = float(os.getenv("GATEWAY_READ_TIMEOUT_SECONDS", "15"))
        self.timeout = (connect_timeout, read_timeout)
        # Admission deadline shared by models/retries: exhausted -> static-KB.
        # The native transport owns cancellation through DNS, headers and body.
        self.budget_seconds = float(budget_seconds if budget_seconds is not None
                                    else os.getenv("GATEWAY_BUDGET_SECONDS", "40"))
        self.token_budget = int(token_budget if token_budget is not None
                                else os.getenv("GATEWAY_TOKEN_BUDGET", str(DEFAULT_TOKEN_BUDGET)))
        self.max_retries = max_retries
        self.base_backoff = base_backoff
        self.max_sleep = max_sleep
        self._session = PooledSession(self.max_response_bytes)
        self._http_context = threading.local()
        weakref.finalize(self, self._session.close)
        # Account-wide credit exhaustion (provider 402, or 429 with
        # code=insufficient_quota / type=billing_error) is NOT a per-model rate
        # limit: every model shares the same key, so probing the rest of the
        # chain only adds dead latency. Hold the whole chain for a cooldown.
        self.billing_cooldown = float(os.getenv("GATEWAY_BILLING_COOLDOWN_SECONDS", "300"))
        self._billing_until = 0.0
        self._billing_lock = threading.Lock()

    def billing_exhausted(self):
        with self._billing_lock:
            return time.monotonic() < self._billing_until

    def _hold_billing(self, model):
        with self._billing_lock:
            cool = self.billing_cooldown if self.billing_cooldown > 0 else 0.0
            self._billing_until = time.monotonic() + cool
        self._log(event="gateway_billing_exhausted", model=model,
                  cooldown_s=self.billing_cooldown)

    @staticmethod
    def is_billing_error(status, body):
        """Pure classifier for account-wide quota/credit exhaustion."""
        if status == 402:
            return True
        if status != 429 or not isinstance(body, dict):
            return False
        err = body.get("error")
        if not isinstance(err, dict):
            return False
        return (str(err.get("code") or "").lower() in {"insufficient_quota", "billing_hard_limit_reached"}
                or str(err.get("type") or "").lower() in {"billing_error", "insufficient_quota"})

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
        # A half-open probe is speculative: it must never spend a real request's
        # whole budget re-testing a model that has already been ejected. Clamp
        # probe reads to GATEWAY_PROBE_TIMEOUT_SECONDS (default 5 s).
        breaker = self.breakers.get(model) if isinstance(getattr(self, "breakers", None), dict) else None
        if breaker is not None and breaker.state == breaker.HALF_OPEN:
            try:
                probe = float(os.getenv("GATEWAY_PROBE_TIMEOUT_SECONDS", "5"))
            except ValueError:
                probe = 5.0
            if probe > 0:
                t = min(t, probe)
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
        context = getattr(self._http_context, "value", {})
        response_deadline = context.get("deadline")
        if response_deadline is None:
            response_deadline = time.monotonic() + (
                remaining if remaining is not None else self.budget_seconds)
        resp = self._session.post(
            MELIOUS_BASE_URL + CHAT_PATH,
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json",
                     "traceparent": telemetry.traceparent_header()},
            json={"model": model, "messages": messages,
                  "max_tokens": int(max_tokens or os.getenv("GATEWAY_MAX_TOKENS", "1024"))},
            stream=True,
            deadline=response_deadline,
            cancel=context.get("cancel"),
            timeout=(min(self.timeout[0], remaining) if remaining is not None else self.timeout[0],
                     self.read_timeout_for(model, remaining)))
        try:
            # Error bodies are neither needed for routing nor safe to buffer.
            # Preserve Retry-After while closing the stream in the finally block.
            if resp.status_code != 200:
                hdrs = dict(resp.headers)
                if resp.status_code == 402:
                    # Status alone identifies account-wide exhaustion. Reading
                    # an optional error body only gives a slow provider a new
                    # opportunity to hold the worker.
                    hdrs[BILLING_MARKER] = "1"
                elif resp.status_code == 429:
                    # Bounded 4 KiB peek only to tell billing exhaustion from
                    # a rate limit. It shares the success reader's decoded-byte
                    # cap and absolute deadline, including slow-drip bodies.
                    peek_bytes = self._read_bounded(
                        resp, model, response_deadline,
                        byte_limit=min(4096, self.max_response_bytes), prefix=True)
                    try:
                        peek = json.loads(peek_bytes or b"{}")
                    except (ValueError, RecursionError):
                        peek = {}
                    if self.is_billing_error(resp.status_code, peek):
                        hdrs[BILLING_MARKER] = "1"
                return resp.status_code, hdrs, {}
            body = self._read_bounded(resp, model, response_deadline)
            try:
                payload = json.loads(body)
                if not isinstance(payload, dict):
                    payload = {}
            except (ValueError, RecursionError):
                payload = {}
            return resp.status_code, dict(resp.headers), payload
        finally:
            resp.close()

    def _read_bounded(self, resp, model, response_deadline, byte_limit=None,
                      prefix=False):
        """Bounded decoded response projection.

        The native transport already enforces DNS/connect/header/body deadlines
        and bounded decompression. This projection also validates response
        adapters without reaching into private urllib3/socket internals.
        """
        limit = self.max_response_bytes if byte_limit is None else byte_limit
        body = bytearray()
        amt = min(16384, limit if prefix else limit + 1)
        for chunk in resp.iter_content(chunk_size=amt):
            if response_deadline is not None and time.monotonic() >= response_deadline:
                raise GatewayError("gateway response deadline exceeded", status=504, model=model)
            if prefix:
                body.extend(chunk[:limit - len(body)])
                if len(body) >= limit:
                    return body
            else:
                if len(body) + len(chunk) > limit:
                    raise GatewayError("gateway response exceeds decoded byte limit", status=502, model=model)
                body.extend(chunk)
        return body

    @staticmethod
    def _log(**fields):
        telemetry.log_event(fields.pop("event", "gateway"), **fields)

    def route_order(self, start=0):
        """Health-ranked fallback order: canonical chain, but models whose
        breaker is not CLOSED or that carry unresolved consecutive failures
        (e.g. a 25 s read timeout) are demoted behind healthy models so one
        slow provider never spends the shared budget ahead of a healthy one.
        The sort is stable: canonical priority is preserved within each tier,
        so routing stays deterministic. Demoted models are still tried last
        (breaker allowing), never dropped."""
        slice_ = list(self.chain[start:])
        ranked = sorted(slice_, key=lambda m: 1 if self.breakers[m].unhealthy() else 0)
        if ranked != slice_:
            self._log(event="gateway_route", reason="health_ranked",
                      canonical=slice_, order=ranked)
        return tuple(ranked)

    def hedge_delay(self):
        """Seconds before a still-pending attempt is hedged to the next model.

        Issue #86: a stalled upstream is indistinguishable from a slow (multi-
        second) generation until its read window expires, so lowering read
        windows cannot meet a <200 ms failover bar without killing healthy
        calls. Instead the next healthy model is dispatched after
        GATEWAY_HEDGE_DELAY_MS (default 100) while the first keeps running;
        the first success wins and siblings are cancelled before any further
        billable call. A negative value disables hedging (serial failover).
        """
        raw = os.getenv("GATEWAY_HEDGE_DELAY_MS", "100")
        try:
            value = float(raw)
        except ValueError:
            value = 100.0
        if value != value or value < 0:
            return None
        return value / 1000.0

    def chat(self, prompt, model=None, static_fallback=True, budget_seconds=None):
        hedge = self.hedge_delay()
        real_http = (self.transport is None and "_post" not in vars(self)
                     and getattr(type(self)._post, "__func__", type(self)._post) is ModelGateway.__dict__["_post"]
                     and bool(self._key()))
        if hedge is None or not real_http:
            # Injected transports / patched _post are deterministic in-process
            # doubles, and a missing credential must keep its explicit error
            # contract; hedging only applies to real credentialed HTTP.
            return self._chat_serial(prompt, model, static_fallback, budget_seconds)
        return self._chat_hedged(prompt, model, static_fallback, budget_seconds, hedge)

    def _chat_hedged(self, prompt, model, static_fallback, budget_seconds, hedge):
        if self.billing_exhausted():
            # Credits are account-wide: no lane can succeed, dispatch nothing.
            self._log(event="gateway_skip", model=None, reason="billing_exhausted")
            if static_fallback:
                self._log(event="gateway_static_fallback", reason="billing_exhausted")
                return GatewayResult("static-kb", static_answer(prompt), 0, 0.0,
                                     0, True, "static-kb")
            raise GatewayError("provider credits exhausted", status=402)
        budget = float(budget_seconds if budget_seconds is not None else self.budget_seconds)
        t_start = time.monotonic()
        deadline = t_start + budget
        wanted = normalize_model(model)
        start = self.chain.index(wanted) if wanted in self.chain else 0
        lanes = list(self.route_order(start))
        try:
            max_inflight = max(1, int(os.getenv("GATEWAY_HEDGE_MAX_INFLIGHT", "2")))
        except ValueError:
            max_inflight = 2
        results = queue.Queue()
        cancel = threading.Event()
        messages = [{"role": "system", "content": "You are an accessibility remediation engineer."},
                    {"role": "user", "content": str(prompt)}]
        ledger = TokenLedger(self.token_budget, messages)
        state = {"inflight": 0, "launched": 0}
        last_err = None
        token_budget_hit = False

        from . import telemetry
        parent_trace = telemetry.traceparent_header()
        threads = []
        def lane(m, tb, remaining, ready):
            telemetry.start_trace(parent_trace, model=m)
            try:
                r = self._chat_serial(prompt, m, False, remaining, order=(m,),
                                      token_budget=tb, cancel=cancel, ready=ready,
                                      absolute_deadline=deadline, ledger=ledger)
                results.put((m, r, None))
            except Exception as exc:  # routed to the dispatcher, never lost
                results.put((m, None, exc))
            finally:
                ready.set()  # skipped/failed lane must not consume a hedge timer
                telemetry.clear()

        def launch(reason):
            nonlocal token_budget_hit
            while state["launched"] < len(lanes):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or self.billing_exhausted():
                    return False
                # One shared ledger reserves prompt + completion for every
                # attempt/retry, including losing and cancelled hedge lanes.
                tb = self.token_budget
                if not ledger.can_dispatch():
                    token_budget_hit = True
                    return False
                m = lanes[state["launched"]]
                state["launched"] += 1
                state["inflight"] += 1
                ready = threading.Event()
                thread = threading.Thread(target=lane, args=(m, tb, remaining, ready),
                                          name="gateway-hedge", daemon=True)
                threads.append(thread)
                thread.start()
                # Bound the wait: a lane that cannot even open its socket
                # within the hedge window must not stall the next dispatch.
                ready.wait(max(0.0, min(hedge, deadline - time.monotonic())))
                self._log(event="gateway_dispatch", model=m, reason=reason,
                          lane=state["launched"],
                          since_start_ms=round((time.monotonic() - t_start) * 1000, 3))
                return True
            return False

        launch("primary")
        # Absolute hedge deadline anchored at the last dispatch. A relative
        # per-wait timeout drifts whenever an unrelated result wakes the
        # dispatcher, and the 150 ms default left only 50 ms of headroom for
        # thread start + connect on loaded macOS runners (213 ms measured in CI).
        next_hedge = time.monotonic() + hedge
        # Every lane shares the same absolute deadline; native transport
        # reserves cancellation drain inside that existing budget.
        grace = 0.0
        while state["inflight"]:
            remaining = deadline - time.monotonic()
            if remaining + grace <= 0:
                break
            can_hedge = (remaining > 0 and state["launched"] < len(lanes)
                         and state["inflight"] < max_inflight and ledger.can_dispatch())
            try:
                wait = (max(0.0, min(remaining, next_hedge - time.monotonic()))
                        if can_hedge else remaining + grace)
                m, r, exc = results.get(timeout=wait)
            except queue.Empty:
                if can_hedge and time.monotonic() >= next_hedge:
                    if launch("hedge"):
                        next_hedge = time.monotonic() + hedge
                continue
            state["inflight"] -= 1
            if r is not None and not r.fallback:
                cancel.set()
                self._session.cancel(cancel)
                for thread in threads:
                    thread.join(max(0.0, deadline - time.monotonic()))
                if ledger.contract_violation:
                    last_err = GatewayError("provider token authorization exceeded")
                    break
                r.attempts = ledger.snapshot()["authorized_attempts"]
                r.tokens = ledger.spent
                r.token_usage_known = ledger.snapshot()["usage_known"]
                r.token_budget = ledger.snapshot()
                self._log(event="gateway_hedge_win", model=m,
                          latency_ms=round((time.monotonic() - t_start) * 1000, 3),
                          lanes_dispatched=state["launched"])
                return r
            last_err = exc or last_err
            if state["inflight"] < max_inflight:
                if launch("failover"):
                    next_hedge = time.monotonic() + hedge
        cancel.set()
        self._session.cancel(cancel)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))
        if static_fallback:
            self._log(event="gateway_static_fallback",
                      reason="token_budget_exhausted" if token_budget_hit else
                      ("budget_exhausted" if time.monotonic() >= deadline else "chain_exhausted"))
            result = GatewayResult("static-kb", static_answer(prompt), ledger.spent, 0.0,
                                   ledger.snapshot()["authorized_attempts"], True, "static-kb")
            result.token_usage_known, result.token_budget = ledger.snapshot()["usage_known"], ledger.snapshot()
            return result
        raise last_err or GatewayError("all models unavailable")

    def _chat_serial(self, prompt, model=None, static_fallback=True, budget_seconds=None,
                     order=None, token_budget=None, cancel=None, ready=None,
                     absolute_deadline=None, ledger=None):
        tb = self.token_budget if token_budget is None else int(token_budget)
        deadline = absolute_deadline if absolute_deadline is not None else (
            time.monotonic() + float(budget_seconds if budget_seconds is not None else self.budget_seconds))
        budget_hit = False
        tokens_spent = 0
        token_budget_hit = False
        messages = [{"role": "system",
                     "content": "You are an accessibility remediation engineer."},
                    {"role": "user", "content": str(prompt)}]
        ledger = ledger if ledger is not None else TokenLedger(tb, messages)
        wanted = normalize_model(model)
        start = self.chain.index(wanted) if wanted in self.chain else 0
        last_err = None
        for m in (order if order is not None else self.route_order(start)):
            if time.monotonic() >= deadline:
                budget_hit = True
                self._log(event="gateway_budget_exhausted", model=m)
                last_err = GatewayError("gateway time budget exhausted", status=504, model=m)
                break
            if not ledger.can_dispatch():
                token_budget_hit = True
                self._log(event="gateway_token_budget_exhausted", model=m,
                          tokens_spent=tokens_spent, token_budget=tb)
                last_err = GatewayError("gateway token budget exhausted", status=429, model=m)
                break
            if self.billing_exhausted():
                self._log(event="gateway_skip", model=m, reason="billing_exhausted")
                last_err = GatewayError("provider credits exhausted", status=402, model=m)
                break
            breaker = self.breakers[m]
            attempt = 0
            while True:
                # Retries share the same budget as fallback models. Recheck
                # after backoff, before making another billable network call.
                if time.monotonic() >= deadline:
                    budget_hit = True
                    last_err = GatewayError("gateway time budget exhausted", status=504, model=m)
                    break
                if not ledger.can_dispatch():
                    token_budget_hit = True
                    last_err = GatewayError("gateway token budget exhausted", status=429, model=m)
                    break
                if cancel is not None and cancel.is_set():
                    # A hedged sibling already won: never make another billable call.
                    last_err = GatewayError("hedge cancelled", status=499, model=m)
                    break
                # Every retry is a new admission too: another request may have
                # tripped the circuit while this attempt was backing off.
                ticket = breaker.admit()
                if ticket is None:
                    self._log(event="gateway_skip", model=m, reason="circuit_open",
                              state=breaker.state)
                    last_err = GatewayError("circuit open", model=m)
                    break
                reservation = ledger.reserve(int(os.getenv("GATEWAY_MAX_TOKENS", "1024")))
                if reservation is None:
                    breaker.abandon(ticket)
                    token_budget_hit = True
                    last_err = GatewayError("gateway token budget exhausted", status=429, model=m)
                    break
                reservation_ticket, per_call = reservation
                if ready is not None:
                    # Hedge clock starts when this lane's request is in flight,
                    # not when its thread was scheduled (see _chat_hedged).
                    ready.set()
                    ready = None
                t0 = time.monotonic()
                status, headers, payload = 0, {}, {}
                try:
                    self._http_context.value = {"deadline": deadline, "cancel": cancel}
                    status, headers, payload = self._post(
                        m, messages, per_call, remaining=deadline - time.monotonic())
                except CancelledAttempt:
                    status, payload = 499, {}
                except requests.Timeout as exc:
                    status, payload = 504, {"error": str(exc)}
                except requests.RequestException as exc:
                    status, payload = 502, {"error": str(exc)}
                except GatewayError as exc:
                    if exc.status is None:
                        breaker.abandon(ticket)
                        ledger.reconcile(reservation_ticket, {})
                        raise
                    status, payload = exc.status or 502, {'error': str(exc)}
                except Exception:
                    breaker.abandon(ticket)
                    ledger.reconcile(reservation_ticket, {})
                    raise
                finally:
                    self._http_context.value = {}
                latency = round((time.monotonic() - t0) * 1000, 2)
                violation = ledger.reconcile(reservation_ticket, payload)
                # Provider JSON is untrusted, including usage on success.
                try:
                    tokens = max(0, int(((payload or {}).get("usage") or {}).get("total_tokens") or 0))
                except (TypeError, ValueError, AttributeError, OverflowError):
                    tokens = 0
                tokens_spent = ledger.spent
                if violation or ledger.contract_violation:
                    breaker.record_failure(ticket)
                    self._log(event="gateway_token_contract_violation", model=m,
                              authorized_ceiling=tb, observed_tokens=ledger.observed_tokens)
                    last_err = GatewayError("provider exceeded authorized token reservation",
                                            status=502, model=m)
                    break
                text = extract_text(payload) if status == 200 else ""
                if status == 200 and not text:
                    # Reasoning models can spend the whole completion budget on
                    # hidden thinking and return an empty answer with a 200. A
                    # 200 with no content is a failed attempt, never a success.
                    status = 502
                    payload = {"error": "empty completion"}
                if status == 200:
                    breaker.record_success(ticket)
                    self._log(event="gateway_call", model=m, status=200,
                              latency_ms=latency, tokens=tokens,
                              tokens_spent=tokens_spent,
                              circuit=breaker.state, attempt=attempt + 1)
                    result = GatewayResult(m, text, ledger.spent, latency,
                                           ledger.snapshot()["authorized_attempts"], False, m)
                    result.token_usage_known, result.token_budget = ledger.snapshot()["usage_known"], ledger.snapshot()
                    return result
                if status == 499:
                    breaker.abandon(ticket)
                    last_err = GatewayError("gateway attempt cancelled", status=499, model=m)
                    break
                if status == 402 or (headers or {}).get(BILLING_MARKER) == "1":
                    breaker.abandon(ticket)
                    self._hold_billing(m)
                    self._log(event="gateway_call", model=m, status=status,
                              latency_ms=latency, reason="billing_exhausted")
                    last_err = GatewayError("provider credits exhausted", status=402, model=m)
                    break
                transient = status == 429 or status == 408 or status >= 500
                if status == 429:
                    # Explicit rate limits atomically stop new admissions without
                    # fabricating failures or racing an unbounded retry loop.
                    breaker.trip(ticket)
                elif status == 404:
                    # The provider does not serve this model id at all (catalog
                    # rotation / typo). Re-trying it on the next two requests
                    # only buys ~0.3 s of dead latency each; eject at once and
                    # let the exponential half-open probe re-admit it if the
                    # catalog lists it again.
                    breaker.trip(ticket)
                elif status == 504:
                    # Read timeouts are weighted: they cost a full window each.
                    breaker.record_timeout(ticket)
                else:
                    breaker.record_failure(ticket)
                self._log(event="gateway_call", model=m, status=status,
                          latency_ms=latency, circuit=breaker.state,
                          attempt=attempt + 1)
                if not transient:
                    last_err = GatewayError("gateway rejected request",
                                            status=status, model=m)
                    break
                last_err = GatewayError("transient gateway failure",
                                        status=status, model=m)
                if status == 429 or status >= 500:
                    # Rate limits and server failures fail over immediately. Sleeping and
                    # retrying the same constrained model amplifies provider
                    # cascades and violates the sub-200 ms routing objective.
                    # Retry-After remains useful to operators via response headers,
                    # while the per-model breaker prevents hot-looping.
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
                if cancel is not None:
                    cancel.wait(max(0.0, delay))
                else:
                    time.sleep(max(0.0, delay))
        if static_fallback:
            self._log(event="gateway_static_fallback",
                      reason="budget_exhausted" if budget_hit else
                      ("token_budget_exhausted" if token_budget_hit else "chain_exhausted"),
                      tokens_spent=tokens_spent)
            result = GatewayResult("static-kb", static_answer(prompt), ledger.spent, 0.0,
                                   ledger.snapshot()["authorized_attempts"], True, "static-kb")
            result.token_usage_known, result.token_budget = ledger.snapshot()["usage_known"], ledger.snapshot()
            return result
        raise last_err or GatewayError("all models unavailable")

    def health(self):
        # One lock/clock sample keeps the hold flag and retry hint consistent.
        # This is passive telemetry: never probe a paid provider from readiness.
        with self._billing_lock:
            remaining = max(0.0, self._billing_until - time.monotonic())
        return {"chain": list(self.chain),
                "transport": self._session.snapshot(),
                "token_budget": self.token_budget,
                "budget_seconds": self.budget_seconds,
                "tracing": "opentelemetry" if telemetry.otel_enabled() else "w3c-traceparent",
                "billing_exhausted": remaining > 0,
                "billing_retry_after_seconds": math.ceil(remaining),
                "models": {m: b.snapshot() for m, b in self.breakers.items()}}
