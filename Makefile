VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.PHONY: help venv install install-dev system-deps run dev lint docker-build docker-run clean distclean

help:
	@echo "Cibles disponibles :"
	@echo "  make system-deps  - installe tesseract-ocr, tesseract-ocr-fra, poppler-utils (sudo apt)"
	@echo "  make venv         - cree l'environnement virtuel Python"
	@echo "  make install      - cree le venv et installe les dependances Python"
	@echo "  make install-dev  - installe en plus les outils de dev (ruff)"
	@echo "  make run          - lance le serveur (production, sans reload)"
	@echo "  make dev          - lance le serveur avec rechargement automatique"
	@echo "  make lint         - verifie le code avec ruff"
	@echo "  make docker-build - construit l'image Docker"
	@echo "  make docker-run   - lance l'image Docker sur le port 8000"
	@echo "  make clean        - supprime les caches Python"
	@echo "  make distclean    - supprime le venv et les caches"

system-deps:
	sudo apt install -y tesseract-ocr tesseract-ocr-fra poppler-utils

$(VENV)/bin/activate:
	python3 -m venv $(VENV)

venv: $(VENV)/bin/activate

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

run: install
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000

dev: install
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

lint: install-dev
	$(VENV)/bin/ruff check app/

docker-build:
	docker build -t pdf-table-extractor .

docker-run: docker-build
	docker run --rm -p 8000:8000 pdf-table-extractor

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

distclean: clean
	rm -rf $(VENV)
