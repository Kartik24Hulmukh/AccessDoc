"""Conservative shared authorization ledger, not a provider billing guarantee."""
import threading


def prompt_token_bound(messages):
    """Byte-token upper bound plus conservative chat framing per message.

    The supported text models use byte/subword tokenization. UTF-8 bytes bound
    content and role tokens; reserve 32 framing tokens per message and 16 for
    the conversation. Provider-hidden prompts/billing cannot be audited here:
    metadata above the authorized reservation is a contract violation, not a
    successful answer. Oversized/unknown input fails closed before dispatch.
    """
    return 16 + sum(32 + len(str(m.get("role", "")).encode("utf-8"))
                    + len(str(m.get("content", "")).encode("utf-8"))
                    for m in messages)


class TokenLedger:
    def __init__(self, ceiling, messages):
        if ceiling < 1:
            raise ValueError("GATEWAY_TOKEN_BUDGET must be positive")
        self.ceiling, self.prompt_bound = ceiling, prompt_token_bound(messages)
        self._lock = threading.Lock()
        self._held, self._next = {}, 0
        self.spent, self.peak, self.usage_known = 0, 0, True
        self.contract_violation = False
        self.observed_tokens = 0

    def available(self):
        with self._lock:
            return max(0, self.ceiling - self.spent)

    def can_dispatch(self):
        return self.available() > self.prompt_bound and not self.contract_violation

    def reserve(self, completion_cap):
        with self._lock:
            available = self.ceiling - self.spent - self.prompt_bound
            if self.contract_violation or available < 1:
                return None
            completion = min(completion_cap, available)
            if completion < 1:
                return None
            reservation = self.prompt_bound + completion
            self._next += 1
            ticket = self._next
            self._held[ticket] = reservation
            self.spent += reservation
            self.peak = max(self.peak, self.spent)
            return ticket, completion

    def reconcile(self, ticket, payload):
        """Only explicit, valid total usage refunds an unused reservation.

        Failure, cancellation, empty completion, or absent/malformed usage
        cannot be assumed free. Keep the full authorization in that case.
        """
        usage = payload.get("usage") if isinstance(payload, dict) else None
        total = usage.get("total_tokens") if isinstance(usage, dict) else None
        valid = isinstance(total, int) and not isinstance(total, bool) and total > 0
        with self._lock:
            reserved = self._held.pop(ticket)
            if not valid:
                self.usage_known = False
                return False
            self.observed_tokens += total
            if total > reserved:
                self.contract_violation = True
                self.usage_known = False
                return True
            self.spent -= reserved - total
            return False

    def snapshot(self):
        with self._lock:
            return {"ceiling": self.ceiling, "prompt_bound": self.prompt_bound,
                    "authorized_attempts": self._next,
                    "committed_upper_tokens": self.spent, "peak_reserved_tokens": self.peak,
                    "usage_known": self.usage_known and not self._held, "observed_tokens": self.observed_tokens,
                    "contract_violation": self.contract_violation}