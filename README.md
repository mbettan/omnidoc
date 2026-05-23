# Omnidoc

> **Omnidoc transforms any ZIP archive into a single, structured, LLM-ready document — no matter what file types are inside.**

Data fed to Large Language Models today is fragmented: engineers manually extract text from PDFs, copy-paste spreadsheet tabs, screenshot images, and stitch everything together before passing it to a model. **Omnidoc eliminates that friction.**

Given a ZIP archive, Omnidoc automatically detects every file type inside, applies the appropriate extraction strategy (native parsing, table serialization, or OCR), and emits a single clean Markdown file — or PDF — that any LLM can ingest directly.

---

## 🌟 Key Features

- **Multi-Format Ingestion:** Seamlessly extracts content from PDFs, Excel spreadsheets, CSVs/TSVs, Word documents, PowerPoints, Images (via OCR), and Source Code.
- **Recursive Archive Manifest (v1.1):** Generates a beautifully structured metadata table at the very top of the bundle, mapping out every single folder, file, ignored dotfile, or skipped metadata entry inside the ZIP. Displays names, types, raw and compressed sizes, and date modified timestamps.
- **Explicit Media & Unsupported Skipping:** Safely blocks heavy video/audio formats (e.g., `.mp4`, `.mov`, `.mp3`, `.wav`) from exhausting CPU resources. Emits a concise, informative inline skip block showing the bypassed extension: e.g., `_[unsupported file type (.mp4) — skipped]_`.
- **Zero Pre-processing Required:** Point Omnidoc directly at raw, nested ZIP archives. It automatically handles directory recursion, filters out macOS metadata (`__MACOSX`, `.DS_Store`), and prunes hidden folders (except allowed directories like `.github` configurations).
- **Production-Grade Hardening:** 
  - **Zip Bomb Protection:** Rejects oversized entries based on declared uncompressed size and enforces bounded reads to prevent memory exhaustion.
  - **ReportLab XML Crash Safety:** Automatically escapes extracted code blocks and table cells to guarantee robust PDF rendering.
  - **Extensionless Doc Sniffing:** Intelligently identifies and extracts plain-text documentation files (e.g., `README`, `LICENSE`, `Dockerfile.dev`).
  - **Zero-Byte Safety:** Short-circuits empty files to prevent internal parser exceptions across all dependencies.
- **Ergonomics & Usability:**
  - **Global CLI (`omnidoc`):** Fully packaged via `pyproject.toml`.
  - **Visual Progress Bar:** Real-time status tracking via `tqdm`.
  - **Token Capping:** `--max-tokens` flag with fast 4-chars/token heuristic.
  - **PDF Page Truncation:** `--max-pdf-pages` flag to cap large documents.
  - **Plain-Text Minimal Mode:** `--format txt` option for token-minimal outputs.

---

## 🏆 Why Markdown (`.md`) is the Winner for LLMs

When preparing document bundles for Large Language Models (like GPT-4o, Claude 3.5 Sonnet, or Gemini 2.5 Pro), **Markdown (`.md`) is the absolute gold standard and highly recommended.**

### 1. Maximum Token Efficiency (Cheaper & Faster)
Markdown is pure UTF-8 text with minimal formatting overhead. It consumes significantly fewer tokens than PDF ingestion, resulting in much faster API response times and lower billing costs.

### 2. Flawless Structural Context
LLMs are trained extensively on Markdown. They perfectly understand semantic hierarchy (`#` for Title, `##` for Section, `###` for Sub-section), bulleted lists, code blocks, and Markdown tables (`| --- |`). This structure gives the model pristine context about where one file ends and another begins.

### 3. Zero Extraction Loss
When you upload a PDF to an LLM, the model’s backend must convert that PDF back into text (via OCR or internal PDF parsers). This conversion frequently introduces garbled text, dropped table columns, or misaligned paragraphs. Passing Markdown bypasses this entirely—the model ingests the exact text directly.

---

## 📄 When should you use PDF (`.pdf`)?

You should only use Omnidoc’s optional `--pdf` flag in three specific scenarios:

1. **Human-in-the-Loop Review:** If a human lawyer, analyst, or developer needs to read and review the exact same consolidated bundle alongside the LLM, a paginated PDF provides a vastly superior reading experience.
2. **Multimodal Vision Models:** If you want an advanced multimodal model (like Gemini 2.5 Pro) to physically "see" the visual layout or formatting of the document bundle.
3. **Legacy Enterprise RAG Pipelines:** Some corporate document ingestion tools and RAG (Retrieval-Augmented Generation) databases only accept `.pdf` files as inputs.

---

## 📦 Installation & Quick Start

Omnidoc requires Python 3.10+ and manages builds modernly using **setuptools/pip**.

### Step 1: Clone the Repository
```bash
# Clone repository
git clone https://github.com/mbettan/omnidoc.git
cd omnidoc
```

### Step 2: Install Locally (Editable Mode)
Provision a virtual environment and install core package and command dependencies:

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in editable mode with core dependencies
pip install -e .

# Install with all optional dependency bundles (OCR, PDF, Gemini Fallbacks)
pip install -e ".[all]"
```

### Step 3: Installing System OCR Engines (Optional)
To enable local OCR fallbacks and page conversions, configure poppler and tesseract:

```bash
# macOS (Homebrew)
brew install tesseract poppler

# Ubuntu / Debian
sudo apt update && sudo apt install tesseract-ocr poppler-utils
```

---

## 🚀 Usage & Examples

Once installed locally, the `omnidoc` console command will map globally inside the virtual environment.

```bash
# Basic Usage — recursively walks data.zip and creates data_llm.md
omnidoc data.zip

# Custom Output & Parallel PDF rendering
omnidoc data.zip -o final_report --pdf

# Process with selective PDF page constraints & custom token budget capping
omnidoc data.zip --max-pdf-pages 15 --max-tokens 150000

# Silent Execution Mode for Automated Pipelines
omnidoc data.zip --no-progress --quiet
```

### CLI Options

| Flag | Default | Description |
| :--- | :--- | :--- |
| `zip_file` | *Required* | Path to the input `.zip` archive. |
| `-o`, `--output BASE` | `<zip>_llm` | Base name for output file(s) (without extension). |
| `--pdf` | `False` | Also render and export an LLM-ready PDF version. |
| `--format {md,txt}` | `md` | Output format: `md` (rich markdown) or `txt` (token-minimal). |
| `--max-file-mb N` | `100` | Per-file uncompressed size cap in MB to prevent Zip bombs. |
| `--max-pdf-pages N` | `100` | Maximum number of pages extracted per PDF. |
| `--max-tokens N` | unlimited | Total bundle token budget (~4 chars/token heuristic). |
| `--no-progress` | `False` | Disable visual progress bar. |
| `--no-visual-bundle` | `False` | Disable companion visual PDF generation and page-slicing. |
| `--ocr-min-confidence N` | `60` | Tesseract confidence threshold (0-100) below which visual content is bundled. |
| `--visual-max-dim N` | `1600` | Maximum pixel dimension for visual bundle JPEG images. |
| `--visual-quality N` | `75` | JPEG compression quality (10-100) for visual bundle images. |
| `--vision-fallback {none,gemini}` | `none` | Enable cloud vision model fallback (requires `PROJECT_ID` env var). |
| `--text-page-min-chars N` | `15` | Character threshold below which a PDF page is classified as image-only. |
| `--ocr-render-dpi N` | `200` | DPI resolution used during selective Poppler page rendering. |
| `-q`, `--quiet` | `False` | Suppress non-error output. |
| `-V`, `--version` | `False` | Show version information (`omnidoc 1.1.0`). |

### Environment Variables

When using `--vision-fallback gemini`, configure the following environment variables in your terminal:

- `PROJECT_ID` (*Required*): The Google Cloud Platform (GCP) project ID utilized for Vertex AI billing and access.
- `OMNIDOC_VISION_MODEL` (*Optional*, default: `gemini-3.1-pro-preview`): The target Gemini vision model utilized for visual analysis.

#### Authentication Setup
The Google Cloud GenAI client utilizes Application Default Credentials (ADC) to authorize requests locally. Set this up with:
```bash
# Authenticate local application environment
gcloud auth application-default login
```

---

## 📊 Supported File Formats

| Category | Extensions | Extraction Strategy |
| :--- | :--- | :--- |
| **PDF** | `.pdf` | Text + table extraction via `pdfplumber` and `pypdf`; OCR fallback for scanned pages. |
| **Images** | `.jpg`, `.png`, `.webp`, `.tiff`, `.bmp`, `.gif` | OCR text extraction via `pytesseract` and Pillow. |
| **Spreadsheets** | `.xlsx`, `.xlsm` | Multi-sheet extraction to GitHub-flavored Markdown tables via `openpyxl`. |
| **Legacy Spreadsheets**| `.xls` | Deprecated binary spreadsheets explicitly skipped with converting warnings. |
| **Word Docs** | `.docx` | Heading hierarchy, paragraphs, and embedded tables via `python-docx`. |
| **Legacy Word Docs** | `.doc` | Deprecated binary documents explicitly skipped with converting warnings. |
| **PowerPoint** | `.pptx` | Slide-by-slide text shape extraction via `python-pptx`. |
| **Legacy PowerPoints** | `.ppt` | Deprecated binary slide shows explicitly skipped with converting warnings. |
| **Text & Code** | `.txt`, `.md`, `.json`, `.xml`, `.py`, `.js`, `.sql`, etc. | UTF-8/Latin-1 decoding; pretty-printed JSON; stripped HTML; Markdown code fences. |
| **Extensionless** | `README`, `LICENSE`, `Makefile`, `Dockerfile` | Heuristic byte-sniffing and regex matching to extract plain-text docs. |
| **Unsupported** | Any other format | Inline skip notice emitted to preserve extraction continuity. |

---

## 🧪 Running the Test Suite

Omnidoc includes a rigorous 269-test suite covering unit, integration, path traversal, and Zip bomb security scenarios.

```bash
# Ensure dev dependencies are installed
pip install -e ".[dev]"

# Run full test suite verbosely
pytest tests/ -v

# Run tests with coverage reporting
pytest tests/ -v --cov=zip_to_llm --cov-report=term-missing
```

---

## 🏗️ Architecture Overview

Omnidoc is architected around a robust **Format Router (`EXT_MAP`)** that decouples extraction logic into isolated format handlers.

```
[ Input .zip Archive ]
         │
         ▼
[ ZIP Walker / Metadata Filter ] ── (Prunes hidden folders & macOS metadata)
         │
         ▼
[ Bounded Size Validator ] ──────── (Rejects Zip bombs > 100 MB)
         │
         ▼
[ Format Router (EXT_MAP) ] ─────── (Resolves extension or sniffs extensionless docs)
         │
         ├────────────────────────┬────────────────────────┬────────────────────────┐
         ▼                        ▼                        ▼                        ▼
[ extract_pdf() ]        [ extract_excel() ]      [ extract_docx() ]       [ extract_text() ]
(Text + Tables + OCR)    (Multi-Sheet MD Tables)  (Headings + Tables)      (Clean Text + Fences)
         │                        │                        │                        │
         └────────────────────────┴───────────┬────────────┴────────────────────────┘
                                              │
                                              ▼
                               [ Markdown Assembler ]
                                              │
                                              ├────────────────────────┐
                                              ▼                        ▼
                                   [ bundle_llm.md ]        [ bundle_llm.pdf ]
                                                             (Rendered via ReportLab)
```

---

## 📄 License

Omnidoc is classified as open source software and licensed under the **Apache License 2.0**.
