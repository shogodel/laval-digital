SHELL := /bin/bash
VENV  := venv
PYTHON := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip

.PHONY: help venv install dev lint typecheck test run backup clean

help:
	@echo "Usage:"
	@echo "  make venv       — Create virtual environment"
	@echo "  make install    — Install dependencies"
	@echo "  make dev        — Install dev dependencies (pytest, ruff, etc.)"
	@echo "  make lint       — Run ruff linter"
	@echo "  make typecheck  — Run mypy type checker"
	@echo "  make test       — Run pytest suite"
	@echo "  make run        — Start gunicorn dev server"
	@echo "  make backup     — Run backup script"
	@echo "  make clean      — Remove __pycache__ and .pyc files"

venv:
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip

install:
	$(PIP) install -r requirements.txt

dev: $(VENV)
	$(PIP) install ruff mypy pytest pytest-cov

lint:
	ruff check .

typecheck:
	mypy app.py blueprints/ core/ --ignore-missing-imports

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

run:
	$(VENV)/bin/gunicorn -w 2 --threads 4 --worker-class gthread \
		--bind 0.0.0.0:5000 --timeout 120 --graceful-timeout 30 \
		--keep-alive 5 --max-requests 10000 --max-requests-jitter 2000 \
		--reload app:app

backup:
	$(PYTHON) scripts/backup.py

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name '*.pyc' -delete
