"""Traffic-independent expiry using one lifecycle-managed monotonic scheduler."""
import threading
import time
import weakref


class ExpiryScheduler:
    def __init__(self):
        self.condition = threading.Condition()
        self.entries, self.thread = {}, None

    def schedule(self, store, deadline):
        key = id(store)
        with self.condition:
            if deadline is None:
                self.entries.pop(key, None)
            else:
                def collected(ref):
                    with self.condition:
                        current = self.entries.get(key)
                        if current and current[0] is ref:
                            self.entries.pop(key, None)
                            self.condition.notify_all()
                self.entries[key] = (weakref.ref(store, collected), deadline)
                if self.thread is None:
                    self.thread = threading.Thread(
                        target=self._run, name="report-expiry", daemon=True)
                    self.thread.start()
            self.condition.notify_all()

    def _run(self):
        while True:
            with self.condition:
                if not self.entries:
                    self.thread = None
                    return
                now = time.monotonic()
                due = [key for key, (_, deadline) in self.entries.items()
                       if deadline <= now]
                if not due:
                    self.condition.wait(min(d for _, d in self.entries.values()) - now)
                    continue
                refs = [self.entries.pop(key)[0] for key in due]
            # Never hold scheduler lock while taking a store lock.
            for ref in refs:
                store = ref()
                if store is not None:
                    store._expire()
                del store
            del refs

    def wait_idle(self, timeout=1):
        with self.condition:
            thread = self.thread if not self.entries else None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)


SCHEDULER = ExpiryScheduler()