import logging
import time
import uuid
from pathlib import Path
from threading import Lock

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.extractor import process_pdf

logger = logging.getLogger(__name__)

app = FastAPI(title="PDF Table Extractor")

UPLOAD_DIR = Path("/tmp/pdf_extractor")
UPLOAD_DIR.mkdir(exist_ok=True)

FILE_TTL_SECONDS = 3600  # generated Excel files older than this are purged
MAX_UPLOAD_SIZE = 50 * 1024 * 1024
UPLOAD_CHUNK_SIZE = 1024 * 1024

RATE_LIMIT_MAX_REQUESTS = 5
RATE_LIMIT_WINDOW_SECONDS = 60
_rate_limit_lock = Lock()
_rate_limit_buckets: dict[str, list[float]] = {}


def _cleanup_old_files():
    """Delete generated Excel files past their retention window.

    Extracted tables can contain sensitive data from the source PDF;
    files are not meant to live on disk indefinitely.
    """
    cutoff = time.time() - FILE_TTL_SECONDS
    for path in UPLOAD_DIR.glob("*.xlsx"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(client_ip: str) -> None:
    """Cap requests per IP to a small window (in-memory, single-instance).

    /extract runs OCR, which is CPU/memory-expensive; without this, the
    public demo is trivially abusable for denial of service.
    """
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW_SECONDS
    with _rate_limit_lock:
        bucket = [t for t in _rate_limit_buckets.get(client_ip, []) if t >= cutoff]
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            _rate_limit_buckets[client_ip] = bucket
            raise HTTPException(
                status_code=429,
                detail="Trop de requêtes. Réessayez dans une minute.",
            )
        bucket.append(now)
        _rate_limit_buckets[client_ip] = bucket


async def _read_upload_limited(file: UploadFile, max_size: int) -> bytes:
    """Read the upload in chunks, aborting as soon as it exceeds max_size.

    Reading the whole body before checking its size lets an oversized
    upload sit fully buffered in memory first; this bounds memory use
    to roughly one chunk past the limit instead.
    """
    chunks = []
    total = 0
    while True:
        chunk = await file.read(UPLOAD_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise HTTPException(status_code=400, detail="Fichier trop grand (max 50 Mo).")
        chunks.append(chunk)
    return b"".join(chunks)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/extract")
async def extract_tables(
    request: Request,
    file: UploadFile = File(...),
    force_ocr: bool = Form(False),
    lang: str = Form("fra+eng"),
):
    _check_rate_limit(_get_client_ip(request))

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

    pdf_bytes = await _read_upload_limited(file, MAX_UPLOAD_SIZE)

    try:
        tables, excel_bytes = process_pdf(pdf_bytes, force_ocr=force_ocr, lang=lang)
    except Exception:
        logger.exception("Extraction failed for file %r", file.filename)
        raise HTTPException(
            status_code=500,
            detail="Une erreur est survenue lors de l'extraction du PDF.",
        ) from None

    if not tables:
        raise HTTPException(status_code=422, detail="Aucun tableau détecté dans ce PDF.")

    _cleanup_old_files()

    # Save Excel output
    job_id = str(uuid.uuid4())
    excel_path = UPLOAD_DIR / f"{job_id}.xlsx"
    excel_path.write_bytes(excel_bytes)

    # Summary
    summary = {
        "job_id": job_id,
        "filename": file.filename,
        "tables_found": len(tables),
        "method": tables[0]["method"] if tables else "unknown",
        "pages": list({t["page"] for t in tables}),
        "details": [
            {
                "sheet": f"Page{t['page']}_T{t['table_index']}",
                "page": t["page"],
                "rows": len(t["data"]),
                "cols": len(t["data"][0]) if t["data"] else 0,
            }
            for t in tables
        ],
    }

    return JSONResponse(content=summary)


@app.get("/download/{job_id}")
async def download(job_id: str):
    # Sanitize
    if not job_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="ID invalide.")
    excel_path = UPLOAD_DIR / f"{job_id}.xlsx"
    if not excel_path.exists():
        raise HTTPException(status_code=404, detail="Fichier non trouvé ou expiré.")
    return FileResponse(
        path=str(excel_path),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="tableaux_extraits.xlsx",
    )


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
