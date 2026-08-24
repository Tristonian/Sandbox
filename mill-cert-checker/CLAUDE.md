# CLAUDE.md — Mill Cert Checker

Guidance for any AI/human session working in this repo. Read this first,
then [`ADR.md`](ADR.md) (why things are built the way they are) and
[`NEXT-STEPS.md`](NEXT-STEPS.md) (current status, what's verified vs.
assumed, what's still open). [`README.md`](README.md) is just install/run
steps — don't duplicate it here.

## What this is, in one breath

A local Flask app that ingests mill test certificates (PDF/image), OCRs the
header fields and per-heat chemical composition table via local Tesseract
(free, offline, no API billing — ADR-012), checks each element against a
tolerance spec table (seeded with SAE10B21, ADR-002), and requires a human
to review, correct, and approve before anything is committed to SQLite
(ADR-003). Single branch (`main`), no deploy pipeline, no auth — a
local-only prototype for Tristan and Ewan.

## The one rule that matters most: the review gate is load-bearing

**Never add a path that writes to `documents`/`line_items` without going
through `apply_review_edits()` and an explicit Save or Approve action.**
ADR-003 exists because OCR on variable-quality scans *will* misread values —
this actually happened on the very first real test (a Carbon value read as
0.2414 instead of 0.2111, which would have been a false FAIL) — and the
whole point of this tool is that nothing reaches the record of truth
unreviewed. If a future task asks for "auto-approve" or "skip review for
trusted suppliers," that's a real product decision to bring to Tristan, not
something to build quietly because it seemed convenient.

## Known sharp edges — don't build on top of these assuming they're solved

- **Chemistry column order is assumed, not detected** (`CHEMISTRY_COLUMNS_DEFAULT`
  in `ocr_extract.py`), because OCR'ing the two-line stacked table header
  reliably enough to detect real column order didn't work out. Only tested
  against one supplier's layout (POSCO). A second real cert with a
  different column order will silently mismap values. See ADR-012.
- **Remove hard-deletes, including approved records, with no audit trail**
  (ADR-016). There is no soft-delete, no deletion log, no "who removed
  this and why." This was a deliberate trade for prototype speed with a
  two-person user base — revisit before this has more users or any
  compliance weight, per ADR-016's own closing note.
- **`spec_limits` has no source-of-truth verification.** The SAE10B21
  numbers came from cross-referencing secondary web sources (ADR-002), not
  a primary SAE J403 document. Treat as a reasonable seed, not certainty.
- **Size / Quantity / Weight / Product No. aren't editable** on the review
  form — only Heat No. and the chemistry values are. They also don't feed
  pass/fail, so this is lower priority, not forgotten.

## Working style this project has followed — keep doing this

- **State what's verified vs. assumed, explicitly, every time.** Every ADR
  entry that claims something works says exactly what was tested it
  against (usually: the one real POSCO sample document) and names the
  specific result, not "should work." Keep doing this — "the pass/fail
  check works" is a weaker and less useful claim than "correcting SF00180's
  Carbon from 0.2414 to 0.2111 flipped that row from FAIL to REVIEW,
  confirmed against the running app."
- **Every real decision gets an ADR entry**, in `ADR.md`, newest first,
  with Context / Decision / Consequences. Superseded entries stay in the
  file marked as superseded, not deleted — the history of *why something
  changed* is as valuable as the current state.
- **Test against the real sample document before claiming something
  works**, not just against mocked/synthetic data. This project has a
  known real sample cert (`Mill Sheet - LW 280076(N105263).pdf`, not
  committed to the repo — it's Tristan's local Downloads file) that every
  extraction/parsing change has been validated against directly, including
  running it through the live Flask server with `curl`, not just unit-level
  function calls.
- **Destructive actions on real data need explicit confirmation first.**
  A session testing the Remove-on-approved feature (2026-08-24) reused a
  real uploaded document as the test subject instead of creating a
  disposable one — that was a mistake, flagged to Tristan afterward rather
  than hidden. Create your own throwaway test uploads; don't repeat that.
- **`git push` is not auto-approved** — Claude Code's auto mode blocks it
  by default as a "visible to others" action, even mid-task. Commit
  locally, then ask before pushing, even if the user's phrasing earlier in
  the conversation sounded like blanket permission.

## File map

| File | Purpose |
|---|---|
| `app.py` | The whole Flask app — routes, DB schema (`init_db`), pass/fail logic (`check_chemistry`), the shared edit-apply helper (`apply_review_edits`) used by both Save and Approve. |
| `ocr_extract.py` | Tesseract-based extraction. Renders PDF/image pages, reconstructs physical lines with word-level bounding boxes, parses header fields + line items, generates the per-field/per-row source-image crops. |
| `templates/_base.html` | Shared layout, light/dark theme tokens + toggle, the RAG legend CSS. |
| `templates/index.html` | Upload (drag-and-drop) + pending/approved document lists. |
| `templates/review.html` | The review/edit screen — editable fields, source crops, live client-side recolor JS, Save/Approve/Remove actions. |
| `templates/data.html` | The flat approved-line-items table, with Open/Remove per row. |
| `millcert.db`, `uploads/` | Gitignored — local runtime state, not shipped. |
| `.env.example` | Currently unused by any code path (extraction is local OCR, no API key needed) — kept in case a cloud-vision fallback is ever added per ADR-012's closing note. |

## Session log

### 2026-08-24 — built end-to-end, from brainstorm to a working prototype on real data

Full arc in one session: brainstormed requirements interactively (layouts
vary, human review required, order↔cert is many-to-many at the heat level),
wrote `ADR.md`/`NEXT-STEPS.md` capturing every decision with reasoning
before writing code, then built and validated against the real sample
POSCO certificate at each step rather than against mocks.

Extraction pivoted twice, both times for real reasons, not speculation:
cloud vision LLM (ADR-001) → local Tesseract once it turned out Claude Pro
doesn't include API billing and Tristan wanted zero cost (ADR-012) → added
word-level bounding boxes so the review screen could show the exact source
crop next to each value (ADR-013), which **immediately surfaced a real OCR
misread** (Carbon: 0.2414 vs. true 0.2111) — direct validation that the
review-gate design (ADR-003) solves a real problem, not a hypothetical one.

Also shipped same-session: inline editing wired into the review form
(ADR-014), Save split from Approve (ADR-017), live client-side pass/fail
recoloring + a RAG legend, Remove extended from unreviewed-only to also
cover approved documents (ADR-016 — flags its own audit-trail gap
explicitly), light/dark theming, and a cross-platform `README.md` after
Tristan's friend Ewan wanted to run it on a Mac.

**Verified on the real document, not assumed:** header field extraction,
all 8 heats' chemistry extraction and pass/fail check, the source crop
feature, edit-and-recompute on both Save and Approve, and Remove on both
an unreviewed test upload and a real approved document.

**Not yet tried:** a second real certificate from a different
supplier/layout — the column-order assumption and header-regex patterns
are validated against exactly one document shape so far. That's the most
important next real-world test before trusting this on live incoming mail.

Repo pushed to `github.com/Tristonian/Sandbox` (private, shared with
Ewan) across two commits — see git log for the split.
