# Diagrammes UML — PDF Table Extractor

Diagrammes établis à partir du code (`app/main.py`, `app/extractor.py`, `Dockerfile`, `render.yaml`). Format Mermaid. L'application n'a ni base de données ni comptes utilisateurs : l'état se limite aux fichiers Excel temporaires et à un compteur de débit en mémoire.

> **Projet en cours de développement.** Ces diagrammes décrivent l'état du code au 17 novembre 2026. Le projet n'est pas terminé et continuera d'évoluer pour être amélioré : les diagrammes, comme le README, pourront donc changer au fil des versions.

## 1. Cas d'utilisation

```mermaid
flowchart LR
    U([Utilisateur anonyme])
    subgraph PDF Table Extractor
        UC1[Ouvrir la page d'upload]
        UC2[Envoyer un PDF à extraire]
        UC3[Forcer l'OCR / choisir la langue]
        UC4[Télécharger le classeur Excel]
    end
    U --> UC1 & UC2 & UC4
    UC2 -. extend .-> UC3
```

## 2. Composants (modules et fonctions)

```mermaid
classDiagram
    class main {
        <<module app.main>>
        UPLOAD_DIR = /tmp/pdf_extractor
        FILE_TTL_SECONDS = 3600
        MAX_UPLOAD_SIZE = 50 Mo
        RATE_LIMIT = 5 req / 60 s par IP
        -_rate_limit_buckets : dict~ip, list~float~~
        +GET / index()
        +POST /extract extract_tables(file, force_ocr, lang)
        +GET /download/job_id download()
        -_check_rate_limit(ip)
        -_get_client_ip(request)
        -_read_upload_limited(file, max_size)
        -_cleanup_old_files()
    }
    class extractor {
        <<module app.extractor>>
        MAX_OCR_PAGES = 30
        +process_pdf(pdf_bytes, force_ocr, lang) (tables, excel_bytes)
        +is_scanned_pdf(pdf_bytes) bool
        +extract_tables_digital(pdf_bytes) list~Table~
        +extract_tables_ocr(pdf_bytes, lang) list~Table~
        +tables_to_excel(tables) bytes
        -_deskew(image)
        -_cluster_rows_by_overlap(data)
        -_sanitize_for_excel(value)
        -_try_cast(value)
    }
    class Table {
        <<dict>>
        page : int
        table_index : int
        data : list~list~str~~
        method : "digital" | "ocr"
    }
    main ..> extractor : process_pdf()
    extractor ..> Table : produit
    extractor ..> pdfplumber : PDF natif
    extractor ..> pdf2image_pytesseract : PDF scanné (300 dpi)
    extractor ..> openpyxl : classeur
```

Le classeur contient une feuille « Résumé » en tête, puis une feuille `Page{n}_T{i}` par tableau. `_sanitize_for_excel` neutralise les cellules qui commencent comme une formule.

## 3. Activité : choix de la méthode d'extraction

```mermaid
flowchart TD
    A[process_pdf] --> B{force_ocr<br/>ou is_scanned_pdf ?}
    B -- "oui (moins de 50 caractères<br/>de texte sur les 3 premières pages)" --> C[extract_tables_ocr<br/>deskew + Tesseract + regroupement des lignes]
    C --> D{tableaux trouvés ?}
    D -- non --> E[extract_tables_digital]
    B -- non --> F[extract_tables_digital<br/>lines_strict, puis stratégie par défaut]
    F --> G{tableaux trouvés ?}
    G -- non --> H[extract_tables_ocr]
    D -- oui --> X[tables_to_excel]
    E --> X
    G -- oui --> X
    H --> X
```

## 4. Séquence : extraction puis téléchargement

```mermaid
sequenceDiagram
    actor U as Utilisateur
    participant API as app.main
    participant EX as app.extractor
    participant FS as /tmp/pdf_extractor

    U->>API: POST /extract (file, force_ocr, lang)
    API->>API: _check_rate_limit(IP)
    alt plus de 5 requêtes en 60 s
        API-->>U: 429
    end
    API->>API: extension .pdf ? sinon 400
    API->>API: _read_upload_limited (lecture par blocs de 1 Mo, 400 au-delà de 50 Mo)
    API->>EX: process_pdf(pdf_bytes, force_ocr, lang)
    alt exception
        API-->>U: 500 (message générique, détail en log)
    end
    EX-->>API: tables, excel_bytes
    alt aucun tableau
        API-->>U: 422
    end
    API->>FS: _cleanup_old_files() (xlsx de plus d'une heure)
    API->>FS: écrit {job_id}.xlsx (UUID4)
    API-->>U: 200 {job_id, tables_found, method, pages, details}
    U->>API: GET /download/{job_id}
    API->>API: job_id alphanumérique (hors tirets) ? sinon 400
    API->>FS: lit {job_id}.xlsx
    alt fichier absent ou purgé
        API-->>U: 404
    else
        API-->>U: tableaux_extraits.xlsx
    end
```

## 5. Déploiement

```mermaid
flowchart LR
    Browser[Navigateur] -->|HTTPS| Render
    subgraph Render [Render : service web, plan free]
        subgraph Container [Conteneur Docker]
            Uvicorn[uvicorn app.main:app :8000] --> Tmp[(/tmp/pdf_extractor)]
            Uvicorn --> Tess[Tesseract + Poppler]
        end
    end
```

Le limiteur de débit et les fichiers générés sont locaux à l'instance : le schéma suppose une seule instance.
