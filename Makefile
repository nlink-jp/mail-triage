PROJECT := mail-triage

.PHONY: test lint build clean

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/

format:
	uv run ruff check --fix src/ tests/
	uv run ruff format src/ tests/

build:
	uv build --out-dir dist/

clean:
	rm -rf dist/ .pytest_cache/ .coverage htmlcov/
