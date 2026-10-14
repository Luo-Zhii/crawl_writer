PY := .venv/bin/python
PIP := uv pip install --python .venv/bin/python

.PHONY: help setup dev-api dev-web test lint fmt build clean

help:
	@echo "setup    - create venv, install backend + frontend deps"
	@echo "dev-api  - run FastAPI on :8000 (reload)"
	@echo "dev-web  - run Vite dev server on :5173"
	@echo "test     - run backend tests"
	@echo "lint     - ruff check + tsc typecheck"
	@echo "fmt      - ruff format"
	@echo "build    - build frontend"

setup:
	uv venv .venv --python 3.13
	$(PIP) -e './backend[dev]'
	cd frontend && npm install

# Both dev servers are long-running; run them in two terminals.
dev-api:
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000

dev-web:
	cd frontend && npm run dev

test:
	cd backend && ../$(PY) -m pytest -q

lint:
	.venv/bin/ruff check backend
	cd frontend && npm run lint

fmt:
	.venv/bin/ruff format backend
	.venv/bin/ruff check --fix backend

build:
	cd frontend && npm run build

clean:
	rm -rf frontend/dist backend/.pytest_cache .ruff_cache
	find backend -name __pycache__ -type d -exec rm -rf {} +
