PYTHON ?= python3
NPM ?= npm
COMPOSE ?= docker compose

.PHONY: install install-backend install-frontend dev-backend dev-frontend test lint build docker-build docker-up docker-down smoke

install: install-backend install-frontend

install-backend:
	$(PYTHON) -m pip install -r backend/requirements-dev.txt

install-frontend:
	cd frontend && $(NPM) ci

dev-backend:
	PYTHONPATH=backend $(PYTHON) -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000

dev-frontend:
	cd frontend && $(NPM) run dev -- --host 127.0.0.1 --port 5173

test:
	PYTHONPATH=backend $(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m ruff check backend tests pipelines
	cd frontend && $(NPM) run lint

build:
	cd frontend && $(NPM) run build

docker-build:
	$(COMPOSE) build

docker-up:
	$(COMPOSE) up --build -d

docker-down:
	$(COMPOSE) down -v

smoke:
	PYTHONPATH=backend $(PYTHON) -m pipelines.jobs.run_pipeline --force
