"""Common exceptions raised across the resilience layer."""

from __future__ import annotations


class ResilienceError(Exception):
    """Base class for all resilience-layer errors."""


class CallFailure(ResilienceError):
    """A dependent call failed and may or may not be retryable."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = True,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.cause = cause


class CircuitOpenError(CallFailure):
    def __init__(self, message: str = "circuit breaker is open") -> None:
        super().__init__(message, retryable=False)


class ConcurrencyLimitExceeded(CallFailure):
    def __init__(self, message: str = "concurrency limit exceeded") -> None:
        super().__init__(message, retryable=False)


class RetryBudgetExhausted(CallFailure):
    def __init__(self, message: str = "retry budget exhausted") -> None:
        super().__init__(message, retryable=False)


class DeadlineExceeded(CallFailure):
    def __init__(self, message: str = "request deadline exceeded") -> None:
        super().__init__(message, retryable=False)
