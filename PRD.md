# Omnidoc — Product Requirements Document

**Version:** 1.1.0
**Status:** Final
**Date:** May 2026
**Classification:** Open Source (Apache License 2.0)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Non-Goals](#3-goals--non-goals)
4. [User Stories](#4-user-stories)
5. [Functional Requirements](#5-functional-requirements)
6. [Non-Functional Requirements](#6-non-functional-requirements)
7. [Architecture Overview](#7-architecture-overview)
8. [Milestones & Roadmap](#8-milestones--roadmap)
9. [Open Questions](#9-open-questions)
10. [Appendix](#10-appendix)

---

## 1. Executive Summary

> Omnidoc transforms any ZIP archive into a single, structured, LLM-ready document — no matter what file types are inside.

Data fed to large language models today is fragmented: engineers manually extract text from PDFs, copy-paste spreadsheet tabs, screenshot images, and stitch everything together before passing it to a model. Omnidoc eliminates that friction.

Given a ZIP archive, Omnidoc automatically detects every file type inside, applies the appropriate extraction strategy (native parsing, table serialisation, or OCR), and emits a single clean Markdown file — or PDF — that any LLM can ingest directly.

---

## 2. Problem Statement

### 2.1 Context

LLMs accept text. Real-world data lives in heterogeneous archives: PDFs with embedded images, multi-sheet Excel files, scanned documents, PowerPoint decks, CSVs, Word reports, and raw code files — all zipped together and handed to a developer or analyst.

Today's ad-hoc pipeline for this is error-prone and time-consuming:

- Manual file-by-file extraction with no consistent format
- Excel sheets silently dropped when only the active tab is copied
- Scanned PDFs passed as binary blobs with no OCR
- Images ignored entirely
- No record of which file a piece of context came from

### 2.2 Pain Points

| Pain Point                   | Impact | Current Workaround    |
| ---------------------------- | ------ | --------------------- |
| Multi-format ZIP ingestion   | High   | Manual, one-by-one    |
| Excel multi-sheet extraction | High   | Copy active tab only  |
| Image / scanned PDF content  | High   | Ignored or manual OCR |
| Provenance tracking          | Medium | None                  |
| Reproducible pipeline        | Medium | Ad-hoc scripts        |

---

## 3. Goals & Non-Goals

### 3.1 Goals

- Accept any ZIP archive as input with zero pre-processing required
- Extract readable text from every major file type automatically
- Preserve structure: Excel sheet names, PDF page numbers, slide numbering
- Emit a single Markdown file with a table of contents and clear file separators
- Optionally render that Markdown as a PDF for LLMs that prefer document inputs
- Run entirely offline with no external API calls (with optional cloud fallback)
- Be installable with a single `pip install -e .` command

### 3.2 Non-Goals

- Real-time / streaming processing of live data sources
- UI or web application (CLI-first for v1)
- Audio or video transcription (handled via graceful skips in v1)
- Password-protected ZIP or encrypted file extraction
- Cloud storage integration (S3, GDrive) — planned for v2

---

## 4. User Stories

| ID    | As a…           | I want to…                                        | So that…                                       |
| ----- | --------------- | ------------------------------------------------- | ---------------------------------------------- |
| US-01 | Data analyst    | Feed a ZIP of quarterly reports to an LLM         | I can ask questions across all reports at once |
| US-02 | Developer       | Preprocess a client data dump automatically       | I don't hand-craft extraction code each time   |
| US-03 | Researcher      | Include scanned PDFs and images in my LLM context | No information is silently dropped             |
| US-04 | Product manager | Pass a ZIP of Excel trackers to a model           | All sheets are included, not just the first    |
| US-05 | DevOps / ML Eng | Integrate Omnidoc into a data pipeline               | Ingestion is automated and reproducible        |

---

## 5. Functional Requirements

### 5.1 Input

- Accept a single `.zip` file as the primary input argument
- Validate the file is a well-formed ZIP before processing
- Recursively process nested directories within the ZIP
- Skip macOS metadata entries (`__MACOSX`, `.DS_Store`)
- Skip dot-prefixed files/directories except allowed directories like `.github` if configured

### 5.2 File Type Support

| Category    | Extensions                                          | Extraction Method                                                  |
| ----------- | --------------------------------------------------- | ------------------------------------------------------------------ |
| PDF         | `.pdf`                                              | pdfplumber text + table extraction; OCR fallback for scanned pages |
| Images      | `.jpg` `.jpeg` `.png` `.bmp` `.tiff` `.gif` `.webp` | Tesseract OCR → extracted text; Optional cloud Gemini fallback     |
| Excel       | `.xlsx` `.xlsm` `.xls`                              | openpyxl for `.xlsx`/`.xlsm`; legacy `.xls` unsupported warning   |
| CSV / TSV   | `.csv` `.tsv`                                       | Python csv module → Markdown table                                 |
| Word        | `.docx` `.doc`                                      | python-docx for `.docx`; legacy `.doc` unsupported warning         |
| PowerPoint  | `.pptx` `.ppt`                                      | python-pptx for `.pptx`; legacy `.ppt` unsupported warning         |
| Text / Code | `.txt` `.md` `.json` `.xml` `.html` `.py` `.js` …   | UTF-8 decode; JSON pretty-printed; HTML stripped                   |
| Unsupported | (any other)                                         | Noted as skipped; no crash                                         |

### 5.3 Output

- Primary output: a `.md` file (UTF-8 encoded Markdown) or `.txt` file
- Optional output: a PDF rendition via the `--pdf` flag
- Companion Visual PDF: generated automatically (unless disabled by `--no-visual-bundle`), bundling all low-confidence or unextractable visual elements into a separate optimized `<output_base>_visual.pdf` file with stable anchors (e.g., `visual-0001`) referenced inside the primary markdown/text.
- Output structure:
  - Document title block with source archive name
  - Archive Manifest: A comprehensive, recursively generated list of all folders and files inside the ZIP (including those skipped or unsupported), formatted as a clean Markdown structure detailing each entry's metadata (File Path, Type, Raw Size, Uncompressed/Compressed Size, Modified Date, etc.).
  - File count and table of contents (linked file names)
  - One section per file, separated by horizontal rules
  - Each section: file path, type label, byte size, extracted content
- Collapse 3+ consecutive blank lines to preserve readability
- Tables serialised as GitHub-flavoured Markdown tables (or plain spacing tables in `.txt` mode)

### 5.4 CLI Interface

```
omnidoc <input.zip> [-o OUTPUT_BASE] [--pdf] [--format md|txt] [--max-file-mb MAX_MB]
                    [--max-pdf-pages N] [--max-tokens N] [--no-progress] [--quiet]
                    [--no-visual-bundle] [--ocr-min-confidence CONF]
                    [--visual-max-dim DIM] [--visual-quality Q]
                    [--vision-fallback none|gemini] [--text-page-min-chars N]
                    [--ocr-render-dpi DPI] [-V]
```

| Argument | Type | Default | Description |
| --- | --- | --- | --- |
| `zip_file` | positional | — | Path to input `.zip` archive |
| `-o` / `--output` | optional | `<zip_name>_llm` | Base name for output file(s) (no extension) |
| `--pdf` | flag | off | Also render and save a PDF version |
| `--format` | choice | `md` | Output format: `md` (rich Markdown) or `txt` (token-minimal) |
| `--max-file-mb` | optional | 100 | Per-file uncompressed size cap in MB |
| `--max-pdf-pages` | optional | 100 | Maximum number of pages extracted per PDF |
| `--max-tokens` | optional | None | Cap output at approximately N tokens |
| `--no-progress` | flag | off | Disable progress bar |
| `-q` / `--quiet` | flag | off | Suppress non-error output |
| `--no-visual-bundle` | flag | off | Disable companion visual bundle PDF |
| `--ocr-min-confidence` | optional | 60 | Tesseract confidence threshold (0-100) |
| `--visual-max-dim` | optional | 1600 | Max pixel dimension for visual bundle images |
| `--visual-quality` | optional | 75 | JPEG compression quality (10-100) |
| `--vision-fallback` | choice | `none` | Cloud vision fallback model: `none` or `gemini` |
| `--text-page-min-chars` | optional | 15 | Min characters for a PDF page to be text-only |
| `--ocr-render-dpi` | optional | 200 | DPI resolution for selective PDF page rendering |
| `-V` / `--version` | flag | off | Show program version and exit |

### 5.5 Error Handling

- **Non-existent input file:** exit with clear error message (code 1)
- **Invalid ZIP:** exit with clear error message (code 1)
- **Per-file extraction failure:** emit inline error note, continue processing remaining files
- **Unsupported encoding:** try UTF-8, latin-1, cp1252 in sequence before failing gracefully
- **Missing optional dependency** (e.g. python-pptx): note in output, do not crash

---

## 6. Non-Functional Requirements

| Category        | Requirement                                                                        |
| --------------- | ---------------------------------------------------------------------------------- |
| Performance     | Process a 50 MB ZIP containing 100 files in under 60 seconds on commodity hardware |
| Reliability     | Zero unhandled exceptions; all failures are caught and reported inline             |
| Portability     | Run on macOS, Linux, and Windows with Python 3.10+                                 |
| Dependency mgmt | All Python deps installable via pip; Tesseract only required for OCR features      |
| Output quality  | LLM context window should require no further preprocessing after Omnidoc output       |
| Extensibility   | Adding a new file type requires registering one function in `EXT_MAP`              |

---

## 7. Architecture Overview

### 7.1 Module Structure

| Component                 | Responsibility                                              |
| ------------------------- | ----------------------------------------------------------- |
| CLI (`main()`)            | Argument parsing, input validation, output coordination     |
| ZIP walker                | Iterates ZIP entries, filters metadata, calls router        |
| Format router (`EXT_MAP`) | Maps file extension → extractor function                    |
| Extractor: PDF            | pdfplumber text + table; pdf2image + Tesseract OCR fallback |
| Extractor: Image          | PIL open → Tesseract OCR; optional Gemini fallbacks         |
| Extractor: Excel          | openpyxl → per-sheet Markdown tables                        |
| Extractor: CSV/TSV        | csv.reader → Markdown table                                 |
| Extractor: DOCX           | python-docx paragraphs and embedded tables                  |
| Extractor: PPTX           | python-pptx slide text shapes                               |
| Extractor: Text           | Decode + optional JSON/HTML normalisation                   |
| OutputFormatter           | Switches markdown decorations on/off based on output format|
| Markdown assembler        | Joins all sections with separators and metadata headers     |
| PDF renderer              | ReportLab Platypus: renders Markdown as paginated PDF       |

### 7.2 Dependencies

| Library       | Version | Purpose                          |
| ------------- | ------- | -------------------------------- |
| pdfplumber    | ≥0.9    | PDF text and table extraction    |
| pypdf         | ≥4.0    | PDF metadata & Visual Bundling   |
| pdf2image     | ≥1.16   | PDF → image (OCR fallback)       |
| pytesseract   | ≥0.3    | OCR wrapper for Tesseract        |
| Pillow        | ≥10.0   | Image loading and pre-processing |
| openpyxl      | ≥3.1    | Excel read                       |
| python-docx   | ≥1.1    | Word document parsing            |
| python-pptx   | ≥0.6    | PowerPoint parsing               |
| reportlab     | ≥4.0    | PDF rendering                    |
| tqdm          | ≥4.66   | CLI Progress Reporting           |
| google-genai  | ≥0.1    | Vertex AI / Gemini fallback SDK  |
| tesseract-ocr | 5.x     | System OCR engine (non-Python)   |

---

## 8. Milestones & Roadmap

### 8.1 v1.0 & v1.1 — Implemented & Released

- **Omnidoc CLI Engine:** Full multi-format extraction support (PDF, XLSX, DOCX, PPTX, CSV, TSV, Images, Code, HTML).
- **Packaging & Console Script:** Modern packaging with `pyproject.toml` exposing global `omnidoc` CLI command.
- **Progress bar:** Real-time interactive extraction progress bar using `tqdm`.
- **Token Capping:** `--max-tokens` flag with fast token-count estimation (CHARS_PER_TOKEN=4 heuristic).
- **PDF Extraction Capping:** `--max-pdf-pages` flag to cap large PDF document processing.
- **Minimal Plain-Text Mode:** `--format txt` with clean spacing tables, no fences/markdown blocks.
- **Archive Manifest & Title blocks:** In-depth recursive directory table including skipped and folder metadata.

### 8.2 v1.2 — Short Term

- **Selective dotfile allowlist:** Allow extraction of dotfiles/folders under specific white-lists like `.github/`.
- **Legacy format conversion options:** Provide options to call system conversion tools for binary format types (`.doc`, `.xls`, `.ppt`).

### 8.3 v2.0 — Medium Term

- Python library API: `from omnidoc import extract_zip`
- Cloud inputs: `s3://` and `gs://` URI support
- Streaming output: yield section-by-section for real-time consumption
- Structured JSON output mode for programmatic downstream use

---

## 9. Open Questions

| #     | Question                                                               | Owner   | Status |
| ----- | ---------------------------------------------------------------------- | ------- | ------ |
| OQ-01 | Should Omnidoc support password-protected ZIPs?                         | Product | Open   |
| OQ-02 | What is the acceptable maximum output file size?                       | Eng     | Open   |
| OQ-03 | Should nested ZIPs inside the archive be recursively expanded?         | Eng     | Open   |
| OQ-04 | Is a `--chunk-size` flag needed to split output into LLM-sized window? | Product | Open   |
| OQ-05 | Should audio/video transcription (via Whisper) be in scope?           | Product | Closed (Planned for v2) |
| OQ-06 | dotfile skipping exceptions (e.g. `.github`)                           | Product | Closed (Support `.github` selective allowlisting in v1.2) |

---

## 10. Appendix

### Sample Output Structure

```markdown
# LLM Document Bundle

**Source archive:** `data.zip`
**Files found:** 3

## Archive Directory Manifest

Below is a complete recursive manifest listing all folders, files, and metadata found within the source ZIP archive:

| Entry Path | Type | Compressed Size | Uncompressed Size | Date Modified |
| --- | --- | --- | --- | --- |
| report.pdf | File (PDF Document) | 38,210 bytes | 42,310 bytes | 2026-05-20 14:30:00 |
| data.xlsx | File (Excel Spreadsheet) | 12,110 bytes | 18,240 bytes | 2026-05-20 14:32:15 |
| record.mp4 | File (Video) | 12,310,000 bytes | 12,305,000 bytes | 2026-05-20 14:35:00 |

## Table of Contents

- `report.pdf`
- `data.xlsx`
- `record.mp4`

---

## File: `report.pdf`

**Type:** PDF Document | **Size:** 42,310 bytes

### Page 1

Executive summary text...

---

## File: `data.xlsx`

**Type:** Excel Spreadsheet | **Size:** 18,240 bytes

#### Sheet: Sales

| Month | Revenue | Units |
| ----- | ------- | ----- |
| Jan   | 10000   | 150   |

---

## File: `record.mp4`

**Type:** Video | **Size:** 12,305,000 bytes

_[unsupported file type (.mp4) — skipped]_
```

### Installation

```bash
# Install dependencies locally as editable package
pip install -e .

# Optional packages for OCR/PDF/AI features
pip install -e .[all]

# System OCR engine
brew install tesseract poppler          # macOS
apt install tesseract-ocr poppler-utils  # Ubuntu / Debian
```
