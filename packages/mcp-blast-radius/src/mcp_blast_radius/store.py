"""Where pending approvals and the lockdown live.

MemoryStore is fine for one process. For serverless or several replicas, implement the same
five methods on a shared database. `claim` must be atomic (a conditional write), because it
is what guarantees an approved call runs exactly once.
"""
import threading
import time
from typing import Protocol


class Store(Protocol):
    def put(self, request: dict) -> None: ...
    def get(self, request_id: str) -> dict | None: ...
    def claim(self, request_id: str, from_status: str, to_status: str) -> bool: ...
    def pending(self) -> list[dict]: ...
    def set_lockdown(self, until: float | None, reason: str = "") -> None: ...
    def lockdown(self) -> dict | None: ...


class MemoryStore:
    def __init__(self):
        self._requests, self._lockdown, self._lock = {}, None, threading.Lock()

    def put(self, request):
        with self._lock:
            self._requests[request["id"]] = dict(request)

    def get(self, request_id):
        with self._lock:
            request = self._requests.get(request_id)
            return dict(request) if request else None

    def claim(self, request_id, from_status, to_status):
        with self._lock:
            request = self._requests.get(request_id)
            if not request or request["status"] != from_status:
                return False
            request["status"] = to_status
            return True

    def pending(self):
        now = time.time()
        with self._lock:
            return [dict(r) for r in self._requests.values() if r["status"] == "pending" and r["expires_at"] > now]

    def set_lockdown(self, until, reason=""):
        with self._lock:
            self._lockdown = {"until": until, "reason": reason} if until else None

    def lockdown(self):
        with self._lock:
            if self._lockdown and self._lockdown["until"] > time.time():
                return dict(self._lockdown)
            return None
