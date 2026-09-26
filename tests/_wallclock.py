"""Deterministic wall-clock shifting for reproducibility tests.

Replaces real ``time.sleep`` waits (which only crossed a 1-3 s boundary and
cost CI wall time) with a patched clock that jumps to a fixed far-future
instant. Every wall-clock source an artifact could leak through --
``time.time``, ``time.localtime``, ``time.gmtime`` and ``datetime.datetime.now``
/ ``utcnow`` -- is moved, so a byte-identical result proves no wall-clock value
enters artifact bytes, across decades instead of seconds.
"""
import contextlib
import datetime as _dt
import time as _time
from unittest.mock import patch

# 2100-01-01T00:00:00Z: far from any real run, still inside the ZIP date range.
FAR_FUTURE_EPOCH = 4102444800.0

_real_localtime = _time.localtime
_real_gmtime = _time.gmtime
_RealDateTime = _dt.datetime


class _ShiftedDateTime(_RealDateTime):
    _epoch = FAR_FUTURE_EPOCH

    @classmethod
    def now(cls, tz=None):
        return _RealDateTime.fromtimestamp(cls._epoch, tz)

    @classmethod
    def utcnow(cls):
        return _RealDateTime.fromtimestamp(cls._epoch, _dt.timezone.utc).replace(tzinfo=None)

    @classmethod
    def today(cls):
        return _RealDateTime.fromtimestamp(cls._epoch)


@contextlib.contextmanager
def shifted_wall_clock(epoch=FAR_FUTURE_EPOCH):
    """Pin every wall-clock source to ``epoch`` for the duration of the block."""
    _ShiftedDateTime._epoch = epoch
    with patch("time.time", return_value=epoch), \
         patch("time.localtime", side_effect=lambda s=None: _real_localtime(epoch if s is None else s)), \
         patch("time.gmtime", side_effect=lambda s=None: _real_gmtime(epoch if s is None else s)), \
         patch("datetime.datetime", _ShiftedDateTime):
        yield epoch
