# ADR — Mill Cert Checker

Architectural decisions for the mill test certificate ingestion/verification
tool. Read this before making a change that contradicts something here —
either the reasoning still holds and the change is wrong, or the reasoning is
stale and this file needs a new entry saying why.

Format: newest first. Superseded decisions are left in place and marked, not
deleted.

---

## ADR-017 — Save and Approve split into separate actions

**Context:** ADR-014 wired editing into the review form, but the only way
to persist an edit was the same **Approve & commit** button that also
advances to the next pending document. Tristan asked for a plain save —
fixing a value shouldn't force a full approve-and-advance just to keep the
correction.

**Decision:** Both buttons submit the same form (all header + chemistry
inputs) to different routes via `formaction`: **Save changes**
(`/review/<id>/save`) persists edits and recomputes pass/fail without
touching `status` or advancing the queue — it redirects back to the same
document. **Approve & commit** (`/review/<id>/approve`) does the same
persist-and-recompute, then sets `status='approved'` and advances to the
next pending document (or index, if none). Both routes share one
`apply_review_edits()` function so the recompute logic can't drift between
them.

**Consequences:** A document can sit in `needs_review` indefinitely with
saved partial corrections — that's intended (matches "come back to this
later" workflows), not a bug. Re-opening `/review/<id>/approve` for an
already-`approved` document (via the new Open links from the data table /
approved list, ADR-016) reuses the same route: it updates the existing
record in place and redirects back to itself rather than jumping into the
pending queue, since there's nothing to "advance" to.

---

## ADR-016 — Remove extended to approved documents

**Context:** ADR-015 deliberately scoped Remove to `needs_review` documents
only, reasoning that approved data is "the record of truth" and shouldn't
have a casual delete path. In practice, during the same session, an
approved test/demo document had no UI way to be removed — only a direct
database edit could clear it — and Tristan asked for the ability to clear
entries and re-add fresh ones without that restriction.

**Decision:** `/review/<id>/remove` now deletes a document regardless of
status, including `approved` ones. The confirmation dialog's wording
changes based on status — approved documents get an explicit "this will be
permanently deleted from the data table" warning, unreviewed ones get the
original wording. Remove is now reachable from three places: the review
screen, the pending list (upload page), and the approved list (both on the
upload page and in the full data table) — each pointing back to a sensible
place afterward via a `return` form field (`index`, `data`, or the default
next-pending-document behaviour).

**Consequences:** This reverses ADR-015's core safety argument — there is
now no protected category of data in this tool; anything can be hard-deleted
by anyone with access to the running app, with only a browser `confirm()`
dialog in the way. Acceptable for a single-user/small-team local prototype
with no auth, which is the only context this has been built for so far.
**Explicitly revisit before this tool has multiple users or any real
audit/compliance weight** — at that point "who deleted an approved
certificate record and why" needs to be answerable, which nothing here
currently provides (no soft-delete, no deletion log).

---

## ADR-015 — Remove/discard is scoped to unreviewed documents only

**Superseded by ADR-016** — kept for history; the "approved documents can't
be removed" restriction described below no longer holds.


**Context:** Tristan asked for a way to clear a bad OCR attempt and
re-upload cleanly, for demo purposes and general workflow — uploading a
badly-scanned file shouldn't leave permanent junk in the pipeline with no
way out short of editing the database directly.

**Decision:** `/review/<id>/remove` deletes a document, its line items, its
uploaded file, and its crop images — but only if the document is still
`needs_review`. An already-`approved` document cannot be removed through
this action (the route's query filters on status, so attempting it on an
approved doc is a silent no-op). Available both on the review screen and as
a per-row action on the pending list on the upload page.

**Consequences:** This is a hard delete, not a soft-delete/archive — there's
no undo once a needs_review document is removed. That's acceptable because
nothing downstream (no approved data, no order links) depends on it yet;
per ADR-003, nothing reaches the database of record until approval anyway,
so removing a pending document only ever discards work that was never
trusted. Revisit if there's ever a reason to remove an *approved* document
(e.g. "this cert was uploaded by mistake") — that's a different, higher-
stakes action deliberately not built here.

---

## ADR-014 — Inline editing wired up: the review form is the correction mechanism

**Context:** ADR-005 and ADR-006 designed for inline editing before
document-level approval, but the first working version (ADR-012) shipped
with the review screen read-only — editing was a TODO. Tristan asked for it
to be wired in for a demo, since ADR-012 immediately surfaced a real OCR
misread (Carbon read as 0.2414 instead of 0.2111) with no way to fix it
short of a database edit.

**Decision:** Every header field and every chemistry value on the review
screen is a real form input, pre-filled with the extracted value. On
**Approve**, `app.py`'s `approve()` route reads whatever is in each box at
submit time — not what was originally extracted — recomputes each line
item's pass/fail against the spec (ADR-002's rule) from those values, and
commits the result. Per ADR-006, there's no dual-store: the box's value at
submit time simply *is* the record from then on.

**Validated (2026-08-24):** correcting SF00180's Carbon from `0.2414` to
`0.2111` and re-approving flipped that line's status from FAIL to REVIEW
(REVIEW because Cr/Ni/Cu/Mo/Sol-Al still have no confirmed spec_limits row —
correct behaviour per ADR-002, not a bug).

**Consequences:** Heat No. and chemistry values are editable; Size,
Quantity, Weight, Product No. are not yet (not wired to inputs — lower
priority since they don't feed pass/fail). Order No. edited on the header
form is pushed onto every line item's `order_no` column at approve time,
consistent with the interim simplification noted in ADR-009.

---

## ADR-013 — Per-field/per-row source-image crops for by-eye comparison

**Context:** ADR-012's first working version required opening the full
source file in another tab to check any single OCR'd value against the
original — slow, and exactly the kind of friction that makes a reviewer
start trusting extracted values without actually checking them. Tristan
asked for the relevant portion of the source image shown side by side with
each extracted field/row instead.

**Decision:** `ocr_extract.py` now drives extraction off
`pytesseract.image_to_data` (word-level bounding boxes) rather than
`image_to_string` (plain text) alone. Physical printed lines are
reconstructed from word groups (grouped by Tesseract's own
block/paragraph/line numbering), keeping each word's bounding box attached.
Header-field regex matches are mapped back from character offsets to the
specific words they matched, giving a tight per-field crop — not just "the
whole printed line" — and each line-item row keeps the bounding box of its
whole line. Crops are saved as PNGs under `uploads/crops/`, named by
document + field/row, and referenced by filename on `documents` and
`line_items` (added `field_crops_json` and `crop_filename` columns).

**Validated (2026-08-24):** running against the real POSCO cert, the row-0
crop visually shows `0.2111` printed for Carbon, while the OCR'd *value* for
that same row reads `0.2414` — i.e. this feature immediately surfaced a real
misread side by side, which is exactly the failure mode ADR-003's review
gate exists to catch, now made checkable at a glance instead of requiring
the reviewer to open the source file and hunt for the row.

**Consequences:** One extra Tesseract pass per page isn't needed — the
switch is from `image_to_string` to `image_to_data`, not an additional
call, so no meaningful extra extraction time. Crop files accumulate in
`uploads/crops/` — cleaned up by `/review/<id>/remove` (ADR-015) for
unreviewed documents, but there's no cleanup path for crops belonging to
*approved* documents yet (they're meant to stay, as the audit trail behind
an approved record, but that's an assumption not yet tested against real
disk usage over time).

---

## ADR-012 — Extraction switched to local Tesseract OCR, superseding ADR-001's cloud-vision plan

**Context:** ADR-001 chose a cloud vision LLM for prototype speed, with local
Tesseract explicitly deferred as future work. Tristan then confirmed
(2026-08-24) that a Claude Pro subscription does not include Anthropic API
access — API calls need separate, metered billing — and asked for an OCR
solution with zero cost and no billing setup. That moves Tesseract from
"future work" to "now."

**Decision:** `ocr_extract.py` runs local Tesseract (via `pytesseract` +
`pymupdf` for PDF page rendering) as the extraction engine. Installed via
`winget install --id UB-Mannheim.TesseractOCR`. No API key, no network call,
no per-document cost. `extract_document()` in `app.py` falls back to the
existing mock data if Tesseract genuinely isn't installed, so the pipeline
never hard-fails.

**Validated against the real sample POSCO cert (2026-08-24), not assumed:**
- Header fields (order no., PO no., supplier, customer, commodity, spec) all
  extracted correctly.
- **Certificate No. and Date of Issue extracted as blank** — that text sits
  near a small stamp/QR graphic and OCR'd to garbage. The review screen now
  shows an explicit warning when either is missing on an OCR'd document,
  rather than silently leaving a blank field.
- All 8 line items' chemical composition extracted, including Heat No. and
  Product No., using a "last N numeric tokens = the chemistry columns"
  parse that proved robust even with garbage tokens earlier in the same OCR
  line (commas/punctuation misread as extra digits).
- **One genuine OCR misread**: heat SF00180's first row read Carbon as
  `0.2414` instead of the true `0.2111` — enough to cross SAE10B21's 0.23
  max and produce a real FAIL that a human reviewing the source image would
  immediately see is wrong. This is not hypothetical — it happened on the
  first real test and is exactly the failure mode ADR-003's review gate
  exists to catch.

**Known limitation, not solved:** chemical element **column order is
assumed** (`CHEMISTRY_COLUMNS_DEFAULT` = C, Si, Mn, P, S, Cr, Ni, B, Cu, Mo,
Sol-Al), not detected from each cert's own header row. The two-line stacked
header (element symbol on one row, "(%)" unit below it) did not OCR reliably
enough to detect column order safely. This is the layout-generalization gap
ADR-001 originally flagged for cloud vision solving "for free" — it's real,
and it means a mill that prints chemistry columns in a different order will
silently mismap values until this gets fixed. Size/Quantity/Weight per line
item also aren't parsed yet (`None` on OCR'd documents) — lower priority
since they don't feed the pass/fail check.

**Consequences:** Zero ongoing cost, works offline, but nowhere near the
"any layout" robustness a vision LLM would have given for free. Every OCR'd
document's raw source line is stored per line-item and shown on the review
screen specifically to compensate for this — the tool is honest about lower
confidence rather than hiding it. Revisit the cloud-vision path (kept as
`_extract_mock`'s structural sibling, not deleted) if column-order variance
or scan quality turns out to make local OCR unworkable on real supplier
certs beyond POSCO's.

---

## ADR-011 — API key handling and cost logging

**Context:** Extraction calls a paid vision LLM API per document/page. Key
must not be committed; cost should be visible before this scales from a few
certs a week to a real volume.

**Decision:** Key lives in a gitignored `.env`, with a tracked `.env.example`
containing placeholders only (same pattern as TJWMC's `users.local.js` /
`.env.local` split). The app logs a line per extraction call — pages sent,
timestamp, estimated cost — so usage is visible without needing to check an
external dashboard.

**Consequences:** A small amount of extra bookkeeping per call. No budget
cap or alerting for the prototype — just a log to look at.

---

## ADR-010 — `spec_limits` edits are freeform but logged

**Context:** A wrong tolerance bound doesn't just affect one document — it
silently mis-grades every cert checked against that spec afterward, in
either direction. But requiring a formal approval step on every tolerance
edit (mirroring ADR-003's document gate) is more process than a
small-team prototype needs right now.

**Decision:** Anyone using the tool can add or edit `spec_limits` rows
directly — no approval gate. Every change is logged to a
`spec_limits_history` table: who, when, spec, element, old min/max, new
min/max. Nothing blocks the edit from taking effect immediately; the log
exists so a bad edit can be traced and reverted.

**Consequences:** A typo'd bound (0.90 vs 0.09) still silently mis-grades
certs until someone notices — the log only helps *after* the fact, it
doesn't prevent it. Revisit if that turns out to be a real problem, not a
hypothetical one.

---

## ADR-009 — Order↔line-item traceability modeled from the start

**Context:** Tristan clarified (2026-08-24) that Order No. and Certificate
No. are not 1:1: the same certificate can legitimately be referenced by
more than one order (material from one supply batch used across orders),
and a single order can draw material covered by more than one certificate
(material sourced from two different supplies). This is real, current
business reality, not a hypothetical edge case.

**Decision:** Model this now rather than deferring it. An `order_line_items`
join table links a specific order number to a specific `line_item` (a heat
row within a document), not to the document as a whole and not to a bare
order-number field on the document. This matches physical reality: material
is consumed heat by heat, so the precise question the schema needs to answer
is "which heats, from which certs, backed this order" — not just "which
certs mention this order number."

**Consequences:** More schema/UI work up front than treating Order No. as a
plain text field (the originally lighter-weight option), but avoids
rebuilding the data model later once real traceability queries are needed.
`documents` still carries a header-level Order No. as extracted (mills print
one on the cert), but it is not treated as unique or authoritative on its
own — `order_line_items` is.

---

## ADR-008 — Duplicate certificate numbers: warn, don't block

**Context:** Certificate numbers are not guaranteed unique in practice — see
ADR-009's context. The same cert can legitimately be uploaded once per order
it's referenced against.

**Decision:** On upload, check the extracted Cert No. against existing
documents. If found, show a warning on the review screen ("this cert no.
already exists — uploaded [date], linked to orders [...]") but do not block
approval. The human reviewing decides whether it's a legitimate re-reference
or an accidental re-upload.

**Consequences:** No hard uniqueness constraint on Cert No. in the schema.
Relies on the review step (ADR-003) to catch genuine accidental duplicates.

---

## ADR-007 — Upload model: one file = one certificate, batch upload supported

**Context:** A single mill cert can span multiple pages (the POSCO sample
shows "PAGE : 1", implying more may exist), but there was no evidence of
certs arriving as separate scanned image files per page rather than a
single multi-page PDF. Separately, a real workflow will involve uploading
several *different* certificates in one sitting.

**Decision:** One uploaded file = one certificate/document. Multi-page PDFs
are handled natively (Flask/PDF libraries read all pages of one file as one
document) — no need to stitch separate files into one document for the
prototype. The drag-and-drop zone accepts multiple files at once for batch
upload, but each file is extracted and reviewed as its own separate
document; the review flow queues through them one at a time rather than
merging them.

**Consequences:** If a real cert ever does arrive as separate per-page image
files (not one PDF), this won't handle it — revisit if that actually comes
up. Batch upload means the review UI needs a "next document" queue concept
from the start, not just a single-document review screen.

---

## ADR-006 — No dual-store of OCR-original vs human-corrected values

**Context:** ADR-003 established inline editing before document-level
approval (see ADR-005). When a human corrects a misread value on the review
screen, the question is whether to keep the original OCR output for later
auditing of extraction quality, or just overwrite it.

**Decision:** Overwrite. The corrected value becomes the record; the
original OCR reading is not persisted anywhere once corrected.

**Consequences:** Simpler schema for the prototype (`line_items` just holds
one set of values, not two). Trades away the ability to later measure OCR
error rates or spot a systematic misread pattern (e.g. a supplier's scans
consistently confusing a decimal point) across many documents. Revisit if
extraction quality auditing becomes a real need — it would mean adding
extracted-vs-confirmed columns (or a separate log) at that point, not
reworking what's there.

---

## ADR-005 — Approval is per-document, with inline per-line editing and explicit fail visibility

**Context:** A cert can have many line items (heats). Tristan wants to see
exactly which lines caused a failure, especially when most lines passed —
not have one bad row block visibility into the rest, but also not have the
unit of approval be so granular that reviewing becomes tedious.

**Decision:** The unit of approval is the whole document, but the review
screen supports editing individual line items inline before that one
approval action. Each line item's pass/fail (and which specific element
caused a fail, per ADR-002) is shown clearly and individually — so a
document with 7 clean heats and 1 failing heat shows all 8 with the 1
called out, rather than a single pass/fail verdict for the whole cert.
Approving the document commits all its line items (as edited) together.

**Consequences:** A reviewer can't partially commit a document (approve 7
heats, leave 1 pending) — the whole document commits at once, after any
needed corrections. This was a deliberate choice over row-by-row partial
commit, in favor of keeping "the cert as reviewed" as one coherent unit.

---

## ADR-004 — Prototype stack: Flask, port 3000, SQLite, drag-and-drop

**Context:** This is a proof of concept for one user/team, run locally. No
need for multi-user auth, cloud hosting, or a heavy frontend framework yet.

**Decision:**
- Flask app, served at `localhost:3000`.
- Plain HTML/JS frontend — a drag-and-drop upload zone plus a review table.
  No React/build step for the prototype; it's one or two templates and some
  vanilla JS.
- SQLite as the datastore. Tables (subject to change as we build):
  `documents` (upload metadata, file, status), `line_items` (one row per
  heat/lot extracted from a cert), `spec_limits` (spec name, element, min,
  max, source), `review_flags` (why a line item needs a human look).

**Consequences:** Not production-ready — single process, no auth, no
concurrent-user story. That's fine for a prototype; revisit if this needs to
serve more than one person.

---

## ADR-003 — Nothing is committed to the database without human approval

**Context:** Extraction comes from an LLM reading variable-quality scans of
documents with layouts we don't control. It will misread things sometimes.
Some elements on a cert won't have a confirmed tolerance to check against
(see ADR-002). Auto-committing unreviewed output would make the database of
record only as trustworthy as the OCR pass that populated it — and wrong
silently, which is worse than wrong loudly.

**Decision:** Every document goes through a fixed pipeline:

`upload → extract (vision LLM) → review screen → human approves/edits → commit`

The review screen shows the extracted fields and the computed pass/fail per
element, side-by-side with the source page image(s), with anything flagged
(see ADR-002) called out explicitly. Nothing reaches `line_items` until a
human has looked at that document's extraction and approved it (with edits if
needed).

**Consequences:** Slower per document than full automation — deliberately.
This is the gate that makes the rest of the system trustworthy. Do not add a
"skip review" fast path without Tristan explicitly asking for it.

---

## ADR-002 — Tolerance spec table: confirmed values only, novel/unmatched elements force human review

**Context:** Pass/fail requires a reference table of (spec, element, min,
max). SAE10B21 is defined by SAE J403. Web research (2026-08-24) found the
core elements consistently confirmed across independent sources:

| Element | Min | Max | Source agreement |
|---|---|---|---|
| C | 0.18 | 0.23 | 2 independent sources agree |
| Mn | 0.60 | 0.90 | 2 independent sources agree |
| B | 0.0005 | 0.0030 | 2 independent sources agree |
| P | — | 0.030 | consistent |
| S | — | 0.035–0.050 | sources disagree on exact max |

But other elements the POSCO sample cert reports — Si, Cr, Ni, Cu, Mo,
Sol-Al — either don't appear in the SAE J403-sourced pages at all, or appear
with conflicting ranges on vendor pages (one site lists Mn as 0.80–1.10 and
adds Cr/Si limits not found anywhere else — plausibly a mill's own tightened
internal spec, or just an error on that page). There is no way to tell which,
from search results alone, without an authoritative primary source per
element.

**Decision:** The `spec_limits` table only holds elements with a
cross-confirmed bound. Every extracted chemical element is checked against
this table by (spec, element):

- **Matched, in range** → pass.
- **Matched, out of range** → fail.
- **No matching row for that (spec, element)** → not silently passed, not
  silently failed. Flagged for mandatory human review before the document
  can be approved. This covers both "novel" elements (something the table
  has never seen for that spec) and elements we found conflicting/no data
  for during research.

Tristan's call (2026-08-24): "any novel chemicals flag human review" —
option B over auto-passing unmatched elements as informational-only.

**Consequences:** On the sample POSCO cert, expect most rows to pass clean on
C/Mn/P/S/B and every row to carry a review flag for Cr/Ni/Cu/Mo/Sol-Al until
someone adds confirmed bounds for those elements (per spec, since bounds are
spec-specific) via the UI. The `spec_limits` table is designed to grow —
more specs beyond SAE10B21 get added the same way, not hardcoded.

---

## ADR-001 — Extraction: cloud vision LLM for the prototype, not template OCR

**Context:** Mill certs arrive with varying layouts (different mills/suppliers
format differently), varying scan/image quality, and sometimes span multiple
pages. A fixed-coordinate template extractor (crop this box, read that box)
only works for one known layout and breaks the moment a new supplier's cert
shows up.

**Decision:** For the prototype, send document pages to a cloud
vision-capable LLM (Claude) to read and extract fields — header data (order
no., PO no., supplier, customer, commodity, spec, cert no., date of issue)
and the line-item table (size, product no., heat no., quantity, weight,
chemical composition per row). This is paired with the human review gate
(ADR-003), so extraction mistakes are caught before they become data.

Tristan's stated preference is a **zero-cost, local** pipeline (Tesseract)
long-term, but explicitly chose to defer that for prototype speed
(2026-08-24): "if Tesseract is free and local once we go through setup I'm
happy to explore that... but for prototype maybe we put that aside and get a
proof of concept going more quickly."

**Consequences:** Prototype has a per-page API cost and a network dependency,
and documents (which may carry commercial/supplier data) leave the local
machine during extraction. Acceptable for proving the concept. **Do not
treat this as the final architecture** — the Tesseract swap is planned work,
not a rejected idea, and will need real layout-agnostic logic (table
detection, not fixed coordinates) to match what the LLM currently does for
free. Revisit once the extraction/review flow is proven end-to-end.

---

## Template for new entries

```
## ADR-00N — Short title

**Context:** What problem forced a decision.

**Decision:** What we chose, specifically.

**Consequences:** What this costs or constrains, and what it deliberately
leaves open.
```
