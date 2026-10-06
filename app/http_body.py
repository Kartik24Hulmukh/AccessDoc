"""Shared absolute-deadline body ingestion and bounded oversized-body drain."""
import math
import os
import time

DRAIN_MAX_BYTES = 16 * 1024 * 1024


class BodyDeadlineExceeded(TimeoutError):
    """The complete upload/drain exceeded its wall-clock budget."""


class TruncatedBodyError(ValueError):
    """Declared upload length was not received; safe public transport error."""


def body_deadline():
    seconds = float(os.getenv("BODY_TIMEOUT_SECONDS", "15"))
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("BODY_TIMEOUT_SECONDS must be positive and finite")
    return time.monotonic() + seconds


def read_body(stream, connection, length, chunk_bytes, deadline, collect=True):
    """Read at most length bytes; a drip cannot reset the absolute deadline.

    Production handlers use BufferedReader.read1 so a single exact-size read
    cannot hide many underlying socket reads. Memory-backed test streams may
    expose only read; production sockets always have read1.
    """
    original_timeout = connection.gettimeout() if connection is not None else None
    read = getattr(stream, "read1", stream.read)
    remaining_bytes = length
    body = bytearray()
    try:
        while remaining_bytes > 0:
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise BodyDeadlineExceeded("Request body deadline exceeded")
            if connection is not None:
                timeout = (min(original_timeout, remaining_time)
                           if original_timeout is not None else remaining_time)
                connection.settimeout(timeout)
            try:
                chunk = read(min(remaining_bytes, chunk_bytes))
            except TimeoutError:
                # An inactivity timeout also terminates the upload. It must
                # never turn into a generic 500 or start a fresh drain.
                raise BodyDeadlineExceeded("Request body read timed out") from None
            if time.monotonic() >= deadline:
                raise BodyDeadlineExceeded("Request body deadline exceeded")
            if not chunk:
                break
            remaining_bytes -= len(chunk)
            if collect:
                body.extend(chunk)
        return bytes(body), remaining_bytes
    finally:
        if connection is not None:
            try:
                connection.settimeout(original_timeout)
            except OSError:
                pass