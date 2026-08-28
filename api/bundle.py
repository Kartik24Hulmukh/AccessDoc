"""Vercel serverless bundle handler alias.

Routes /api/bundle requests to the canonical AccessDoc handler.
Version: 0.7.0-beta.5
"""
from __future__ import annotations
from app.models import VERSION
from api.handler import handler, ADAPTER_VERSION

server_version = f"AccessDoc/{VERSION}"

__all__ = ["handler", "ADAPTER_VERSION", "server_version"]
