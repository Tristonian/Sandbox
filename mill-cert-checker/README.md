# Mill Cert Checker

A local prototype that ingests mill test certificates (PDF/image), OCRs out
the header info and per-heat chemical composition table, checks each
element against a tolerance spec (starting with SAE10B21), and — after a
human reviews and corrects the extraction — commits it to a local database.

Full design reasoning lives in [`ADR.md`](ADR.md), current status/open
items in [`NEXT-STEPS.md`](NEXT-STEPS.md), and guidance for anyone (human
or AI) picking this project back up in [`CLAUDE.md`](CLAUDE.md). This file
is just "how to run it."

## Prerequisites

- **Python 3.10+**
- **Tesseract OCR** (the actual OCR engine — free, local, does the reading).
  This is a system binary, not something `pip install` can get you.

## Setup

### 1. Install Tesseract

**macOS** (via [Homebrew](https://brew.sh)):
```bash
brew install tesseract
```

**Windows:**
```powershell
winget install --id UB-Mannheim.TesseractOCR -e
```
(Or download the installer directly from the
[UB-Mannheim Tesseract releases page](https://github.com/UB-Mannheim/tesseract/releases)
if `winget` isn't available.)

**Linux (Debian/Ubuntu):**
```bash
sudo apt install tesseract-ocr
```

`ocr_extract.py` looks for `tesseract` on your `PATH` automatically — no
config needed on macOS/Linux once installed via the package manager. On
Windows it also checks the default `C:\Program Files\Tesseract-OCR\` install
location as a fallback in case the installer didn't add it to `PATH`.

Verify it worked:
```bash
tesseract --version
```

### 2. Install Python dependencies

From the `mill-cert-checker` folder:
```bash
pip install -r requirements.txt
```

(If `pip` defaults to Python 2 on your system, use `pip3` instead.)

### 3. Run it

```bash
python app.py
```
(or `python3 app.py` on macOS/Linux)

Then open **http://localhost:3000** in a browser.

The app creates `millcert.db` (SQLite) and an `uploads/` folder in this
directory on first run — both are gitignored, so they stay local to your
machine.

## Using it

1. Drag a mill cert PDF/image onto the upload page (or click to browse —
   multiple files at once are fine, each is treated as its own certificate).
2. You'll land on the review screen for the first one: extracted fields are
   editable, with the exact source-image region shown next to each so you
   can eyeball-check it against what OCR read, no need to open the original
   file separately. Chemistry cells recolor live (green/amber/red — see the
   key on the page) as you edit a value.
3. **Save changes** persists corrections without leaving the document.
   **Approve & commit** persists and moves you to the next one pending.
   **Remove** discards this document entirely (including its extracted
   data) so you can re-upload a cleaner version.
4. Approved data shows up in the **Data table** page. Every document —
   pending or already approved — has an **Open** link back into the review
   screen from the upload page or the data table, so you can revisit an old
   cert, re-check its source crops, or **Remove** it later if it turns out
   to be wrong. Removing an approved document is permanent — there's no undo
   and no log of who removed what (see `CLAUDE.md` for why that's a known
   gap, not an oversight).

## Troubleshooting

**Upload page shows "Tesseract not found"** — the app couldn't locate the
binary. Confirm `tesseract --version` works in the same terminal you're
running `python app.py` from; if it works there but not in the app, restart
your terminal/IDE after installing (PATH changes need a fresh shell).

**Extraction comes back mostly blank** — the app falls back to placeholder
data if OCR genuinely fails to run (not if it just reads things wrong — that
case shows up as bad values, not blanks). Check the terminal running
`app.py` for a warning line naming the actual error.
