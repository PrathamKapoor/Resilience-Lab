# ResilienceLab — development & research automation
PYTHON ?= python

.PHONY: install install-dev test lint typecheck format check ci smoke benchmark reproduce-paper clean

install:
	$(PYTHON) -m pip install -e .

install-dev:
	$(PYTHON) -m pip install -e ".[dev,parquet]"

test:
	$(PYTHON) -m pytest

test-cov:
	$(PYTHON) -m pytest --cov=resiliencelab --cov-report=term-missing

lint:
	$(PYTHON) -m ruff check resiliencelab tests

format:
	$(PYTHON) -m ruff format resiliencelab tests

typecheck:
	$(PYTHON) -m mypy resiliencelab

check: lint typecheck test

smoke:
	resiliencelab benchmark RL-BENCH-003 --repetitions 3

ci: check
	@echo "CI pipeline complete"

benchmark:
	resiliencelab benchmark RL-BENCH-003

reproduce-paper:
	resiliencelab reproduce --all --store ./results

clean:
	@rm -rf .pytest_cache .mypy_cache .ruff_cache build dist *.egg-info
	@find resiliencelab -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true