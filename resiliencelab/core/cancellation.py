"""Cooperative cancellation mechanism for experiment execution.

The CancellationToken provides a lightweight, infrastructure-independent way to
signal cancellation to running experiments. It works in both local mode (no
PostgreSQL/Redis) and server mode (worker polls DB, refreshes token).

Cancellation semantics:
    - CANCEL_REQUESTED: A request has been persisted, worker may not have stopped yet.
    - CANCELLED: The experiment cooperatively stopped and the run was finalized.
    - COMPLETED: The experiment naturally completed despite any previous request.

Race semantics (atomic terminal-state race):
    - If completion wins the terminal-state race, the run is COMPLETED.
    - If cancellation wins before completion commits, the run is CANCELLED.
    - Terminal states are immutable.

Scientific semantics:
    - cancelled != failed
    - cancelled != completed
    - cancellation != worker retry
    - cancellation != scientific repetition
    - partial repetitions are never silently treated as complete
"""

from __future__ import annotations

import threading


class CancelledError(Exception):
    """Raised when cooperative cancellation is detected at a checkpoint.

    This is NOT an unexpected failure. The worker maps this to CANCELLED status
    with appropriate metadata. It should never appear as an unexplained worker
    failure in logs or results.
    """


class CancellationToken:
    """Lightweight cooperative cancellation token.

    Thread-safe. Can be shared between async tasks and synchronous workers.
    The token is checked at meaningful boundaries:
        - Before experiment start
        - Between repetitions
        - Between workload batches/iterations
        - During long simulation operations

    The token does NOT kill processes or use signals. The runner cooperatively
    observes the token and stops future work at the next checkpoint.
    """

    def __init__(self) -> None:
        self._cancelled = threading.Event()
        self._reason: str = ""

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def reason(self) -> str:
        return self._reason

    def request(self, reason: str = "") -> None:
        """Request cancellation. Idempotent — multiple calls are safe.

        The first non-empty reason is preserved.
        """
        if not self._cancelled.is_set():
            self._reason = reason
        self._cancelled.set()

    def raise_if_cancelled(self) -> None:
        """Raise CancelledError if cancellation was requested.

        Call this at checkpoints. Cheap to check (threading.Event).
        """
        if self._cancelled.is_set():
            raise CancelledError(
                f"experiment cancelled: {self._reason}" if self._reason else "experiment cancelled"
            )
