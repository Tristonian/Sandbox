"""
Mill Cert Checker — prototype (see ADR.md / NEXT-STEPS.md for the reasoning
behind every decision below; look for "TODO(ADR-xxx)" markers for the
features that are deliberately stubbed for this first working version).
"""
import base64
import json
import os
import sqlite3
from datetime import datetime

from flask import (Flask, g, redirect, render_template, request,
                    send_from_directory, url_for)
from werkzeug.utils import secure_filename

import ocr_extract

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
CROP_DIR = os.path.join(UPLOAD_DIR, "crops")
DB_PATH = os.path.join(BASE_DIR, "millcert.db")
os.makedirs(CROP_DIR, exist_ok=True)

app = Flask(__name__)


# ---------------------------------------------------------------- database

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_name TEXT NOT NULL,
            order_no TEXT, po_no TEXT, supplier TEXT, customer TEXT,
            commodity TEXT, spec TEXT, cert_no TEXT, date_of_issue TEXT,
            status TEXT NOT NULL DEFAULT 'needs_review',
            extraction_mode TEXT NOT NULL DEFAULT 'mock',
            uploaded_at TEXT NOT NULL,
            field_crops_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS line_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id),
            heat_no TEXT, size TEXT, product_no TEXT,
            quantity TEXT, weight TEXT,
            chemistry_json TEXT NOT NULL,
            results_json TEXT NOT NULL,
            overall_status TEXT NOT NULL,
            order_no TEXT,
            raw_ocr_line TEXT,
            crop_filename TEXT
        );

        CREATE TABLE IF NOT EXISTS spec_limits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spec TEXT NOT NULL,
            element TEXT NOT NULL,
            min_val REAL,
            max_val REAL,
            source TEXT,
            UNIQUE(spec, element)
        );
        """
    )
    # Seed SAE10B21 (SAE J403) — cross-confirmed values only, see ADR-002.
    seed = [
        ("SAE10B21", "C", 0.18, 0.23, "SAE J403 - confirmed 2 sources"),
        ("SAE10B21", "Mn", 0.60, 0.90, "SAE J403 - confirmed 2 sources"),
        ("SAE10B21", "P", None, 0.030, "SAE J403 - confirmed"),
        ("SAE10B21", "S", None, 0.050, "SAE J403 - 2 of 3 sources; 1 source said 0.03, verify"),
        ("SAE10B21", "B", 0.0005, 0.0030, "SAE J403 - confirmed 2 sources"),
    ]
    db.executemany(
        "INSERT OR IGNORE INTO spec_limits (spec, element, min_val, max_val, source) VALUES (?, ?, ?, ?, ?)",
        seed,
    )
    db.commit()
    db.close()


# ------------------------------------------------------------- extraction

def extract_document(file_path, original_name, crop_prefix):
    """
    Pull header fields + line-item chemistry table from an uploaded cert.

    ADR-012 superseded ADR-001's cloud-vision plan: extraction now runs on
    local Tesseract OCR (ocr_extract.py) — zero cost, zero network call,
    per Tristan's "no extra billing" requirement (2026-08-24). Falls back to
    mock data only if Tesseract genuinely isn't installed, so the pipeline
    is never fully blocked. ADR-013 added the per-field/per-row source-image
    crops saved under CROP_DIR, referenced by filename on each field/item.
    """
    try:
        result = ocr_extract.extract(file_path, crop_dir=CROP_DIR, crop_prefix=crop_prefix)
        return result, "ocr"
    except Exception as exc:  # Tesseract missing / render failure — don't block the pipeline
        app.logger.warning("OCR extraction failed for %s: %s", original_name, exc)
        result = _extract_mock(original_name)
        result["ocr_error"] = str(exc)
        return result, "mock"


def _extract_mock(original_name):
    """
    Placeholder extraction so the upload -> review -> approve pipeline is
    provably working end-to-end before real OCR is wired in. Values are
    loosely modelled on the sample POSCO cert used to design this tool —
    NOT read from the actual uploaded file. Every mock document is clearly
    labelled as such on the review screen.
    """
    return {
        "order_no": "01SA087403",
        "po_no": "261Q-N1001",
        "supplier": "HYOSUNG TNC CORPORATION",
        "customer": "NEW BEST WIRE IND. CO., LTD.",
        "commodity": "WIRE ROD(BLOOM)",
        "spec": "SAE10B21",
        "cert_no": "260206-FW01PS-0026A1-0001",
        "date_of_issue": "2026-02-11",
        "field_crops": {},
        "line_items": [
            {"heat_no": "SF00180", "size": "5.5", "product_no": "VEG0590071-0091",
             "quantity": "3", "weight": "6,016",
             "chemistry": {"C": 0.2111, "Si": 0.202, "Mn": 0.777, "P": 0.0160,
                           "S": 0.0055, "Cr": 0.139, "Ni": 0.019, "B": 0.0018,
                           "Cu": 0.024, "Mo": 0.007, "Sol-Al": 0.033}},
            {"heat_no": "SF00181", "size": "5.5", "product_no": "VEG0660011-0091",
             "quantity": "9", "weight": "18,044",
             "chemistry": {"C": 0.2100, "Si": 0.187, "Mn": 0.757, "P": 0.0122,
                           "S": 0.0044, "Cr": 0.124, "Ni": 0.016, "B": 0.0016,
                           "Cu": 0.027, "Mo": 0.002, "Sol-Al": 0.036}},
        ],
    }


def check_chemistry(spec, chemistry, db):
    """Per ADR-002: matched+in-range -> pass, matched+out-of-range -> fail,
    no matching (spec, element) row -> flag for mandatory human review."""
    limits = {
        row["element"]: (row["min_val"], row["max_val"])
        for row in db.execute("SELECT * FROM spec_limits WHERE spec = ?", (spec,)).fetchall()
    }
    results = {}
    overall = "pass"
    for element, value in chemistry.items():
        if element not in limits:
            results[element] = {"value": value, "status": "review", "min": None, "max": None}
            overall = "review" if overall != "fail" else overall
            continue
        lo, hi = limits[element]
        ok = (lo is None or value >= lo) and (hi is None or value <= hi)
        results[element] = {"value": value, "status": "pass" if ok else "fail", "min": lo, "max": hi}
        if not ok:
            overall = "fail"
        elif overall == "pass":
            pass
    if overall != "fail" and any(r["status"] == "review" for r in results.values()):
        overall = "review"
    return results, overall


# ------------------------------------------------------------------ routes

@app.route("/")
def index():
    db = get_db()
    pending = db.execute(
        "SELECT * FROM documents WHERE status = 'needs_review' ORDER BY uploaded_at DESC"
    ).fetchall()
    approved = db.execute(
        "SELECT * FROM documents WHERE status = 'approved' ORDER BY uploaded_at DESC LIMIT 10"
    ).fetchall()
    return render_template("index.html", pending=pending, approved=approved,
                            ocr_available=ocr_extract.is_available())


@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")
    db = get_db()
    first_id = None
    for f in files:
        if not f or not f.filename:
            continue
        filename = secure_filename(f.filename)
        stamped = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{filename}"
        path = os.path.join(UPLOAD_DIR, stamped)
        f.save(path)

        crop_prefix = os.path.splitext(stamped)[0]
        extracted, mode = extract_document(path, filename, crop_prefix)

        cur = db.execute(
            """INSERT INTO documents
               (filename, original_name, order_no, po_no, supplier, customer,
                commodity, spec, cert_no, date_of_issue, status, extraction_mode, uploaded_at,
                field_crops_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'needs_review', ?, ?, ?)""",
            (stamped, filename, extracted.get("order_no"), extracted.get("po_no"),
             extracted.get("supplier"), extracted.get("customer"), extracted.get("commodity"),
             extracted.get("spec"), extracted.get("cert_no"), extracted.get("date_of_issue"),
             mode, datetime.now().isoformat(timespec="seconds"),
             json.dumps(extracted.get("field_crops", {}))),
        )
        doc_id = cur.lastrowid
        if first_id is None:
            first_id = doc_id

        for li in extracted.get("line_items", []):
            results, overall = check_chemistry(extracted.get("spec"), li["chemistry"], db)
            db.execute(
                """INSERT INTO line_items
                   (document_id, heat_no, size, product_no, quantity, weight,
                    chemistry_json, results_json, overall_status, order_no, raw_ocr_line,
                    crop_filename)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (doc_id, li.get("heat_no"), li.get("size"), li.get("product_no"),
                 li.get("quantity"), li.get("weight"), json.dumps(li["chemistry"]),
                 json.dumps(results), overall, extracted.get("order_no"), li.get("raw_ocr_line"),
                 li.get("crop_filename")),
            )
        db.commit()

    if first_id is None:
        return redirect(url_for("index"))
    return redirect(url_for("review", doc_id=first_id))


HEADER_FIELDS = ["order_no", "po_no", "supplier", "customer", "commodity", "spec", "cert_no", "date_of_issue"]


@app.route("/review/<int:doc_id>")
def review(doc_id):
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    items = db.execute("SELECT * FROM line_items WHERE document_id = ?", (doc_id,)).fetchall()
    items = [dict(i, chemistry=json.loads(i["chemistry_json"]), results=json.loads(i["results_json"])) for i in items]
    field_crops = json.loads(doc["field_crops_json"] or "{}")

    # Duplicate cert no. warning — ADR-008: warn, don't block.
    dup = None
    if doc["cert_no"]:
        dup = db.execute(
            "SELECT * FROM documents WHERE cert_no = ? AND id != ? AND status = 'approved'",
            (doc["cert_no"], doc_id),
        ).fetchone()

    next_pending = db.execute(
        "SELECT id FROM documents WHERE status = 'needs_review' AND id != ? ORDER BY uploaded_at LIMIT 1",
        (doc_id,),
    ).fetchone()

    return render_template("review.html", doc=doc, items=items, dup=dup, field_crops=field_crops,
                            next_pending_id=next_pending["id"] if next_pending else None)


def apply_review_edits(db, doc_id):
    """
    Reads the review form and writes it to `documents` + `line_items`,
    recomputing pass/fail from whatever's in the boxes at submit time
    (ADR-005/006: overwrite, no dual-store of the original OCR value —
    the form field is simply pre-filled with what OCR read, and whatever the
    human leaves in the box at submit time becomes the record). Does NOT
    touch `status` — callers (`save`, `approve`) decide that. Returns the
    resolved spec string.
    """
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    header_values = {f: request.form.get(f"field_{f}", "").strip() or None for f in HEADER_FIELDS}
    spec = header_values["spec"] or doc["spec"]

    db.execute(
        """UPDATE documents SET order_no=?, po_no=?, supplier=?, customer=?, commodity=?,
           spec=?, cert_no=?, date_of_issue=? WHERE id=?""",
        (header_values["order_no"], header_values["po_no"], header_values["supplier"],
         header_values["customer"], header_values["commodity"], spec,
         header_values["cert_no"], header_values["date_of_issue"], doc_id),
    )

    items = db.execute("SELECT * FROM line_items WHERE document_id = ?", (doc_id,)).fetchall()
    for item in items:
        original_chemistry = json.loads(item["chemistry_json"])
        chemistry = {}
        for element, value in original_chemistry.items():
            raw = request.form.get(f"chem_{item['id']}_{element}")
            try:
                chemistry[element] = float(raw) if raw not in (None, "") else value
            except ValueError:
                chemistry[element] = value  # unparseable edit — keep prior value rather than crash
        heat_no = request.form.get(f"heat_{item['id']}", "").strip() or item["heat_no"]

        results, overall = check_chemistry(spec, chemistry, db)
        db.execute(
            """UPDATE line_items SET heat_no=?, chemistry_json=?, results_json=?,
               overall_status=?, order_no=? WHERE id=?""",
            (heat_no, json.dumps(chemistry), json.dumps(results), overall,
             header_values["order_no"], item["id"]),
        )
    db.commit()
    # TODO(ADR-009): order_line_items join table not created yet — order_no
    # is stored directly on line_items for now as the simpler first step.
    return spec


@app.route("/review/<int:doc_id>/save", methods=["POST"])
def save(doc_id):
    """Persists edits without approving — status is left exactly as it was
    (needs_review stays needs_review, approved stays approved). Added per
    Tristan's request (2026-08-24): correcting a value shouldn't force you
    through the whole approve-and-advance flow just to keep the fix."""
    db = get_db()
    apply_review_edits(db, doc_id)
    return redirect(url_for("review", doc_id=doc_id))


@app.route("/review/<int:doc_id>/approve", methods=["POST"])
def approve(doc_id):
    db = get_db()
    doc = db.execute("SELECT status FROM documents WHERE id = ?", (doc_id,)).fetchone()
    was_already_approved = doc["status"] == "approved"

    apply_review_edits(db, doc_id)
    db.execute("UPDATE documents SET status='approved' WHERE id=?", (doc_id,))
    db.commit()

    if was_already_approved:
        # Re-editing an already-approved record — stay put rather than
        # jumping into whatever's next in the pending queue.
        return redirect(url_for("review", doc_id=doc_id))

    next_pending = db.execute(
        "SELECT id FROM documents WHERE status = 'needs_review' ORDER BY uploaded_at LIMIT 1"
    ).fetchone()
    if next_pending:
        return redirect(url_for("review", doc_id=next_pending["id"]))
    return redirect(url_for("index"))


@app.route("/review/<int:doc_id>/remove", methods=["POST"])
def remove(doc_id):
    """Discards a document and its line items entirely — including approved
    ones (extended 2026-08-24 per Tristan's request; originally needs_review
    only, see ADR-015). Used for clearing a bad OCR attempt, or a test/demo
    record, so a cleaner version can take its place. Hard delete, no undo."""
    db = get_db()
    doc = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    if doc:
        crops = set(json.loads(doc["field_crops_json"] or "{}").values())
        for item in db.execute("SELECT crop_filename FROM line_items WHERE document_id = ?", (doc_id,)):
            if item["crop_filename"]:
                crops.add(item["crop_filename"])
        for crop_name in crops:
            crop_path = os.path.join(CROP_DIR, crop_name)
            if os.path.exists(crop_path):
                os.remove(crop_path)
        upload_path = os.path.join(UPLOAD_DIR, doc["filename"])
        if os.path.exists(upload_path):
            os.remove(upload_path)
        db.execute("DELETE FROM line_items WHERE document_id = ?", (doc_id,))
        db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        db.commit()

    return_to = request.form.get("return")
    if return_to == "index":
        return redirect(url_for("index"))
    if return_to == "data":
        return redirect(url_for("data_table"))

    next_pending = db.execute(
        "SELECT id FROM documents WHERE status = 'needs_review' ORDER BY uploaded_at LIMIT 1"
    ).fetchone()
    if next_pending:
        return redirect(url_for("review", doc_id=next_pending["id"]))
    return redirect(url_for("index"))


@app.route("/data")
def data_table():
    db = get_db()
    rows = db.execute(
        """SELECT li.*, d.id AS doc_id, d.filename AS doc_filename, d.original_name,
                  d.supplier, d.customer, d.cert_no, d.spec
           FROM line_items li JOIN documents d ON d.id = li.document_id
           WHERE d.status = 'approved'
           ORDER BY li.id DESC"""
    ).fetchall()
    rows = [dict(r, chemistry=json.loads(r["chemistry_json"]), results=json.loads(r["results_json"])) for r in rows]
    return render_template("data.html", rows=rows)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=3000, debug=True)
