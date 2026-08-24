"""
Local, free OCR extraction via Tesseract (ADR-012 — see ADR.md).

Known limitation, deliberately not solved yet: chemistry column ORDER is
assumed (CHEMISTRY_COLUMNS_DEFAULT) rather than detected from each cert's
own header row, because reliably OCR'ing a two-line stacked table header
(element symbol on one line, "(%)" unit on the next) turned out to be much
less reliable than reading the data rows themselves. This is exactly the
layout-generalization gap ADR-001 flagged when choosing between cloud
vision and local OCR — it's real, not hypothetical, and it's why every
extracted row still goes through human review (ADR-003) rather than being
trusted outright.

ADR-013 added per-field/per-row bounding boxes (word-level, from
pytesseract.image_to_data) so the review screen can crop and show the exact
source-image region next to each parsed value, instead of requiring the
whole document to be opened separately to cross-check.
"""
import os
import re
import shutil

import pymupdf as fitz
import pytesseract
from PIL import Image
from pytesseract import Output

# Cross-platform binary lookup: PATH first (covers `brew install tesseract`
# on macOS/Linux, and Windows too if the installer added it to PATH), with
# hardcoded fallbacks for the common Windows installer location in case it
# didn't. See README.md for install instructions per OS.
TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]
_found = shutil.which("tesseract")
if _found:
    pytesseract.pytesseract.tesseract_cmd = _found
else:
    for _path in TESSERACT_PATHS:
        if os.path.exists(_path):
            pytesseract.pytesseract.tesseract_cmd = _path
            break

CHEMISTRY_COLUMNS_DEFAULT = ["C", "Si", "Mn", "P", "S", "Cr", "Ni", "B", "Cu", "Mo", "Sol-Al"]

FIELD_LABELS = {
    "order_no": ["Order No"],
    "po_no": ["PO No"],
    "supplier": ["Supplier"],
    "customer": ["Customer"],
    "commodity": ["Commodity"],
    "spec": ["Spec & Type", "Spec"],
    "cert_no": ["Certificate No"],
    "date_of_issue": ["Date of Issue"],
}

# Longest/most-specific labels first so "Spec & Type" wins over bare "Spec",
# and so the lookahead below stops a value at the *next* label rather than
# swallowing the rest of the line — OCR runs "Label: Value  Label2: Value2"
# together without reliable double-spacing to split on.
_LABEL_ALTERNATION = "|".join(
    sorted({re.escape(lbl) for labels in FIELD_LABELS.values() for lbl in labels},
           key=len, reverse=True)
)
_HEADER_FIELD_RE = re.compile(
    rf"({_LABEL_ALTERNATION})\s*[:.]\s*(.*?)(?=(?:{_LABEL_ALTERNATION})\s*[:.]|\n|$)",
    re.IGNORECASE,
)

HEAT_NO_RE = re.compile(r"\b([A-Z]{1,3}\d{4,6})\b")
PRODUCT_NO_RE = re.compile(r"\b([A-Z]{2,5}\d{6,8}(?:-\d{3,4})?)\b")
NUMBER_RE = re.compile(r"\d+\.\d+|\d+")

CROP_PADDING = 6


def is_available():
    cmd = pytesseract.pytesseract.tesseract_cmd
    return bool(shutil.which(cmd) or os.path.exists(cmd))


def render_pages(file_path, dpi=300):
    ext = os.path.splitext(file_path)[1].lower()
    images = []
    if ext == ".pdf":
        doc = fitz.open(file_path)
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        for page in doc:
            pix = page.get_pixmap(matrix=mat)
            images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
    else:
        images.append(Image.open(file_path).convert("RGB"))
    return images


def _ocr_lines(images):
    """One entry per physical printed line, each carrying its own words
    (with per-word bounding boxes) so a regex match's character span can be
    mapped back to a tight bounding box, not just "the whole line"."""
    lines = []
    for page_index, img in enumerate(images):
        data = pytesseract.image_to_data(img, output_type=Output.DICT)
        groups = {}
        for i in range(len(data["text"])):
            txt = data["text"][i]
            if not txt or not txt.strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            groups.setdefault(key, []).append({
                "text": txt, "left": data["left"][i], "top": data["top"][i],
                "width": data["width"][i], "height": data["height"][i],
            })
        for words in groups.values():
            words.sort(key=lambda w: w["left"])
            text, offsets = "", []
            for w in words:
                if text:
                    text += " "
                start = len(text)
                text += w["text"]
                offsets.append((start, len(text), w))
            lines.append({
                "text": text,
                "offsets": offsets,
                "page_index": page_index,
                "left": min(w["left"] for w in words),
                "top": min(w["top"] for w in words),
                "right": max(w["left"] + w["width"] for w in words),
                "bottom": max(w["top"] + w["height"] for w in words),
            })
    lines.sort(key=lambda l: (l["page_index"], l["top"]))
    return lines


def _bbox_for_span(offsets, start, end, page_index):
    matched = [w for (s, e, w) in offsets if e > start and s < end]
    if not matched:
        return None
    return {
        "page_index": page_index,
        "left": min(w["left"] for w in matched),
        "top": min(w["top"] for w in matched),
        "right": max(w["left"] + w["width"] for w in matched),
        "bottom": max(w["top"] + w["height"] for w in matched),
    }


def crop_box(images, box, padding=CROP_PADDING):
    if box is None:
        return None
    img = images[box["page_index"]]
    l, t, r, b = box["left"], box["top"], box["right"], box["bottom"]
    return img.crop((max(0, l - padding), max(0, t - padding),
                      min(img.width, r + padding), min(img.height, b + padding)))


def parse_header_fields(lines):
    """Returns (fields dict, boxes dict) — boxes are per-field, cropped
    tightly to the matched value's words, not the whole printed line."""
    fields, boxes = {}, {}
    label_to_key = {lbl.lower(): key for key, labels in FIELD_LABELS.items() for lbl in labels}
    for line in lines:
        for match in _HEADER_FIELD_RE.finditer(line["text"]):
            label = match.group(1).strip().lower()
            key = label_to_key.get(label)
            if not key or key in fields:
                continue
            value = re.sub(r"^[\s:.\-]+", "", match.group(2)).strip()
            if not value:
                continue
            fields[key] = value
            v_start, v_end = match.span(2)
            boxes[key] = _bbox_for_span(line["offsets"], v_start, v_end, line["page_index"])
    for key in FIELD_LABELS:
        fields.setdefault(key, None)
        boxes.setdefault(key, None)
    return fields, boxes


def parse_line_items(lines, columns=None):
    """Best-effort row parse. Every returned item carries a bounding box
    for the whole row (for a side-by-side crop) plus `raw_ocr_line` so a
    human reviewer can cross-check the parsed values against the source."""
    columns = columns or CHEMISTRY_COLUMNS_DEFAULT
    items = []
    for line in lines:
        text = line["text"]
        heat_match = HEAT_NO_RE.search(text)
        numbers = NUMBER_RE.findall(text)
        if not heat_match or len(numbers) < len(columns):
            continue
        chem_tokens = numbers[-len(columns):]
        try:
            chemistry = {col: float(val) for col, val in zip(columns, chem_tokens)}
        except ValueError:
            continue
        # B is printed in ppm on the cert, not %  — normalise to the same
        # % scale as spec_limits (matches the mock data convention).
        if "B" in chemistry:
            chemistry["B"] = chemistry["B"] / 10000.0 if chemistry["B"] > 1 else chemistry["B"]

        product_match = PRODUCT_NO_RE.search(text)
        items.append({
            "heat_no": heat_match.group(1),
            "product_no": product_match.group(1) if product_match else None,
            "size": None,
            "quantity": None,
            "weight": None,
            "chemistry": chemistry,
            "raw_ocr_line": text.strip(),
            "box": {
                "page_index": line["page_index"], "left": line["left"], "top": line["top"],
                "right": line["right"], "bottom": line["bottom"],
            },
        })
    return items


def extract(file_path, crop_dir=None, crop_prefix="doc"):
    """Runs OCR, parses fields + line items, and — if crop_dir is given —
    saves a cropped source-image PNG per field/row, storing the relative
    filename (under crop_dir) on each so the review screen can show it."""
    images = render_pages(file_path)
    lines = _ocr_lines(images)
    fields, field_boxes = parse_header_fields(lines)
    items = parse_line_items(lines)

    if crop_dir:
        os.makedirs(crop_dir, exist_ok=True)
        field_crops = {}
        for key, box in field_boxes.items():
            crop = crop_box(images, box)
            if crop is None:
                continue
            fname = f"{crop_prefix}_field_{key}.png"
            crop.save(os.path.join(crop_dir, fname))
            field_crops[key] = fname
        fields["field_crops"] = field_crops

        for idx, item in enumerate(items):
            crop = crop_box(images, item["box"])
            if crop is None:
                continue
            fname = f"{crop_prefix}_row_{idx}.png"
            crop.save(os.path.join(crop_dir, fname))
            item["crop_filename"] = fname
    else:
        fields["field_crops"] = {}
        for item in items:
            item["crop_filename"] = None

    for item in items:
        item.pop("box", None)

    fields["line_items"] = items
    return fields
