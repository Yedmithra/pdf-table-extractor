import io
import re
import pdfplumber
import pandas as pd
import pytesseract
from pdf2image import convert_from_bytes
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def is_scanned_pdf(pdf_bytes: bytes) -> bool:
    """Check if PDF is scanned (no extractable text)."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:3]:
            text = page.extract_text() or ""
            if len(text.strip()) > 50:
                return False
    return True


def extract_tables_digital(pdf_bytes: bytes) -> list[dict]:
    """Extract tables from a digital PDF using pdfplumber."""
    results = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables({
                "vertical_strategy": "lines_strict",
                "horizontal_strategy": "lines_strict",
                "snap_tolerance": 3,
                "join_tolerance": 3,
                "edge_min_length": 3,
                "min_words_vertical": 3,
                "min_words_horizontal": 1,
            })
            
            # Fallback strategy if no tables found
            if not tables:
                tables = page.extract_tables()

            for tbl_idx, table in enumerate(tables):
                if not table or len(table) < 2:
                    continue
                cleaned = []
                for row in table:
                    cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
                    cleaned.append(cleaned_row)
                
                if not any(any(cell for cell in row) for row in cleaned):
                    continue

                results.append({
                    "page": page_num,
                    "table_index": tbl_idx + 1,
                    "data": cleaned,
                    "method": "digital"
                })
    return results


def extract_tables_ocr(pdf_bytes: bytes, lang: str = "fra+eng") -> list[dict]:
    """Extract tables from a scanned PDF using OCR + heuristics."""
    results = []
    images = convert_from_bytes(pdf_bytes, dpi=300)

    for page_num, image in enumerate(images, 1):
        # Get detailed OCR data with bounding boxes
        data = pytesseract.image_to_data(
            image, lang=lang, output_type=pytesseract.Output.DATAFRAME
        )
        data = data[data.conf > 30].copy()
        data.dropna(subset=["text"], inplace=True)
        data = data[data["text"].str.strip() != ""]

        if data.empty:
            continue

        # Cluster words into rows based on top position
        data["top_group"] = (data["top"] // 15) * 15
        rows_grouped = data.groupby("top_group")

        table_rows = []
        for _, row_data in rows_grouped:
            row_data = row_data.sort_values("left")
            words = row_data["text"].tolist()
            table_rows.append(words)

        if len(table_rows) < 2:
            continue

        # Normalize row lengths
        max_cols = max(len(r) for r in table_rows)
        normalized = []
        for row in table_rows:
            padded = row + [""] * (max_cols - len(row))
            normalized.append(padded)

        results.append({
            "page": page_num,
            "table_index": 1,
            "data": normalized,
            "method": "ocr"
        })
    return results


def tables_to_excel(tables: list[dict]) -> bytes:
    """Convert extracted tables to a formatted Excel workbook."""
    wb = Workbook()
    wb.remove(wb.active)

    # Colors
    HEADER_COLOR = "1B4F72"
    ALT_COLOR = "EBF5FB"
    BORDER_COLOR = "AED6F1"

    thin = Side(style="thin", color=BORDER_COLOR)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # Summary sheet
    summary_ws = wb.create_sheet("Résumé", 0)
    summary_ws.sheet_view.showGridLines = False
    
    title_cell = summary_ws["B2"]
    title_cell.value = "📊 Rapport d'extraction de tableaux"
    title_cell.font = Font(name="Calibri", bold=True, size=16, color="1B4F72")
    
    summary_ws["B3"].value = f"Nombre de tableaux extraits : {len(tables)}"
    summary_ws["B3"].font = Font(name="Calibri", size=11, color="555555")
    
    summary_ws["B4"].value = "Méthode : " + (tables[0]["method"].upper() if tables else "N/A")
    summary_ws["B4"].font = Font(name="Calibri", size=11, color="555555")

    summary_ws.column_dimensions["A"].width = 3
    summary_ws.column_dimensions["B"].width = 45

    headers = ["Onglet", "Page PDF", "N° Tableau", "Lignes", "Colonnes", "Méthode"]
    summary_ws.append([])
    summary_ws.append([""] + headers)
    
    hrow = summary_ws.max_row
    for col_idx, h in enumerate(headers, 2):
        cell = summary_ws.cell(row=hrow, column=col_idx, value=h)
        cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", start_color=HEADER_COLOR)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border

    for i, tbl in enumerate(tables):
        sheet_name = f"Page{tbl['page']}_T{tbl['table_index']}"
        df = pd.DataFrame(tbl["data"])
        summary_ws.append([
            "", sheet_name, tbl["page"], tbl["table_index"],
            len(df), len(df.columns), tbl["method"].upper()
        ])
        drow = summary_ws.max_row
        fill = PatternFill("solid", start_color=ALT_COLOR) if i % 2 == 0 else PatternFill("solid", start_color="FFFFFF")
        for col_idx in range(2, 8):
            cell = summary_ws.cell(row=drow, column=col_idx)
            cell.fill = fill
            cell.font = Font(name="Calibri", size=10)
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = border

    # Data sheets
    for tbl in tables:
        sheet_name = f"Page{tbl['page']}_T{tbl['table_index']}"
        ws = wb.create_sheet(sheet_name)
        ws.sheet_view.showGridLines = False

        data = tbl["data"]
        if not data:
            continue

        # Write header row
        header_row = data[0]
        for col_idx, val in enumerate(header_row, 1):
            cell = ws.cell(row=1, column=col_idx, value=val)
            cell.font = Font(name="Calibri", bold=True, color="FFFFFF", size=10)
            cell.fill = PatternFill("solid", start_color=HEADER_COLOR)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = border

        # Write data rows
        for row_idx, row in enumerate(data[1:], 2):
            fill_color = ALT_COLOR if row_idx % 2 == 0 else "FFFFFF"
            for col_idx, val in enumerate(row, 1):
                cleaned_val = _try_cast(val)
                cell = ws.cell(row=row_idx, column=col_idx, value=cleaned_val)
                cell.font = Font(name="Calibri", size=10)
                cell.fill = PatternFill("solid", start_color=fill_color)
                cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                cell.border = border

        # Auto-adjust column widths
        for col_idx in range(1, len(header_row) + 1):
            col_letter = get_column_letter(col_idx)
            max_len = 0
            for row in ws.iter_rows(min_col=col_idx, max_col=col_idx):
                for cell in row:
                    try:
                        max_len = max(max_len, len(str(cell.value or "")))
                    except Exception:
                        pass
            ws.column_dimensions[col_letter].width = min(max(max_len + 4, 12), 50)

        ws.row_dimensions[1].height = 28
        ws.freeze_panes = "A2"

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def _try_cast(value: str):
    """Try to convert string to int or float."""
    v = str(value).strip()
    # Remove common number formatting
    cleaned = re.sub(r"[€$£\s]", "", v).replace(",", ".").replace(" ", "")
    try:
        if "." in cleaned:
            return float(cleaned)
        return int(cleaned)
    except Exception:
        return v


def process_pdf(pdf_bytes: bytes, force_ocr: bool = False, lang: str = "fra+eng") -> tuple[list[dict], bytes]:
    """Main entry: detect PDF type, extract tables, return Excel bytes."""
    if force_ocr or is_scanned_pdf(pdf_bytes):
        tables = extract_tables_ocr(pdf_bytes, lang=lang)
        if not tables:
            tables = extract_tables_digital(pdf_bytes)
    else:
        tables = extract_tables_digital(pdf_bytes)
        if not tables:
            tables = extract_tables_ocr(pdf_bytes, lang=lang)

    excel_bytes = tables_to_excel(tables)
    return tables, excel_bytes
