# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projet

PDF Table Extractor : application web FastAPI qui extrait les tableaux d'un PDF (natif ou scanné) et les exporte en Excel formaté. Déployée sur Render (`render.yaml`, offre gratuite, image Docker). Interface en un seul template (`app/templates/index.html`), textes en français.

## Commandes

```bash
make system-deps   # tesseract-ocr (+ fra) et poppler-utils via apt — requis hors Docker
make install       # venv + requirements.txt   (install-dev ajoute ruff)
make dev           # uvicorn --reload sur :8000
make lint          # ruff check app/  (line-length 100, règles E F I UP)
make docker-run    # build + run de l'image sur :8000
```

Il n'y a pas de suite de tests. La CI (`.github/workflows/ci.yml`, Python 3.11) exécute `ruff check app/`, un import de fumée `python -c "from app.main import app"` et `pip-audit -r requirements.txt` : reproduire ces trois étapes avant de pousser.

## Architecture

- `app/main.py` : routes `GET /` (page), `POST /extract` (upload → traitement → identifiant de job), `GET /download/{job_id}` (fichier Excel). Garde-fous à préserver : upload lu par morceaux et plafonné (`MAX_UPLOAD_SIZE` 50 Mo), limitation de débit en mémoire par IP (5 requêtes / 60 s, IP via `_get_client_ip`), fichiers générés dans `/tmp/pdf_extractor` purgés après `FILE_TTL_SECONDS` (1 h), messages d'erreur génériques (ne pas renvoyer les exceptions au client).
- `app/extractor.py` : `process_pdf` choisit la voie selon `is_scanned_pdf` :
  - natif → `extract_tables_digital` (pdfplumber) ;
  - scanné → `extract_tables_ocr` (pdf2image + Tesseract, `MAX_OCR_PAGES` = 30) avec redressement (`_deskew`) puis regroupement des mots en lignes par recouvrement vertical (`_cluster_rows_by_overlap`, `ROW_OVERLAP_THRESHOLD`).
  - `tables_to_excel` produit le classeur multi-feuilles + feuille de résumé (openpyxl). Toute valeur écrite passe par `_sanitize_for_excel` (anti-injection de formules : préfixe pour `= + - @ \t \r`) puis `_try_cast`.
- L'état (limiteur de débit, jobs) est en mémoire du processus : un seul worker uvicorn est supposé.
