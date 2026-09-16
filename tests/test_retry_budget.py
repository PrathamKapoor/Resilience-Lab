"""Tests for RetryBudget and budget-wired retry behavior."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from resiliencelab.core.builders import build_retry
from resiliencelab.core.schema import BackoffSpec, RetrySpec
from resiliencelab.resilience.errors import CallFailure, RetryBudgetExhausted
from resiliencelab.resilience.policy import PolicyExecutor, ResiliencePolicy
from resiliencelab.resilience.retry import Retry, RetryBudget, RetryConfig


class TestRetryBudget:
    def test_acquire_within_budget(self) -> None:
        budget = RetryBudget(max_retries=3, window=10.0)
        assert budget.acquire() is True
        assert budget.acquire() is True
        assert budget.acquire() is True
        assert budget.remaining == 0

    def test_acquire_exhausts_budget(self) -> None:
        budget = RetryBudget(max_retries=2, window=10.0)
        assert budget.acquire() is True
        assert budget.acquire() is True
        assert budget.acquire() is False
        assert budget.remaining == 0

    def test_remaining_decrements(self) -> None:
        budget = RetryBudget(max_retries=5, window=10.0)
        assert budget.remaining == 5
        budget.acquire()
        assert budget.remaining == 4
        budget.acquire()
        assert budget.remaining == 3

    def test_zero_budget_rejects_all(self) -> None:
        budget = RetryBudget(max_retries=0, window=10.0)
        assert budget.acquire() is False
        assert budget.remaining == 0

    def test_invalid_max_retries(self) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            RetryBudget(max_retries=-1, window=10.0)

    def test_invalid_window(self) -> None:
        with pytest.raises(ValueError, match="window"):
            RetryBudget(max_retries=3, window=0.0)


class TestRetryWithBudget:
    def test_should_retry_without_budget(self) -> None:
        retry = Retry(RetryConfig(max_attempts=3))
        failure = CallFailure("fail", status=503, retryable=True)
        assert retry.should_retry(1, failure) is True
        assert retry.should_retry(2, failure) is True
        assert retry.should_retry(3, failure) is False

    def test_should_retry_with_budget(self) -> None:
        budget = RetryBudget(max_retries=2, window=10.0)
        retry = Retry(RetryConfig(max_attempts=5), budget=budget)
        failure = CallFailure("fail", status=503, retryable=True)
        assert retry.should_retry(1, failure) is True
        assert retry.should_retry(2, failure) is True
        # Budget exhausted
        with pytest.raises(RetryBudgetExhausted):
            retry.should_retry(3, failure)

    def test_budget_exhausted_is_not_retryable(self) -> None:
        exc = RetryBudgetExhausted()
        assert exc.retryable is False


class TestRetryBudgetSchema:
    def test_default_no_budget(self) -> None:
        spec = RetrySpec()
        assert spec.budget_max_retries is None
        assert spec.budget_window == 10.0

    def test_budget_configured(self) -> None:
        spec = RetrySpec(budget_max_retries=5, budget_window=30.0)
        assert spec.budget_max_retries == 5
        assert spec.budget_window == 30.0

    def test_zero_budget_valid(self) -> None:
        spec = RetrySpec(budget_max_retries=0)
        assert spec.budget_max_retries == 0


class TestBuildRetryWithBudget:
    def test_builds_with_budget(self) -> None:
        retry_spec = RetrySpec(budget_max_retries=3, budget_window=5.0)
        backoff_spec = BackoffSpec()
        retry = build_retry(retry_spec, backoff_spec)
        assert retry is not None
        assert retry.budget is not None
        assert retry.budget._max == 3
        assert retry.budget._window == 5.0

    def test_builds_without_budget(self) -> None:
        retry_spec = RetrySpec()
        backoff_spec = BackoffSpec()
        retry = build_retry(retry_spec, backoff_spec)
        assert retry is not None
        assert retry.budget is None

    def test_builds_none_when_disabled(self) -> None:
        retry = build_retry(None, BackoffSpec())
        assert retry is None


class TestBudgetInPolicyExecutor:
    def test_budget_limits_retries(self) -> None:
        """Budget exhaustion should prevent retry even when max_attempts allows it."""
        budget = RetryBudget(max_retries=1, window=10.0)
        retry = Retry(
            RetryConfig(max_attempts=5, retryable_statuses=frozenset({503})),
            budget=budget,
        )
        policy = ResiliencePolicy(retry=retry, name="budget_test")

        call_count = 0

        async def failing_operation() -> object:
            nonlocal call_count
            call_count += 1
            raise CallFailure("fail", status=503, retryable=True)

        executor = PolicyExecutor(policy, rng=AsyncMock())
        with pytest.raises(CallFailure):
            asyncio.run(executor.execute(failing_operation))
        # First attempt + 1 retry (budget allows 1), then budget exhaustion
        assert executor.retries == 1
        assert executor.calls == 2

    def test_no_budget_allows_all_retries(self) -> None:
        """Without budget, max_attempts controls retry count."""
        retry = Retry(
            RetryConfig(max_attempts=3, retryable_statuses=frozenset({503})),
        )
        policy = ResiliencePolicy(retry=retry, name="no_budget_test")

        call_count = 0

        async def failing_operation() -> object:
            nonlocal call_count
            call_count += 1
            raise CallFailure("fail", status=503, retryable=True)

        executor = PolicyExecutor(policy, rng=AsyncMock())
        with pytest.raises(CallFailure):
            asyncio.run(executor.execute(failing_operation))
        assert executor.retries == 2
        assert executor.calls == 3
