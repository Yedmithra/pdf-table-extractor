import uuid
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app.extractor import process_pdf

app = FastAPI(title="PDF Table Extractor")

UPLOAD_DIR = Path("/tmp/pdf_extractor")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).parent / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.post("/extract")
async def extract_tables(
    file: UploadFile = File(...),
    force_ocr: bool = Form(False),
    lang: str = Form("fra+eng"),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés.")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier trop grand (max 50 Mo).")

    try:
        tables, excel_bytes = process_pdf(pdf_bytes, force_ocr=force_ocr, lang=lang)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur d'extraction : {str(e)}")

    if not tables:
        raise HTTPException(status_code=422, detail="Aucun tableau détecté dans ce PDF.")

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
