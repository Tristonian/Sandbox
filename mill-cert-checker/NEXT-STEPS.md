# NEXT-STEPS — Mill Cert Checker

Where to pick up. Read `ADR.md` first — the decisions below assume that
context.

## What this is

A local tool that ingests mill test certificates (PDF/image), extracts the
header info (order no., PO no., supplier, customer, commodity, spec & type,
cert no., date of issue) and the per-heat chemical composition table, checks
each element against a tolerance table for the stated spec, and — after a
human reviews and approves the extraction — appends the result to a local
database.

Sample document used for planning: `Mill Sheet - LW 280076(N105263).pdf`, a
POSCO Mill Test Certificate for SAE10B21 wire rod, 8 heats, chemistry
columns C/Si/Mn/P/S/Cr/Ni/B/Cu/Mo/Sol-Al.

## Status: working prototype, end-to-end, running on real data (2026-08-24)

`app.py` (Flask, port 3000), `ocr_extract.py` (local Tesseract extraction),
and SQLite (`millcert.db`) exist and were run end-to-end against the actual
sample POSCO cert: upload → OCR → SAE10B21 pass/fail check → review screen
(editable, with source-image crops) → approve → data table. All 8 heats
went through, including a real correction (a misread Carbon value fixed on
the review screen, confirmed to flip that row's status on re-approval).
**Read ADR-012 through ADR-015 before touching extraction or the review
flow** — they record what was validated against the real document and what
genuinely failed (Cert No. / Date of Issue came back blank — small/stamped
text; one heat's Carbon misread as 0.2414 instead of 0.2111), not
hypotheticals.

Also built: light/dark theme toggle (`_base.html`, localStorage-persisted),
a Remove action to discard an unreviewed document (ADR-015), and
`README.md` with install/run instructions for Windows and macOS.

**Not yet built:**
- The `order_line_items` join table (ADR-009 — order_no is currently stored
  directly on `line_items` as an interim simplification).
- `spec_limits_history` audit log (ADR-010 calls for one; edits to
  `spec_limits` aren't exposed in the UI at all yet, let alone logged).
- `api_usage_log` (ADR-011 — moot for now since extraction is local/free,
  no paid API call happening; revisit if a cloud-vision fallback is added).
- Size / Quantity / Weight / Product No. per line item aren't editable on
  the review form (Heat No. and chemistry values are).
- Chemistry column **order** is assumed, not detected per-document (see
  ADR-012's "known limitation" — the real generalization gap this local-OCR
  approach still has versus the originally-planned cloud vision route).
- Crops for *approved* documents have no cleanup path (ADR-013) — untested
  whether that's actually fine over time or a disk-usage problem later.

## Decisions locked in (see ADR.md for full reasoning)

- **Layouts vary** across suppliers, scan quality varies, documents may span
  multiple pages. No fixed-template extraction.
- **Extraction:** originally planned as a cloud vision LLM for prototype
  speed (ADR-001), but superseded before any cloud call was made — Tristan
  confirmed Claude Pro doesn't include API billing and asked for zero-cost
  extraction, so it runs on local Tesseract OCR instead (ADR-012),
  validated against the real sample document.
- **Every document requires human review and approval before its data is
  committed** to the database (ADR-003). No auto-commit path.
- **Tolerance table** (`spec_limits`) holds only cross-confirmed bounds.
  SAE10B21 seeded with C/Mn/P/S/B (see ADR-002 for the actual numbers and
  where they came from). Any chemical element on a cert with no matching row
  for that spec is flagged for mandatory human review, not auto-passed.
- **Stack:** Flask, `localhost:3000`, SQLite, plain HTML/JS drag-and-drop
  upload (ADR-004).

## Open questions — all resolved (2026-08-24)

All six items originally listed here are now decided. See ADR-005 through
ADR-011 for full reasoning; summary:

1. **Approval granularity** → per-document, with inline per-line-item
   editing before that one approval, and explicit per-line pass/fail/flag
   visibility so a mostly-clean cert doesn't hide its one bad row (ADR-005).
2. **Editing extracted values** → overwrite; no dual-store of original OCR
   output vs corrected value (ADR-006).
3. **Multi-page handling** → one uploaded file = one certificate; multi-page
   PDFs handled natively as one document. Batch upload of multiple *separate*
   certificates is supported, with the review flow queuing through them one
   at a time (ADR-007).
4. **Duplicate detection** → warn, don't block. Cert numbers are not
   guaranteed unique in practice — the same cert can legitimately back more
   than one order (ADR-008).
5. **Order↔certificate traceability** → modeled from the start, at the
   line-item (heat) level, not deferred and not at the whole-document level.
   An `order_line_items` join table links a specific order number to a
   specific heat row (ADR-009).
6. **`spec_limits` edits** → freeform, no approval gate, but every change is
   logged to a `spec_limits_history` table (who/when/old→new) so a bad edit
   is traceable even though it isn't prevented up front (ADR-010).
7. **API key / cost handling** → gitignored `.env` with a tracked
   `.env.example` template (mirrors TJWMC's pattern); each extraction call
   logs pages processed and estimated cost (ADR-011).

No open questions remain from the original brainstorming list. Anything new
that comes up during the build should get its own ADR entry, not get
silently decided in code.

## What's built vs. what's left of the original build plan

Data model, Flask skeleton, extraction, pass/fail logic, and a review UI
with editable fields, source-image crops, and a duplicate-cert-no. warning
are all built and validated against the real sample cert (see Status
above). Still outstanding from the original plan:

- `spec_limits_history`, `order_line_items`, `api_usage_log` tables — not
  created yet (ADR-010, ADR-009, ADR-011 respectively describe them; none
  block the core pipeline working, which is why they were deferred).
- A second, differently-laid-out real cert has **not** been tried yet — only
  the one POSCO sample. The chemistry-column-order assumption (ADR-012) and
  the header-field regex patterns are unvalidated against any other
  supplier's layout. This is the most important next test before trusting
  this on real incoming mail.

## What's verified vs. assumed

**Verified (2026-08-24), against the real sample POSCO cert, not
hypothetical:** header field extraction, all 8 heats' chemistry extraction,
the pass/fail check against SAE10B21, the source-image crop feature, the
inline-edit-and-recompute flow, and the full upload→review→approve→data
table pipeline.

**Still assumed, not verified:** the SAE10B21 numbers in ADR-002 come from
web research cross-checked across two sources for the core elements only —
not validated against an actual SAE J403 document or a POSCO-confirmed
internal spec. Chemistry column order (ADR-012) is assumed from the one
sample document, not detected per-document. Treat both as reasonable
starting points, not ground truth, until confirmed against a primary
source or a second real cert.
