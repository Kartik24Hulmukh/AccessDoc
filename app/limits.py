"""Bounded input limits for the public HTTP API and internal processing.

Every value is a hard ceiling. Inputs at or below these limits are accepted;
anything above is rejected with a 413 (HTTP) or ValueError (internal) before
expensive work begins. The goal is to prevent resource exhaustion from hostile
or accidentally-large payloads while leaving generous headroom for real audits.
"""
MAX_HTTP_BODY_BYTES = 2 * 1024 * 1024          # 2 MiB total request body
MAX_VIOLATIONS = 10_000                        # axe-core violations array
MAX_TOTAL_NODES = 100_000                      # sum of nodes across violations
MAX_NODES_PER_VIOLATION = 5_000                # nodes in a single violation
MAX_STRING_CHARS = 10_000                      # any single string field
MAX_MANUAL_FINDINGS = 5_000                    # manual findings entries
MAX_HISTORY_RECEIPTS = 50                      # receipt_history chain length
MAX_HISTORY_RECEIPT_BYTES = 1024 * 1024        # 1 MiB per prior receipt
