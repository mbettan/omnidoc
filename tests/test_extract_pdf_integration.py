"""Integration tests for extract_pdf: mixed-page text retention, partial recovery,
selective rendering, classifier failure paths."""
import io
from pathlib import Path
from unittest import mock

import pytest

import zip_to_llm as ztl


class _Page:
    def __init__(self, text="", images=None, rects=None, lines=None, curves=None):
        self._text = text
        self.images = images or []
        self.rects = rects or []
        self.lines = lines or []
        self.curves = curves or []
    def extract_text(self):
        return self._text


@pytest.fixture
def fake_plumber(monkeypatch):
    def _setup(pages):
        class _Ctx:
            def __init__(self, p): self.pages = p
            def __enter__(self): return self
            def __exit__(self, *_): return False
        mp = mock.MagicMock()
        mp.open.return_value = _Ctx(pages)
        monkeypatch.setattr(ztl, "pdfplumber", mp)
    return _setup


class TestMixedPageTextRetention:
    """v3 Issue 10: mixed-page native text must always be preserved on bundle path."""

    def test_mixed_page_with_low_conf_ocr_and_isolation_keeps_text(self, fake_plumber, monkeypatch, tmp_path):
        native = "Critical native text from page that must not be lost. " * 3
        fake_plumber([_Page(text=native, images=[mock.MagicMock()])])

        # OCR fails confidence gate
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [20], "text": ["garbage"]}
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)
        monkeypatch.setattr(ztl, "convert_from_bytes",
                            lambda *a, **kw: [mock.MagicMock()])

        # Real VisualBundle to verify the bundle path is hit
        bundle = ztl.VisualBundle()
        opts = ztl.ExtractOptions(isolate_non_text=True)
        opts.visual_bundle = bundle

        result = ztl.extract_pdf(b"%PDF-stub", "doc.pdf", opts=opts)
        # Native text preserved
        assert "Critical native text" in result
        # AND bundled
        assert "Visual content" in result
        assert "visual-0001" in result


class TestPartialPageRecovery:
    """v3 Issue 9: per-page errors must not discard other pages."""

    def test_page_extraction_exception_isolated(self, fake_plumber, monkeypatch):
        pages = [
            _Page(text="A" * 50),
            _Page(text="B" * 50),
            _Page(text="C" * 50),
        ]
        fake_plumber(pages)
        opts = ztl.ExtractOptions()

        original_h3 = ztl.OutputFormatter.h3
        call_count = {"n": 0}
        def flaky_h3(self, text):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise RuntimeError("page 2 formatting error")
            return original_h3(self, text)
        monkeypatch.setattr(ztl.OutputFormatter, "h3", flaky_h3)

        result = ztl.extract_pdf(b"%PDF-stub", "doc.pdf", opts=opts)
        # Pages 1 and 3 still present
        assert "AAAAAAAA" in result
        assert "CCCCCCCC" in result


class TestClassifierFailurePath:
    """v3 Issue 8: classifier returning [] but pypdf can open → informative message."""

    def test_pypdf_fallback_reports_page_count(self, monkeypatch):
        """When pdfplumber fails but pypdf opens, report actual page count."""
        # Make classify_pdf_pages return empty
        monkeypatch.setattr(ztl, "classify_pdf_pages", lambda *a, **kw: [])

        # Make pypdf able to read the bytes with N pages
        mock_reader = mock.MagicMock()
        mock_reader.pages = [mock.MagicMock(), mock.MagicMock(), mock.MagicMock()]
        mock_pypdf = mock.MagicMock()
        mock_pypdf.PdfReader.return_value = mock_reader
        monkeypatch.setitem(__import__("sys").modules, "pypdf", mock_pypdf)

        result = ztl.extract_pdf(b"%PDF-real", "doc.pdf")
        assert "3 pages" in result
        assert "pdfplumber parse error" in result

    def test_empty_when_both_fail(self, monkeypatch):
        monkeypatch.setattr(ztl, "classify_pdf_pages", lambda *a, **kw: [])
        mock_pypdf = mock.MagicMock()
        mock_pypdf.PdfReader.side_effect = RuntimeError("pypdf cannot read")
        monkeypatch.setitem(__import__("sys").modules, "pypdf", mock_pypdf)
        result = ztl.extract_pdf(b"garbage", "doc.pdf")
        assert "Empty or unparseable PDF" in result


class TestSelectiveRendering:
    """Verify _contiguous_runs is used and ocr_render_dpi flows through."""

    def test_only_non_text_pages_rendered(self, fake_plumber, monkeypatch):
        """Text pages must not trigger Poppler calls."""
        fake_plumber([
            _Page(text="A" * 50),                                # text
            _Page(text="", images=[mock.MagicMock()]),            # image_only
            _Page(text="B" * 50),                                # text
            _Page(text="", images=[mock.MagicMock()]),            # image_only
        ])
        mock_convert = mock.MagicMock(return_value=[mock.MagicMock()])
        monkeypatch.setattr(ztl, "convert_from_bytes", mock_convert)
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [99], "text": ["ok"]}
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        ztl.extract_pdf(b"%PDF-stub", "doc.pdf")

        # Two non-contiguous render targets (pages 2 and 4)
        # → expect 2 separate convert_from_bytes calls (one per run)
        assert mock_convert.call_count == 2
        calls = mock_convert.call_args_list
        first_call_kwargs = calls[0][1]
        second_call_kwargs = calls[1][1]
        assert first_call_kwargs["first_page"] == 2 and first_call_kwargs["last_page"] == 2
        assert second_call_kwargs["first_page"] == 4 and second_call_kwargs["last_page"] == 4

    def test_contiguous_pages_batched_in_one_call(self, fake_plumber, monkeypatch):
        fake_plumber([
            _Page(text="A" * 50),
            _Page(text="", images=[mock.MagicMock()]),
            _Page(text="", images=[mock.MagicMock()]),
            _Page(text="", images=[mock.MagicMock()]),
            _Page(text="C" * 50),
        ])
        mock_convert = mock.MagicMock(return_value=[mock.MagicMock()] * 3)
        monkeypatch.setattr(ztl, "convert_from_bytes", mock_convert)
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [99], "text": ["ok"]}
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        ztl.extract_pdf(b"%PDF-stub", "doc.pdf")
        # Pages 2-4 contiguous → 1 call
        assert mock_convert.call_count == 1
        kwargs = mock_convert.call_args[1]
        assert kwargs["first_page"] == 2
        assert kwargs["last_page"] == 4

    def test_custom_dpi_passed_through(self, fake_plumber, monkeypatch):
        fake_plumber([_Page(text="", images=[mock.MagicMock()])])
        mock_convert = mock.MagicMock(return_value=[mock.MagicMock()])
        monkeypatch.setattr(ztl, "convert_from_bytes", mock_convert)
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [99], "text": ["ok"]}
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        opts = ztl.ExtractOptions(ocr_render_dpi=300)
        ztl.extract_pdf(b"%PDF-stub", "doc.pdf", opts=opts)
        assert mock_convert.call_args[1]["dpi"] == 300

    def test_render_failure_logs_and_continues(self, fake_plumber, monkeypatch, capsys):
        fake_plumber([_Page(text="", images=[mock.MagicMock()])])
        mock_convert = mock.MagicMock(side_effect=RuntimeError("poppler error"))
        monkeypatch.setattr(ztl, "convert_from_bytes", mock_convert)
        monkeypatch.setattr(ztl, "pytesseract", mock.MagicMock())

        result = ztl.extract_pdf(b"%PDF-stub", "doc.pdf")
        assert "no extractable text" in result or "Visual content" in result
        err = capsys.readouterr().err
        assert "failed to render pages" in err
