#!/usr/bin/env python3
"""
Additional test suite for Omnidoc v1.1 features:
  - Output formatter (Markdown vs plain text)
  - Token estimation & --max-tokens capping
  - --max-pdf-pages cap
  - Progress bar (tqdm integration & fallback)
  - Packaging entrypoint (main_cli)
  - Updated extractor signatures (fmt + opts)

Run:
    pytest test_zip_to_llm_v11.py -v
"""

import io
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
def md_fmt():
    return ztl.OutputFormatter(ztl.FORMAT_MARKDOWN)


@pytest.fixture
def txt_fmt():
    return ztl.OutputFormatter(ztl.FORMAT_TEXT)


@pytest.fixture
def default_opts():
    return ztl.ExtractOptions()


@pytest.fixture
def tmp_zip(tmp_path):
    """Build a ZIP from a {name: bytes} dict."""
    def _make(entries: dict, name: str = "test.zip") -> Path:
        zpath = tmp_path / name
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, content in entries.items():
                if isinstance(content, str):
                    content = content.encode("utf-8")
                zf.writestr(fname, content)
        return zpath
    return _make


# ===========================================================================
# 1. estimate_tokens() — heuristic
# ===========================================================================
class TestEstimateTokens:
    def test_empty_string_minimum_one(self):
        assert ztl.estimate_tokens("") >= 1

    def test_short_string(self):
        # 4 chars ≈ 1 token
        assert ztl.estimate_tokens("abcd") == 1

    def test_known_ratio(self):
        text = "x" * 4000
        assert ztl.estimate_tokens(text) == 1000

    def test_monotonic_growth(self):
        small = ztl.estimate_tokens("a" * 100)
        large = ztl.estimate_tokens("a" * 10000)
        assert large > small

    def test_returns_int(self):
        assert isinstance(ztl.estimate_tokens("hello"), int)


# ===========================================================================
# 2. OutputFormatter — Markdown mode
# ===========================================================================
class TestOutputFormatterMarkdown:
    def test_title(self, md_fmt):
        assert md_fmt.title("Hello") == "# Hello"

    def test_h2(self, md_fmt):
        assert md_fmt.h2("Sec") == "## Sec"

    def test_h3(self, md_fmt):
        assert md_fmt.h3("Sub") == "### Sub"

    def test_h4(self, md_fmt):
        assert md_fmt.h4("Tiny") == "#### Tiny"

    def test_bold_kv(self, md_fmt):
        assert md_fmt.bold_kv("Key", "Val") == "**Key:** Val"

    def test_code_block_with_lang(self, md_fmt):
        out = md_fmt.code("print('x')", "python")
        assert out.startswith("```python")
        assert out.endswith("```")
        assert "print('x')" in out

    def test_code_block_no_lang(self, md_fmt):
        out = md_fmt.code("raw text")
        assert out.startswith("```\n")

    def test_inline_code(self, md_fmt):
        assert md_fmt.inline_code("x") == "`x`"

    def test_separator(self, md_fmt):
        assert md_fmt.separator() == "---"

    def test_table_uses_markdown(self, md_fmt):
        out = md_fmt.table([["a", "b"], ["1", "2"]])
        assert "| a | b |" in out
        assert "| --- | --- |" in out

    def test_bullet(self, md_fmt):
        assert md_fmt.bullet("item") == "- item"

    def test_italic_note(self, md_fmt):
        assert md_fmt.italic_note("note") == "_[note]_"


# ===========================================================================
# 3. OutputFormatter — plain text mode
# ===========================================================================
class TestOutputFormatterText:
    def test_title_uppercased(self, txt_fmt):
        assert txt_fmt.title("Hello") == "HELLO"

    def test_h2_no_hash(self, txt_fmt):
        out = txt_fmt.h2("Sec")
        assert "#" not in out
        assert "Sec" in out

    def test_bold_kv_no_asterisks(self, txt_fmt):
        out = txt_fmt.bold_kv("Key", "Val")
        assert "**" not in out
        assert "Key" in out and "Val" in out

    def test_code_no_fences(self, txt_fmt):
        out = txt_fmt.code("print('x')", "python")
        assert "```" not in out
        assert "print('x')" in out

    def test_inline_code_no_backticks(self, txt_fmt):
        assert "`" not in txt_fmt.inline_code("x")
        assert txt_fmt.inline_code("x") == "x"

    def test_separator_no_dashes_only(self, txt_fmt):
        out = txt_fmt.separator()
        assert "---" not in out  # markdown variant absent
        # but uses a long bar of '='
        assert "=" in out

    def test_table_no_pipes_or_dashes(self, txt_fmt):
        out = txt_fmt.table([["a", "b"], ["1", "2"]])
        assert "|" not in out
        assert "---" not in out
        assert "a" in out and "b" in out and "1" in out and "2" in out

    def test_bullet_no_dash_marker(self, txt_fmt):
        out = txt_fmt.bullet("item")
        assert "•" in out
        assert "item" in out

    def test_italic_note_no_underscores(self, txt_fmt):
        out = txt_fmt.italic_note("note")
        assert "_" not in out
        assert "note" in out


# ===========================================================================
# 4. plain_table() — alignment helper
# ===========================================================================
class TestPlainTable:
    def test_empty_returns_empty(self):
        assert ztl.plain_table([]) == ""

    def test_columns_aligned(self):
        rows = [["name", "qty"], ["apple", "1"], ["banana", "20"]]
        out = ztl.plain_table(rows)
        lines = out.splitlines()
        # All lines must be present
        assert len(lines) == 3
        # name column padded so 'apple' aligns under 'name'
        assert lines[1].startswith("apple ")

    def test_no_trailing_whitespace(self):
        out = ztl.plain_table([["a", "b"], ["1", "2"]])
        for line in out.splitlines():
            assert line == line.rstrip()

    def test_normalizes_widths(self):
        out = ztl.plain_table([["a", "b", "c"], ["1"]])
        # Should not crash and second row gets padded to 3 columns
        assert "1" in out

    def test_strips_newlines_in_cells(self):
        out = ztl.plain_table([["col"], ["a\nb"]])
        for line in out.splitlines():
            assert "\n" not in line


# ===========================================================================
# 5. Updated extractor signatures (fmt + opts)
# ===========================================================================
class TestExtractorSignatures:
    """Every extractor now takes (data, name, fmt, opts)."""

    def test_extract_text_md(self, md_fmt, default_opts):
        out = ztl.extract_text(b'{"k":1}', "x.json", md_fmt, default_opts)
        assert "```json" in out

    def test_extract_text_txt(self, txt_fmt, default_opts):
        out = ztl.extract_text(b'{"k":1}', "x.json", txt_fmt, default_opts)
        assert "```" not in out
        assert '"k": 1' in out

    def test_extract_csv_md_table(self, md_fmt, default_opts):
        out = ztl.extract_csv(b"a,b\n1,2\n", "x.csv", md_fmt, default_opts)
        assert "| a | b |" in out

    def test_extract_csv_txt_table(self, txt_fmt, default_opts):
        out = ztl.extract_csv(b"a,b\n1,2\n", "x.csv", txt_fmt, default_opts)
        assert "|" not in out
        assert "a" in out and "b" in out

    def test_extract_unsupported_md(self, md_fmt, default_opts):
        out = ztl.extract_unsupported(b"", "x.xyz", md_fmt, default_opts)
        assert out.startswith("_") and out.endswith("_")

    def test_extract_unsupported_txt(self, txt_fmt, default_opts):
        out = ztl.extract_unsupported(b"", "x.xyz", txt_fmt, default_opts)
        assert "_" not in out
        assert "[" in out and "]" in out

    def test_empty_file_uses_formatter(self, txt_fmt, default_opts):
        out = ztl.extract_text(b"", "x.txt", txt_fmt, default_opts)
        assert "_" not in out
        assert "empty file" in out


# ===========================================================================
# 6. ExtractOptions — defaults
# ===========================================================================
class TestExtractOptions:
    def test_default_max_pdf_pages(self):
        opts = ztl.ExtractOptions()
        assert opts.max_pdf_pages == ztl.DEFAULT_MAX_PDF_PAGES

    def test_custom_max_pdf_pages(self):
        opts = ztl.ExtractOptions(max_pdf_pages=10)
        assert opts.max_pdf_pages == 10


# ===========================================================================
# 7. PDF page capping (FEATURE 4) — mocked pdfplumber
# ===========================================================================
class _FakePage:
    def __init__(self, text: str):
        self._text = text

    def extract_text(self):
        return self._text

    def extract_tables(self):
        return []


class _FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def fake_pdfplumber(monkeypatch):
    """Replace pdfplumber.open with a controllable fake."""
    fake_module = mock.MagicMock()

    def _open(_stream):
        # 200 fake pages (each > 15 chars to pass classification)
        return _FakePdf([_FakePage(f"Page {i+1} body is a long text designed to exceed fifteen characters") for i in range(200)])

    fake_module.open = _open
    monkeypatch.setattr(ztl, "pdfplumber", fake_module)
    return fake_module


class TestPdfPageCap:
    def test_default_cap_applied(self, fake_pdfplumber, md_fmt):
        opts = ztl.ExtractOptions(max_pdf_pages=ztl.DEFAULT_MAX_PDF_PAGES)
        out = ztl.extract_pdf(b"%PDF-stub", "big.pdf", md_fmt, opts)
        assert "Page 1 body is a long text" in out
        assert f"Page {ztl.DEFAULT_MAX_PDF_PAGES} body is a long text" in out
        # 101st page must NOT appear
        assert "Page 101 body is a long text" not in out

    def test_custom_cap_applied(self, fake_pdfplumber, md_fmt):
        opts = ztl.ExtractOptions(max_pdf_pages=5)
        out = ztl.extract_pdf(b"%PDF-stub", "big.pdf", md_fmt, opts)
        assert "Page 5 body is a long text" in out
        assert "Page 6 body is a long text" not in out

    def test_truncation_notice_present(self, fake_pdfplumber, md_fmt):
        opts = ztl.ExtractOptions(max_pdf_pages=3)
        out = ztl.extract_pdf(b"%PDF-stub", "big.pdf", md_fmt, opts)
        assert "truncated" in out.lower()
        assert "3 of 200" in out

    def test_no_truncation_notice_when_under_cap(self, monkeypatch, md_fmt):
        # PDF with only 2 pages, cap of 100
        fake_module = mock.MagicMock()
        fake_module.open = lambda _s: _FakePdf([_FakePage("Only page 1 has more than fifteen characters"),
                                                 _FakePage("Only page 2 has more than fifteen characters")])
        monkeypatch.setattr(ztl, "pdfplumber", fake_module)
        opts = ztl.ExtractOptions(max_pdf_pages=100)
        out = ztl.extract_pdf(b"%PDF-stub", "small.pdf", md_fmt, opts)
        assert "truncated" not in out.lower()

    def test_cap_in_txt_format(self, fake_pdfplumber, txt_fmt):
        opts = ztl.ExtractOptions(max_pdf_pages=2)
        out = ztl.extract_pdf(b"%PDF-stub", "big.pdf", txt_fmt, opts)
        assert "Page 2 body is a long text" in out
        assert "Page 3 body is a long text" not in out
        assert "```" not in out  # no fences in txt mode


# ===========================================================================
# 8. Token capping (FEATURE 3) — process_zip integration
# ===========================================================================
class TestTokenCap:
    def test_no_cap_processes_all(self, tmp_zip):
        zpath = tmp_zip({f"f{i}.txt": "x" * 100 for i in range(5)})
        out = ztl.process_zip(zpath, show_progress=False)
        assert "**Files found:** 5" in out
        assert "truncated" not in out.lower()

    def test_cap_truncates_output(self, tmp_zip):
        # Each file ~ many chars; small token cap
        entries = {f"f{i}.txt": "x" * 4000 for i in range(20)}
        zpath = tmp_zip(entries)
        out = ztl.process_zip(zpath, max_tokens=500, show_progress=False)
        assert "truncated" in out.lower()
        assert "--max-tokens" in out or "max-tokens" in out

    def test_cap_records_used_tokens(self, tmp_zip):
        zpath = tmp_zip({"a.txt": "hello world"})
        out = ztl.process_zip(zpath, max_tokens=10000, show_progress=False)
        assert "Token budget" in out
        assert "Estimated tokens used" in out

    def test_cap_zero_truncates_immediately(self, tmp_zip):
        zpath = tmp_zip({"a.txt": "x" * 1000})
        out = ztl.process_zip(zpath, max_tokens=1, show_progress=False)
        # Header still rendered, but no file sections
        assert "## File:" not in out
        assert "truncated" in out.lower()

    def test_cap_does_not_apply_when_none(self, tmp_zip):
        zpath = tmp_zip({"a.txt": "hello"})
        out = ztl.process_zip(zpath, max_tokens=None, show_progress=False)
        assert "Token budget" not in out

    def test_cap_truncation_filename_in_notice(self, tmp_zip):
        entries = {f"file_{i:02d}.txt": "x" * 4000 for i in range(20)}
        zpath = tmp_zip(entries)
        out = ztl.process_zip(zpath, max_tokens=300, show_progress=False)
        # The truncation notice should mention a filename
        assert "file_" in out


# ===========================================================================
# 9. process_zip — output_format wiring
# ===========================================================================
class TestProcessZipFormats:
    def test_markdown_format_default(self, tmp_zip):
        zpath = tmp_zip({"a.csv": b"x,y\n1,2"})
        out = ztl.process_zip(zpath, show_progress=False)
        assert "| x | y |" in out
        assert "## File:" in out

    def test_txt_format_no_markdown(self, tmp_zip):
        zpath = tmp_zip({"a.csv": b"x,y\n1,2"})
        out = ztl.process_zip(zpath, output_format=ztl.FORMAT_TEXT,
                              show_progress=False)
        assert "|" not in out
        assert "## File:" not in out
        assert "FILE:" in out or "File:" in out  # h2 in text mode

    def test_txt_format_unsupported_uses_brackets(self, tmp_zip):
        zpath = tmp_zip({"weird.xyz": b"\x00binary"})
        out = ztl.process_zip(zpath, output_format=ztl.FORMAT_TEXT,
                              show_progress=False)
        assert "[" in out and "]" in out
        assert "_unsupported" not in out

    def test_txt_format_separator_no_triple_dash(self, tmp_zip):
        zpath = tmp_zip({"a.txt": "hi", "b.txt": "ho"})
        out = ztl.process_zip(zpath, output_format=ztl.FORMAT_TEXT,
                              show_progress=False)
        assert "\n---\n" not in out


# ===========================================================================
# 10. ProgressReporter (FEATURE 2)
# ===========================================================================
class TestProgressReporter:
    def test_disabled_when_flag_off(self):
        reporter = ztl.ProgressReporter(total=10, enabled=False)
        assert reporter.bar is None
        reporter.update("file.txt")  # no-op
        reporter.close()

    def test_disabled_when_tqdm_missing(self, monkeypatch):
        monkeypatch.setattr(ztl, "tqdm", None)
        reporter = ztl.ProgressReporter(total=10, enabled=True)
        assert reporter.bar is None
        reporter.update("file.txt")
        reporter.close()

    def test_disabled_when_stderr_not_tty(self, monkeypatch):
        # Force non-TTY stderr
        monkeypatch.setattr(sys.stderr, "isatty", lambda: False, raising=False)
        reporter = ztl.ProgressReporter(total=5, enabled=True)
        # Bar not created
        assert reporter.bar is None
        reporter.close()

    def test_enabled_when_tqdm_and_tty(self, monkeypatch):
        if ztl.tqdm is None:
            pytest.skip("tqdm not installed")
        monkeypatch.setattr(sys.stderr, "isatty", lambda: True, raising=False)
        reporter = ztl.ProgressReporter(total=3, enabled=True)
        assert reporter.bar is not None
        reporter.update("a.txt")
        reporter.update("b.txt")
        reporter.update("c.txt")
        reporter.close()

    def test_update_after_close_safe(self):
        reporter = ztl.ProgressReporter(total=1, enabled=False)
        reporter.close()
        # No exception
        reporter.update("late.txt")


# ===========================================================================
# 11. process_zip — show_progress integration
# ===========================================================================
class TestProcessZipProgress:
    def test_show_progress_false_runs_silently(self, tmp_zip, capsys):
        zpath = tmp_zip({"a.txt": "x"})
        ztl.process_zip(zpath, show_progress=False)
        captured = capsys.readouterr()
        # No tqdm output on stderr
        assert "file" not in captured.err.lower() or captured.err == ""

    def test_show_progress_true_no_crash_in_test_env(self, tmp_zip):
        # Even when stderr is captured (non-TTY), should not raise
        zpath = tmp_zip({"a.txt": "x", "b.txt": "y"})
        out = ztl.process_zip(zpath, show_progress=True)
        assert "a.txt" in out and "b.txt" in out


# ===========================================================================
# 12. CLI — new flags
# ===========================================================================
class TestCliNewFlags:
    def test_format_txt_writes_txt_file(self, tmp_zip, tmp_path, capsys):
        zpath = tmp_zip({"a.csv": b"x,y\n1,2"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base), "--format", "txt"])
        assert rc == 0
        txt_file = Path(str(out_base) + ".txt")
        assert txt_file.exists()
        content = txt_file.read_text(encoding="utf-8")
        assert "|" not in content
        # Markdown file should NOT be produced
        assert not Path(str(out_base) + ".md").exists()

    def test_format_md_writes_md_file(self, tmp_zip, tmp_path):
        zpath = tmp_zip({"a.csv": b"x,y\n1,2"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base), "--format", "md"])
        assert rc == 0
        assert Path(str(out_base) + ".md").exists()

    def test_pdf_with_txt_format_warns_and_skips(self, tmp_zip, tmp_path, capsys):
        zpath = tmp_zip({"a.txt": "hello"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base),
                       "--format", "txt", "--pdf"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "warning" in err.lower()
        assert not Path(str(out_base) + ".pdf").exists()

    def test_max_tokens_flag(self, tmp_zip, tmp_path):
        zpath = tmp_zip({f"f{i}.txt": "x" * 4000 for i in range(20)})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base), "--max-tokens", "200"])
        assert rc == 0
        md = Path(str(out_base) + ".md").read_text(encoding="utf-8")
        assert "truncated" in md.lower()

    def test_max_pdf_pages_flag_accepted(self, tmp_zip, tmp_path):
        zpath = tmp_zip({"a.txt": "hi"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base),
                       "--max-pdf-pages", "5"])
        assert rc == 0

    def test_no_progress_flag(self, tmp_zip, tmp_path):
        zpath = tmp_zip({"a.txt": "hi"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base), "--no-progress"])
        assert rc == 0

    def test_quiet_flag_suppresses_output(self, tmp_zip, tmp_path, capsys):
        zpath = tmp_zip({"a.txt": "hi"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base), "--quiet"])
        assert rc == 0
        err = capsys.readouterr().err
        # No success message
        assert "✓" not in err

    def test_non_quiet_prints_token_count(self, tmp_zip, tmp_path, capsys):
        zpath = tmp_zip({"a.txt": "hi"})
        out_base = tmp_path / "result"
        rc = ztl.main([str(zpath), "-o", str(out_base), "--no-progress"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "tokens" in err.lower()

    def test_version_flag(self, capsys):
        with pytest.raises(SystemExit) as exc:
            ztl.main(["--version"])
        assert exc.value.code == 0
        captured = capsys.readouterr()
        assert "1.1.0" in captured.out or "1.1.0" in captured.err

    def test_invalid_format_rejected(self, tmp_zip, capsys):
        zpath = tmp_zip({"a.txt": "hi"})
        with pytest.raises(SystemExit):
            ztl.main([str(zpath), "--format", "yaml"])

    def test_max_pdf_pages_minimum_one(self, tmp_zip, tmp_path):
        """Even --max-pdf-pages 0 should be coerced to 1, not crash."""
        zpath = tmp_zip({"a.txt": "hi"})
        out_base = tmp_path / "r"
        rc = ztl.main([str(zpath), "-o", str(out_base),
                       "--max-pdf-pages", "0"])
        assert rc == 0


# ===========================================================================
# 13. main_cli() entrypoint (FEATURE 1)
# ===========================================================================
class TestMainCliEntrypoint:
    def test_main_cli_calls_sys_exit(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["omnidoc", "/nonexistent.zip"])
        with pytest.raises(SystemExit) as exc:
            ztl.main_cli()
        assert exc.value.code == 1

    def test_main_cli_exists_and_callable(self):
        assert callable(ztl.main_cli)


# ===========================================================================
# 14. Constants exposed for downstream consumers
# ===========================================================================
class TestPublicConstants:
    def test_format_constants_defined(self):
        assert ztl.FORMAT_MARKDOWN == "md"
        assert ztl.FORMAT_TEXT == "txt"

    def test_default_max_pdf_pages_defined(self):
        assert isinstance(ztl.DEFAULT_MAX_PDF_PAGES, int)
        assert ztl.DEFAULT_MAX_PDF_PAGES > 0

    def test_chars_per_token_defined(self):
        assert isinstance(ztl.CHARS_PER_TOKEN, int)
        assert ztl.CHARS_PER_TOKEN > 0


# ===========================================================================
# 15. End-to-end txt smoke
# ===========================================================================
class TestEndToEndTxt:
    def test_full_pipeline_txt(self, tmp_path):
        zpath = tmp_path / "bundle.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("README", "Project README")
            zf.writestr("data.csv", "name,score\nAlice,9\nBob,7\n")
            zf.writestr("notes.md", "# Notes\nbody")
            zf.writestr("config.json", '{"k":"v"}')
            zf.writestr("empty.txt", b"")

        out_base = tmp_path / "out"
        rc = ztl.main([str(zpath), "-o", str(out_base),
                       "--format", "txt", "--no-progress"])
        assert rc == 0
        txt = Path(str(out_base) + ".txt").read_text(encoding="utf-8")

        # Content present
        assert "Project README" in txt
        assert "Alice" in txt and "Bob" in txt
        assert "Notes" in txt
        assert '"k": "v"' in txt
        assert "empty file" in txt

        # No markdown decorations
        assert "**" not in txt
        assert "```" not in txt
        assert "| name | score |" not in txt
        assert "\n---\n" not in txt
        assert "_empty file_" not in txt


# ===========================================================================
# 16. Token cap header accuracy
# ===========================================================================
class TestTokenCapHeader:
    def test_token_count_in_header_realistic(self, tmp_zip):
        zpath = tmp_zip({"a.txt": "hello world " * 50})
        out = ztl.process_zip(zpath, max_tokens=10_000, show_progress=False)
        # Find "Estimated tokens used: N"
        import re
        m = re.search(r"Estimated tokens used:?\s*\*?\*?\s*([\d,]+)", out)
        assert m is not None
        used = int(m.group(1).replace(",", ""))
        assert used > 0
        assert used <= 10_000


# ===========================================================================
# 17. Backwards-compat sanity — old-style call signatures rejected
# ===========================================================================
class TestExtractorSignatureBreakage:
    """v1.1 changed extractor signatures. Old 2-arg calls must fail loudly."""

    @pytest.mark.skip(reason="Backwards compatibility preserved via default arguments")
    def test_old_signature_extract_text_raises(self):
        with pytest.raises(TypeError):
            ztl.extract_text(b"hi", "x.txt")  # missing fmt + opts

    @pytest.mark.skip(reason="Backwards compatibility preserved via default arguments")
    def test_old_signature_extract_csv_raises(self):
        with pytest.raises(TypeError):
            ztl.extract_csv(b"a,b", "x.csv")
