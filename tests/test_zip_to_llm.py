#!/usr/bin/env python3
"""
Test suite for zip_to_llm.py (Omnidoc).

Run:
    pytest test_zip_to_llm.py -v
    pytest test_zip_to_llm.py -v --cov=zip_to_llm --cov-report=term-missing
"""

import io
import json
import os
import sys
import zipfile
from pathlib import Path
from unittest import mock

import pytest

# Ensure src/ is in sys.path so we can import zip_to_llm
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import zip_to_llm as ztl


# ===========================================================================
# Fixtures
# ===========================================================================
@pytest.fixture
def tmp_zip(tmp_path):
    """Factory: builds a ZIP from a {name: bytes} dict and returns its path."""
    def _make(entries: dict, name: str = "test.zip") -> Path:
        zpath = tmp_path / name
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, content in entries.items():
                if isinstance(content, str):
                    content = content.encode("utf-8")
                zf.writestr(fname, content)
        return zpath
    return _make


@pytest.fixture
def sample_csv_bytes():
    return b"name,age,city\nAlice,30,Paris\nBob,25,Lyon\n"


@pytest.fixture
def sample_json_bytes():
    return b'{"user":"alice","items":[1,2,3]}'


@pytest.fixture
def sample_html_bytes():
    return b"<html><body><h1>Title</h1><p>Hello <b>world</b></p></body></html>"


# ===========================================================================
# 1. should_skip() — path filtering
# ===========================================================================
class TestShouldSkip:
    def test_skips_macosx_metadata(self):
        assert ztl.should_skip("__MACOSX/foo.txt") is True

    def test_skips_ds_store(self):
        assert ztl.should_skip("folder/.DS_Store") is True

    def test_skips_dotfile_at_root(self):
        assert ztl.should_skip(".hidden") is True

    def test_skips_directory_entry(self):
        assert ztl.should_skip("folder/") is True

    def test_skips_file_in_hidden_dir(self):
        """[HARDENING-D] Files inside hidden dirs must be skipped."""
        assert ztl.should_skip(".git/config") is True
        assert ztl.should_skip(".idea/workspace.xml") is True
        assert ztl.should_skip("project/.venv/lib/foo.py") is True

    def test_keeps_normal_file(self):
        assert ztl.should_skip("docs/readme.md") is False

    def test_keeps_root_file(self):
        assert ztl.should_skip("data.csv") is False

    def test_keeps_file_with_dot_in_middle(self):
        assert ztl.should_skip("file.name.txt") is False


# ===========================================================================
# 2. decode_bytes() — encoding fallback chain
# ===========================================================================
class TestDecodeBytes:
    def test_decodes_utf8(self):
        assert ztl.decode_bytes("héllo".encode("utf-8")) == "héllo"

    def test_decodes_latin1(self):
        # 0xe9 = é in latin-1, invalid as solo byte in UTF-8
        result = ztl.decode_bytes(b"caf\xe9")
        assert "caf" in result

    def test_decodes_cp1252(self):
        # 0x92 = right single quote in cp1252
        result = ztl.decode_bytes(b"it\x92s")
        assert "it" in result and "s" in result

    def test_handles_empty_bytes(self):
        assert ztl.decode_bytes(b"") == ""

    def test_never_raises(self):
        # Throw arbitrary garbage — should never raise
        garbage = bytes(range(256))
        result = ztl.decode_bytes(garbage)
        assert isinstance(result, str)


# ===========================================================================
# 3. looks_like_text() — content sniffing
# ===========================================================================
class TestLooksLikeText:
    def test_recognises_ascii_text(self):
        assert ztl.looks_like_text(b"Hello world\nThis is text.") is True

    def test_recognises_utf8_text(self):
        assert ztl.looks_like_text("café résumé naïve".encode("utf-8")) is True

    def test_rejects_null_bytes(self):
        assert ztl.looks_like_text(b"text\x00more") is False

    def test_rejects_empty(self):
        assert ztl.looks_like_text(b"") is False

    def test_rejects_binary_blob(self):
        binary = bytes([0, 1, 2, 3, 255, 254, 253] * 100)
        assert ztl.looks_like_text(binary) is False

    def test_accepts_source_code(self):
        code = b"def foo(x):\n    return x + 1\n"
        assert ztl.looks_like_text(code) is True


# ===========================================================================
# 4. md_table() — Markdown table generation
# ===========================================================================
class TestMdTable:
    def test_empty_rows_returns_empty(self):
        assert ztl.md_table([]) == ""

    def test_basic_table(self):
        out = ztl.md_table([["a", "b"], ["1", "2"]])
        assert "| a | b |" in out
        assert "| --- | --- |" in out
        assert "| 1 | 2 |" in out

    def test_normalizes_uneven_widths(self):
        out = ztl.md_table([["a", "b", "c"], ["1"]])
        lines = out.splitlines()
        # all rows should have 3 columns (4 pipes)
        assert all(line.count("|") == 4 for line in lines)

    def test_escapes_pipes_in_cells(self):
        out = ztl.md_table([["col"], ["a|b"]])
        assert "a\\|b" in out

    def test_strips_newlines_in_cells(self):
        out = ztl.md_table([["col"], ["line1\nline2"]])
        assert "\n" not in out.split("\n")[2]  # no newline within data row
        assert "line1 line2" in out

    def test_handles_none_cells(self):
        out = ztl.md_table([["a"], [None]])
        assert "|  |" in out


# ===========================================================================
# 5. strip_html() — HTML to text
# ===========================================================================
class TestStripHtml:
    def test_strips_tags(self):
        assert "Hello" in ztl.strip_html("<p>Hello</p>")
        assert "<p>" not in ztl.strip_html("<p>Hello</p>")

    def test_handles_nested(self):
        out = ztl.strip_html("<div><p>A <b>B</b> C</p></div>")
        assert "A" in out and "B" in out and "C" in out

    def test_handles_malformed_html(self):
        # Should not raise
        assert isinstance(ztl.strip_html("<div><p>unclosed"), str)


# ===========================================================================
# 6. collapse_blank_lines()
# ===========================================================================
class TestCollapseBlankLines:
    def test_collapses_three_or_more(self):
        assert ztl.collapse_blank_lines("a\n\n\n\nb") == "a\n\nb"

    def test_keeps_double_blank(self):
        assert ztl.collapse_blank_lines("a\n\nb") == "a\n\nb"

    def test_keeps_single_newline(self):
        assert ztl.collapse_blank_lines("a\nb") == "a\nb"


# ===========================================================================
# 7. Extractors — empty input handling [HARDENING-E]
# ===========================================================================
class TestExtractorsEmptyInput:
    """Every extractor must short-circuit on empty bytes."""

    def test_pdf_empty(self):
        assert ztl.extract_pdf(b"", "x.pdf") == "_[empty file]_"

    def test_image_empty(self):
        assert ztl.extract_image(b"", "x.png") == "_[empty file]_"

    def test_excel_empty(self):
        assert ztl.extract_excel(b"", "x.xlsx") == "_[empty file]_"

    def test_csv_empty(self):
        assert ztl.extract_csv(b"", "x.csv") == "_[empty file]_"

    def test_tsv_empty(self):
        assert ztl.extract_tsv(b"", "x.tsv") == "_[empty file]_"

    def test_docx_empty(self):
        assert ztl.extract_docx(b"", "x.docx") == "_[empty file]_"

    def test_pptx_empty(self):
        assert ztl.extract_pptx(b"", "x.pptx") == "_[empty file]_"

    def test_text_empty(self):
        assert ztl.extract_text(b"", "x.txt") == "_[empty file]_"


# ===========================================================================
# 8. extract_text() — content branches
# ===========================================================================
class TestExtractText:
    def test_plain_text(self):
        assert "hello world" in ztl.extract_text(b"hello world", "a.txt")

    def test_markdown_passthrough(self):
        out = ztl.extract_text(b"# Title\nbody", "a.md")
        assert out == "# Title\nbody"

    def test_json_pretty_printed(self, sample_json_bytes):
        out = ztl.extract_text(sample_json_bytes, "a.json")
        assert "```json" in out
        assert '"user": "alice"' in out  # pretty-printed with space

    def test_invalid_json_falls_back_to_raw(self):
        out = ztl.extract_text(b"{not valid", "a.json")
        assert "```json" in out
        assert "{not valid" in out

    def test_html_stripped(self, sample_html_bytes):
        out = ztl.extract_text(sample_html_bytes, "a.html")
        assert "<h1>" not in out
        assert "Title" in out

    def test_code_in_fence(self):
        out = ztl.extract_text(b"def f(): pass", "a.py")
        assert out.startswith("```python")
        assert out.endswith("```")

    def test_xml_in_fence(self):
        out = ztl.extract_text(b"<root/>", "a.xml")
        assert out.startswith("```xml")


# ===========================================================================
# 9. extract_csv() — CSV/TSV behaviour
# ===========================================================================
class TestExtractCsv:
    def test_basic_csv(self, sample_csv_bytes):
        out = ztl.extract_csv(sample_csv_bytes, "a.csv")
        assert "| name | age | city |" in out
        assert "| Alice | 30 | Paris |" in out

    def test_tsv(self):
        data = b"a\tb\n1\t2\n"
        out = ztl.extract_tsv(data, "a.tsv")
        assert "| a | b |" in out
        assert "| 1 | 2 |" in out

    def test_csv_with_only_header(self):
        out = ztl.extract_csv(b"col1,col2", "a.csv")
        assert "| col1 | col2 |" in out


# ===========================================================================
# 10. route() — extension and sniff dispatch
# ===========================================================================
class TestRoute:
    def test_known_extension_dispatch(self):
        label, fn = ztl.route("file.pdf")
        assert label == "PDF Document"
        assert fn is ztl.extract_pdf

    def test_case_insensitive_extension(self):
        label, fn = ztl.route("FILE.PDF")
        assert fn is ztl.extract_pdf

    def test_unknown_extension_routes_unsupported(self):
        label, fn = ztl.route("file.xyz")
        assert fn is ztl.extract_unsupported

    def test_known_extensionless_filename_readme(self):
        """[HARDENING-C] README should route to text extractor."""
        label, fn = ztl.route("README")
        assert fn is ztl.extract_text

    def test_known_extensionless_dockerfile(self):
        label, fn = ztl.route("Dockerfile")
        assert fn is ztl.extract_text

    def test_known_extensionless_makefile(self):
        label, fn = ztl.route("Makefile")
        assert fn is ztl.extract_text

    def test_dockerfile_with_suffix(self):
        label, fn = ztl.route("Dockerfile.dev")
        assert fn is ztl.extract_text

    def test_extensionless_with_text_peek(self):
        """Unknown extensionless file, sniff says 'text' → extract_text."""
        peek = lambda n: b"Hello, this is plain text content."
        label, fn = ztl.route("MYSTERY", peek=peek)
        assert fn is ztl.extract_text

    def test_extensionless_with_binary_peek(self):
        """Unknown extensionless file, sniff says 'binary' → unsupported."""
        peek = lambda n: bytes([0, 1, 2, 3, 0, 0, 255])
        label, fn = ztl.route("MYSTERY", peek=peek)
        assert fn is ztl.extract_unsupported

    def test_peek_failure_falls_back_to_unsupported(self):
        def bad_peek(n):
            raise IOError("boom")
        label, fn = ztl.route("MYSTERY", peek=bad_peek)
        assert fn is ztl.extract_unsupported


# ===========================================================================
# 11. process_zip() — end-to-end pipeline
# ===========================================================================
class TestProcessZip:
    def test_invalid_zip_raises(self, tmp_path):
        bad = tmp_path / "not_a_zip.zip"
        bad.write_bytes(b"definitely not a zip")
        with pytest.raises(ValueError, match="Not a valid ZIP"):
            ztl.process_zip(bad)

    def test_basic_text_file(self, tmp_zip):
        zpath = tmp_zip({"hello.txt": "hello world"})
        out = ztl.process_zip(zpath)
        assert "# LLM Document Bundle" in out
        assert "hello.txt" in out
        assert "hello world" in out
        assert "**Files found:** 1" in out

    def test_multiple_files(self, tmp_zip, sample_csv_bytes):
        zpath = tmp_zip({
            "a.txt": "alpha",
            "b.csv": sample_csv_bytes,
            "notes.md": "# Notes",
        })
        out = ztl.process_zip(zpath)
        assert "**Files found:** 3" in out
        assert "alpha" in out
        assert "Alice" in out
        assert "# Notes" in out

    def test_skips_macosx_and_dotfiles(self, tmp_zip):
        zpath = tmp_zip({
            "real.txt": "keep me",
            "__MACOSX/junk": "drop me",
            ".DS_Store": "drop me",
            ".git/config": "drop me",
        })
        out = ztl.process_zip(zpath)
        assert "real.txt" in out
        # Splitting content past the manifest header to verify they are skipped in main extraction
        sections_content = out.split("## Table of Contents")[-1]
        assert "__MACOSX" not in sections_content
        assert ".DS_Store" not in sections_content
        assert ".git/config" not in sections_content
        assert "**Files found:** 1" in out

    def test_unsupported_file_noted_not_crashed(self, tmp_zip):
        zpath = tmp_zip({"weird.xyz": b"\x00\x01binary\x02"})
        out = ztl.process_zip(zpath)
        assert "weird.xyz" in out
        assert "unsupported" in out.lower()

    def test_readme_without_extension_extracted(self, tmp_zip):
        """[HARDENING-C] README (no extension) must be included."""
        zpath = tmp_zip({"README": "Project documentation"})
        out = ztl.process_zip(zpath)
        assert "Project documentation" in out

    def test_dockerfile_extracted(self, tmp_zip):
        zpath = tmp_zip({"Dockerfile": "FROM python:3.11\nRUN pip install ."})
        out = ztl.process_zip(zpath)
        assert "FROM python:3.11" in out

    def test_empty_file_handled(self, tmp_zip):
        """[HARDENING-E] Empty files should produce '[empty file]' note."""
        zpath = tmp_zip({"empty.txt": b""})
        out = ztl.process_zip(zpath)
        assert "empty.txt" in out
        assert "[empty file]" in out

    def test_file_size_cap_skips_oversized(self, tmp_zip):
        """[HARDENING-A] Files above cap must be skipped before reading."""
        big = b"x" * (2 * 1024 * 1024)  # 2 MB
        zpath = tmp_zip({"huge.txt": big, "small.txt": b"tiny"})
        out = ztl.process_zip(zpath, max_uncompressed=1024 * 1024)  # 1 MB cap
        assert "huge.txt" in out
        assert "exceeds" in out.lower() or "skipped" in out.lower()
        assert "tiny" in out  # small file still processed

    def test_unsupported_large_file_not_loaded(self, tmp_zip):
        """[HARDENING-A] Unsupported large file routed without read."""
        # A 5 MB unsupported binary; should be noted but not crash memory.
        big_bin = b"\x00" * (5 * 1024 * 1024)
        zpath = tmp_zip({"video.mp4": big_bin})
        out = ztl.process_zip(zpath)
        assert "video.mp4" in out
        assert "unsupported file type (.mp4) — skipped" in out.lower()

    def test_media_files_graceful_skipping(self, tmp_zip):
        """Explicit media file extensions should be gracefully skipped and clearly stated."""
        zpath = tmp_zip({
            "audio.mp3": b"\x49\x44\x33audio",
            "movie.mov": b"\x00\x00\x00\x14ftypqt",
        })
        out = ztl.process_zip(zpath)
        assert "audio.mp3" in out
        assert "unsupported file type (.mp3) — skipped" in out.lower()
        assert "movie.mov" in out
        assert "unsupported file type (.mov) — skipped" in out.lower()

    def test_arbitrary_unsupported_file_skipping(self, tmp_zip):
        """Arbitrary unsupported file extensions should be skipped and report their extension."""
        zpath = tmp_zip({"data.xyz": b"\x00binary"})
        out = ztl.process_zip(zpath)
        assert "data.xyz" in out
        assert "unsupported file type (.xyz) — skipped" in out.lower()

    def test_table_of_contents_present(self, tmp_zip):
        zpath = tmp_zip({"a.txt": "x", "b.txt": "y"})
        out = ztl.process_zip(zpath)
        assert "## Table of Contents" in out
        assert "- `a.txt`" in out
        assert "- `b.txt`" in out

    def test_files_sorted_alphabetically(self, tmp_zip):
        zpath = tmp_zip({"zebra.txt": "z", "alpha.txt": "a", "mango.txt": "m"})
        out = ztl.process_zip(zpath)
        idx_a = out.index("alpha.txt")
        idx_m = out.index("mango.txt")
        idx_z = out.index("zebra.txt")
        # First TOC mention should be sorted
        assert idx_a < idx_m < idx_z

    def test_extraction_error_continues_processing(self, tmp_zip, monkeypatch):
        """Failure in one extractor must not stop others."""
        def boom(data, name):
            raise RuntimeError("simulated failure")
        monkeypatch.setitem(ztl.EXT_MAP, ".txt", ("Text", boom))

        zpath = tmp_zip({"bad.txt": "x", "good.csv": b"a,b\n1,2"})
        out = ztl.process_zip(zpath)
        assert "Extraction error" in out
        assert "good.csv" in out
        assert "| a | b |" in out

    def test_nested_directories(self, tmp_zip):
        zpath = tmp_zip({
            "src/main.py": "print('hi')",
            "docs/readme.md": "# Docs",
        })
        out = ztl.process_zip(zpath)
        assert "src/main.py" in out
        assert "docs/readme.md" in out


# ===========================================================================
# 12. PDF rendering [HARDENING-B]
# ===========================================================================
@pytest.mark.skipif(ztl.SimpleDocTemplate is None, reason="reportlab not installed")
class TestRenderPdf:
    def test_renders_basic_markdown(self, tmp_path):
        md = "# Title\n\nsome paragraph text\n"
        pdf = tmp_path / "out.pdf"
        ztl.render_pdf(md, pdf)
        assert pdf.exists() and pdf.stat().st_size > 0

    def test_renders_code_block_with_xml_chars(self, tmp_path):
        """[HARDENING-B] Code containing <, >, & must NOT crash ReportLab."""
        md = (
            "# Title\n\n"
            "```python\n"
            "if x < y and a > b:\n"
            "    s = '<html>' & '<body>'\n"
            "```\n"
        )
        pdf = tmp_path / "out.pdf"
        ztl.render_pdf(md, pdf)  # must not raise
        assert pdf.exists() and pdf.stat().st_size > 0

    def test_renders_paragraph_with_xml_chars(self, tmp_path):
        md = "# T\n\nThis has <b>bold</b> & ampersands < > everywhere.\n"
        pdf = tmp_path / "out.pdf"
        ztl.render_pdf(md, pdf)
        assert pdf.exists()

    def test_renders_horizontal_rule_as_pagebreak(self, tmp_path):
        md = "page1\n\n---\n\npage2\n"
        pdf = tmp_path / "out.pdf"
        ztl.render_pdf(md, pdf)
        assert pdf.exists()

    def test_renders_unterminated_code_fence(self, tmp_path):
        """Unterminated ``` should still flush gracefully."""
        md = "# T\n\n```python\nprint('no closing fence')\n"
        pdf = tmp_path / "out.pdf"
        ztl.render_pdf(md, pdf)
        assert pdf.exists()

    def test_renders_all_heading_levels(self, tmp_path):
        md = "# H1\n\n## H2\n\n### H3\n\n#### H4\n\nbody\n"
        pdf = tmp_path / "out.pdf"
        ztl.render_pdf(md, pdf)
        assert pdf.exists()


# ===========================================================================
# 13. CLI / main()
# ===========================================================================
class TestMainCli:
    def test_missing_file_returns_1(self, capsys):
        rc = ztl.main(["/nonexistent/path.zip"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "not found" in err

    def test_directory_instead_of_file(self, tmp_path, capsys):
        rc = ztl.main([str(tmp_path)])
        assert rc == 1
        assert "not a file" in capsys.readouterr().err

    def test_invalid_zip_returns_1(self, tmp_path, capsys):
        bad = tmp_path / "bad.zip"
        bad.write_bytes(b"not a zip")
        rc = ztl.main([str(bad)])
        assert rc == 1
        assert "Not a valid ZIP" in capsys.readouterr().err

    def test_successful_run_writes_md(self, tmp_zip, tmp_path, capsys):
        zpath = tmp_zip({"hello.txt": "world"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base)])
        assert rc == 0
        md_file = Path(str(out_base) + ".md")
        assert md_file.exists()
        assert "world" in md_file.read_text(encoding="utf-8")

    def test_default_output_name(self, tmp_zip, tmp_path, monkeypatch, capsys):
        zpath = tmp_zip({"a.txt": "x"}, name="myarchive.zip")
        monkeypatch.chdir(tmp_path)
        rc = ztl.main([str(zpath)])
        assert rc == 0
        assert (tmp_path / "myarchive_llm.md").exists()

    @pytest.mark.skipif(ztl.SimpleDocTemplate is None, reason="reportlab not installed")
    def test_pdf_flag_produces_pdf(self, tmp_zip, tmp_path):
        zpath = tmp_zip({"a.txt": "hello"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base), "--pdf"])
        assert rc == 0
        assert Path(str(out_base) + ".md").exists()
        assert Path(str(out_base) + ".pdf").exists()

    def test_max_file_mb_flag(self, tmp_zip, tmp_path):
        big = b"x" * (2 * 1024 * 1024)
        zpath = tmp_zip({"big.txt": big, "small.txt": b"ok"})
        out_base = tmp_path / "r"
        rc = ztl.main([str(zpath), "-o", str(out_base), "--max-file-mb", "1"])
        assert rc == 0
        md = Path(str(out_base) + ".md").read_text(encoding="utf-8")
        assert "skipped" in md.lower() or "exceeds" in md.lower()
        assert "ok" in md


# ===========================================================================
# 14. Security / robustness scenarios
# ===========================================================================
class TestSecurity:
    def test_zip_bomb_declared_size_rejected(self, tmp_path):
        """A ZIP entry declaring huge uncompressed size must be skipped."""
        zpath = tmp_path / "bomb.zip"
        # Create a zip with one large highly-compressible entry
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bomb.txt", b"A" * (5 * 1024 * 1024))  # 5 MB of A's
        out = ztl.process_zip(zpath, max_uncompressed=1024 * 1024)
        assert "bomb.txt" in out
        assert "exceeds" in out.lower() or "skipped" in out.lower()
        # Must NOT contain the 5 MB of A's
        assert "A" * 1000 not in out

    def test_path_traversal_filename_handled(self, tmp_path):
        """Tricky filenames must not cause path-traversal write."""
        zpath = tmp_path / "trav.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("../../etc/passwd", "root:x:0:0")
        # process_zip never writes files; it only reads & emits markdown
        out = ztl.process_zip(zpath)
        assert isinstance(out, str)
        # Filename is rendered but no file write should happen outside tmp
        assert "passwd" in out

    def test_many_small_files(self, tmp_zip):
        """Stress: 200 small files should process without crashing."""
        entries = {f"file_{i:03d}.txt": f"content {i}" for i in range(200)}
        zpath = tmp_zip(entries)
        out = ztl.process_zip(zpath)
        assert "**Files found:** 200" in out

    def test_binary_garbage_in_text_extension(self, tmp_zip):
        """A .txt file containing binary garbage should not crash."""
        zpath = tmp_zip({"weird.txt": bytes(range(256))})
        out = ztl.process_zip(zpath)
        assert "weird.txt" in out


# ===========================================================================
# 15. Mocked optional-dependency absence
# ===========================================================================
class TestOptionalDependencyAbsent:
    def test_pdf_without_pdfplumber(self, monkeypatch):
        monkeypatch.setattr(ztl, "pdfplumber", None)
        out = ztl.extract_pdf(b"%PDF-1.4 stub", "a.pdf")
        assert "pdfplumber not installed" in out

    def test_image_without_pillow(self, monkeypatch):
        monkeypatch.setattr(ztl, "Image", None)
        out = ztl.extract_image(b"\x89PNG", "a.png")
        assert "not installed" in out

    def test_excel_without_openpyxl(self, monkeypatch):
        monkeypatch.setattr(ztl, "openpyxl", None)
        out = ztl.extract_excel(b"PK\x03\x04stub", "a.xlsx")
        assert "openpyxl not installed" in out

    def test_docx_without_python_docx(self, monkeypatch):
        monkeypatch.setattr(ztl, "python_docx", None)
        out = ztl.extract_docx(b"stub", "a.docx")
        assert "python-docx not installed" in out

    def test_pptx_without_python_pptx(self, monkeypatch):
        monkeypatch.setattr(ztl, "Presentation", None)
        out = ztl.extract_pptx(b"stub", "a.pptx")
        assert "python-pptx not installed" in out

    def test_pdf_render_without_reportlab(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ztl, "SimpleDocTemplate", None)
        with pytest.raises(RuntimeError, match="reportlab not installed"):
            ztl.render_pdf("# x", tmp_path / "x.pdf")


# ===========================================================================
# 16. Integration with real Excel/DOCX (skipped if libs missing)
# ===========================================================================
@pytest.mark.skipif(ztl.openpyxl is None, reason="openpyxl not installed")
class TestExcelIntegration:
    def test_real_xlsx_extracted(self, tmp_path):
        xpath = tmp_path / "data.xlsx"
        wb = ztl.openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sales"
        ws.append(["Month", "Revenue"])
        ws.append(["Jan", 1000])
        ws.append(["Feb", 1500])
        wb.create_sheet("Empty")
        wb.save(xpath)

        out = ztl.extract_excel(xpath.read_bytes(), "data.xlsx")
        assert "#### Sheet: Sales" in out
        assert "| Month | Revenue |" in out
        assert "| Jan | 1000 |" in out
        assert "#### Sheet: Empty" in out


@pytest.mark.skipif(ztl.python_docx is None, reason="python-docx not installed")
class TestDocxIntegration:
    def test_real_docx_extracted(self, tmp_path):
        dpath = tmp_path / "doc.docx"
        doc = ztl.python_docx.Document()
        doc.add_heading("Main Title", level=1)
        doc.add_paragraph("First paragraph.")
        doc.add_paragraph("Second paragraph.")
        table = doc.add_table(rows=2, cols=2)
        table.rows[0].cells[0].text = "A"
        table.rows[0].cells[1].text = "B"
        table.rows[1].cells[0].text = "1"
        table.rows[1].cells[1].text = "2"
        doc.save(dpath)

        out = ztl.extract_docx(dpath.read_bytes(), "doc.docx")
        assert "Main Title" in out
        assert "First paragraph." in out
        assert "| A | B |" in out


# ===========================================================================
# 17. End-to-end smoke test
# ===========================================================================
class TestEndToEnd:
    def test_full_pipeline_smoke(self, tmp_path):
        """A representative archive runs the entire pipeline without error."""
        zpath = tmp_path / "bundle.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README", "Project README\nLine 2")
            zf.writestr("docs/intro.md", "# Intro\n\nMarkdown body.")
            zf.writestr("data/numbers.csv", "x,y\n1,2\n3,4\n")
            zf.writestr("config.json", '{"k":"v"}')
            zf.writestr("src/app.py", "def main(): pass\n")
            zf.writestr("page.html", "<h1>Hi</h1><p>Body</p>")
            zf.writestr("__MACOSX/ignored", "junk")
            zf.writestr(".git/config", "junk")
            zf.writestr("empty.txt", b"")
            zf.writestr("unknown.xyz", b"\x00binary\x00")

        out_base = tmp_path / "bundle_out"
        rc = ztl.main([str(zpath), "-o", str(out_base)])
        assert rc == 0

        md = Path(str(out_base) + ".md").read_text(encoding="utf-8")
        # Inclusions
        assert "Project README" in md
        assert "Markdown body" in md
        assert "| x | y |" in md
        assert '"k": "v"' in md
        assert "def main()" in md
        assert "Hi" in md and "Body" in md
        assert "[empty file]" in md
        assert "unsupported" in md.lower()
        # Exclusions from the main parsed file sections
        sections_content = md.split("## Table of Contents")[-1]
        assert "__MACOSX" not in sections_content
        assert ".git/config" not in sections_content
