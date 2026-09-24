import threading
from uuid import uuid4
from .storage import Store


class Jobs:
    """One local computation at a time; status/cancellation durable in the registry."""
    def __init__(self, store):
        self.store = store
        self.worker = None
        self.lock = threading.Lock()
        for job in store.list("job"):
            events = store.events(job["id"])
            if not events or events[-1]["action"] in {"running", "progress", "cancel_requested"}:
                store.event(job["id"], "interrupted", {"reason": "Previous application process ended; resume downloads from checkpoints"})

    def submit(self, label, function):
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("A job is already running; wait or cancel it")
            key = self.store.put("job", {"nonce": uuid4().hex, "label": label})
            self.store.event(key, "running", {})
            def cancelled():
                return any(e["action"] == "cancel_requested" for e in self.store.events(key))
            def progress(done, total):
                self.store.event(key, "progress", {"done": done, "total": total})
            def work():
                try:
                    result = function(cancelled, progress)
                    self.store.event(key, "completed", {"artifact_id": result})
                except InterruptedError:
                    self.store.event(key, "cancelled", {})
                except Exception as exc:
                    from .provider import ProviderError
                    reason = str(exc)[:500] if isinstance(exc, (ValueError, ProviderError)) else "Job failed; no completed result"
                    status = "cancelled" if isinstance(exc, ProviderError) and exc.kind == "cancelled" else "failed"
                    self.store.event(key, status, {"reason": reason})
            self.worker = threading.Thread(target=work, daemon=True)
            self.worker.start()
            return key

    def cancel(self, key):
        self.store.event(key, "cancel_requested", {})
