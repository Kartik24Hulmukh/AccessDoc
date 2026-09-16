"""Recovery-backoff + half-open probe-window tests (launch hardening).

Regression cover for: a persistently dead model (live 2026-09-16: Flash, 25 s
read timeouts) being re-probed on a fixed 30 s cadence and each probe eating a
real request's wall-clock budget.
"""
import time

from app.gateway import CircuitBreaker, ModelGateway, CANONICAL_CHAIN


def _open(b, n=3):
    for _ in range(n):
        b.record_failure()


def test_first_open_uses_base_recovery_timeout():
    b = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
    _open(b)
    assert b.state == b.OPEN
    assert b.open_cycles == 1
    assert b.recovery_delay() == 30.0


def test_recovery_delay_backs_off_exponentially_and_caps():
    b = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0,
                       max_recovery_timeout=40.0)
    b.record_failure()
    assert b.recovery_delay() == 10.0
    b._opened_at = time.monotonic() - 11
    assert b.allow() is True            # half-open probe
    b.record_failure()                  # probe failed -> re-open, cycle 2
    assert b.open_cycles == 2 and b.recovery_delay() == 20.0
    b._opened_at = time.monotonic() - 21
    assert b.allow() is True
    b.record_failure()
    assert b.open_cycles == 3 and b.recovery_delay() == 40.0
    b._opened_at = time.monotonic() - 100
    assert b.allow() is True
    b.record_failure()
    assert b.recovery_delay() == 40.0   # capped, never unbounded


def test_success_resets_backoff_immediately():
    b = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
    b.record_failure()
    b._opened_at = time.monotonic() - 11
    assert b.allow() is True
    b.record_success()
    assert b.state == b.CLOSED and b.open_cycles == 0
    b.record_failure()
    assert b.recovery_delay() == 10.0


def test_backoff_never_fabricates_failure_counts():
    b = CircuitBreaker(failure_threshold=1, recovery_timeout=1.0)
    b.record_timeout()
    snap = b.snapshot()
    assert snap["failures"] == 1 and snap["timeouts"] == 1
    assert snap["open_cycles"] == 1
    assert snap["recovery_delay"] == 1.0


def test_open_breaker_is_not_reprobed_before_backed_off_delay():
    b = CircuitBreaker(failure_threshold=1, recovery_timeout=10.0)
    b.record_failure()
    b._opened_at = time.monotonic() - 11
    assert b.allow() is True
    b.record_failure()                  # cycle 2 -> 20 s
    b._opened_at = time.monotonic() - 11
    assert b.allow() is False           # 11 s < 20 s: still ejected


def test_half_open_probe_read_window_is_clamped(monkeypatch):
    monkeypatch.delenv("GATEWAY_PROBE_TIMEOUT_SECONDS", raising=False)
    g = ModelGateway(api_key="k")
    model = CANONICAL_CHAIN[1]
    closed_window = g.read_timeout_for(model)
    assert closed_window >= 20.0        # full per-model window while healthy
    b = g.breakers[model]
    b.failure_threshold = 1
    b.record_failure()
    b._opened_at = time.monotonic() - b.recovery_delay() - 1
    assert b.allow() is True and b.state == b.HALF_OPEN
    assert g.read_timeout_for(model) == 5.0
    assert g.read_timeout_for(model, remaining=2.0) == 2.0


def test_probe_window_env_override(monkeypatch):
    monkeypatch.setenv("GATEWAY_PROBE_TIMEOUT_SECONDS", "1.5")
    g = ModelGateway(api_key="k")
    model = CANONICAL_CHAIN[1]
    b = g.breakers[model]
    b.failure_threshold = 1
    b.record_failure()
    b._opened_at = time.monotonic() - b.recovery_delay() - 1
    assert b.allow() is True
    assert g.read_timeout_for(model) == 1.5


def test_healthy_models_keep_full_window(monkeypatch):
    monkeypatch.delenv("GATEWAY_PROBE_TIMEOUT_SECONDS", raising=False)
    g = ModelGateway(api_key="k")
    for m in CANONICAL_CHAIN:
        assert g.read_timeout_for(m) >= 20.0
        assert g.breakers[m].recovery_delay() == 30.0
