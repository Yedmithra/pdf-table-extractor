VENV := venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.PHONY: help venv install system-deps run dev clean distclean

help:
	@echo "Cibles disponibles :"
	@echo "  make system-deps  - installe tesseract-ocr, tesseract-ocr-fra, poppler-utils (sudo apt)"
	@echo "  make venv         - cree l'environnement virtuel Python"
	@echo "  make install      - cree le venv et installe les dependances Python"
	@echo "  make run          - lance le serveur (production, sans reload)"
	@echo "  make dev          - lance le serveur avec rechargement automatique"
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

run: install
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000

dev: install
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

distclean: clean
	rm -rf $(VENV)
