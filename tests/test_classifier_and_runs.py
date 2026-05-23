"""Unit tests for PDF page classification and Poppler render batching."""
import pytest
from unittest import mock
import io

import zip_to_llm as ztl


class _Page:
    """Lightweight mock that mimics pdfplumber.page interface."""
    def __init__(self, text="", images=None, rects=None, lines=None, curves=None):
        self._text = text
        self.images = images or []
        self.rects = rects or []
        self.lines = lines or []
        self.curves = curves or []

    def extract_text(self):
        return self._text


class TestVectorThreshold:
    """_has_significant_vectors: weighted curve*3 + line + rect > 15"""

    def test_empty_page_below_threshold(self):
        assert ztl._has_significant_vectors(_Page()) is False

    def test_simple_page_border_excluded(self):
        """4 rects + 4 lines (typical page border) → weighted=8, excluded."""
        page = _Page(rects=[mock.MagicMock()] * 4, lines=[mock.MagicMock()] * 4)
        assert ztl._has_significant_vectors(page) is False

    def test_table_grid_excluded(self):
        """A reasonable table grid (~8 lines from row borders) → excluded."""
        page = _Page(lines=[mock.MagicMock()] * 8)
        assert ztl._has_significant_vectors(page) is False

    def test_bar_chart_included(self):
        """20 rects + 10 lines + 5 curves → weighted=45, included."""
        page = _Page(
            rects=[mock.MagicMock()] * 20,
            lines=[mock.MagicMock()] * 10,
            curves=[mock.MagicMock()] * 5,
        )
        assert ztl._has_significant_vectors(page) is True

    def test_line_chart_curve_heavy(self):
        """A line chart's curves should weigh 3x → 30 curves alone trigger."""
        page = _Page(curves=[mock.MagicMock()] * 6)  # 6 * 3 = 18 > 15
        assert ztl._has_significant_vectors(page) is True

    def test_boundary_at_threshold(self):
        """Exactly 16 weighted → included (strict >)."""
        page = _Page(rects=[mock.MagicMock()] * 16)
        assert ztl._has_significant_vectors(page) is True
        page = _Page(rects=[mock.MagicMock()] * 15)
        assert ztl._has_significant_vectors(page) is False

    def test_missing_attributes_safe(self):
        """getattr returns None on missing attributes; should not crash."""
        bare = mock.MagicMock(spec=[])  # no rects/lines/curves
        assert ztl._has_significant_vectors(bare) is False


class TestContiguousRuns:
    """_contiguous_runs: groups consecutive integers into (start, end) tuples."""

    def test_empty_returns_empty(self):
        assert ztl._contiguous_runs([]) == []

    def test_single_element(self):
        assert ztl._contiguous_runs([7]) == [(7, 7)]

    def test_all_contiguous(self):
        assert ztl._contiguous_runs([1, 2, 3, 4]) == [(1, 4)]

    def test_all_gapped(self):
        assert ztl._contiguous_runs([1, 5, 9]) == [(1, 1), (5, 5), (9, 9)]

    def test_mixed_runs(self):
        assert ztl._contiguous_runs([1, 2, 3, 7, 8, 12]) == [(1, 3), (7, 8), (12, 12)]

    def test_unsorted_input_groups_as_received(self):
        """The function assumes sorted input; document the behavior."""
        # Caller is expected to sort first; runs on unsorted may produce odd groupings
        result = ztl._contiguous_runs([5, 1, 2])
        assert result == [(5, 5), (1, 2)]  # NOT one big run


class TestClassifyPdfPages:
    """classify_pdf_pages: three categories + crash resilience."""

    @pytest.fixture
    def fake_pdf_open(self, monkeypatch):
        def _setup(pages):
            class _PdfCtx:
                def __init__(self, pgs):
                    self.pages = pgs
                def __enter__(self):
                    return self
                def __exit__(self, *_):
                    return False

            mock_plumber = mock.MagicMock()
            mock_plumber.open.return_value = _PdfCtx(pages)
            monkeypatch.setattr(ztl, "pdfplumber", mock_plumber)
        return _setup

    def test_returns_empty_when_pdfplumber_unavailable(self, monkeypatch):
        monkeypatch.setattr(ztl, "pdfplumber", None)
        assert ztl.classify_pdf_pages(b"%PDF-stub") == []

    def test_text_only_page(self, fake_pdf_open):
        fake_pdf_open([_Page(text="A" * 50)])  # > 15 chars, no visuals
        result = ztl.classify_pdf_pages(b"%PDF-stub")
        assert result == [{"page_num": 1, "kind": "text", "text": "A" * 50}]

    def test_image_only_page(self, fake_pdf_open):
        fake_pdf_open([_Page(text="", images=[mock.MagicMock()])])
        result = ztl.classify_pdf_pages(b"%PDF-stub")
        assert result[0]["kind"] == "image_only"

    def test_mixed_page_with_raster(self, fake_pdf_open):
        fake_pdf_open([_Page(text="A" * 50, images=[mock.MagicMock()])])
        result = ztl.classify_pdf_pages(b"%PDF-stub")
        assert result[0]["kind"] == "mixed"

    def test_mixed_page_with_vector_chart(self, fake_pdf_open):
        """Text + vector chart (no raster) → mixed via _has_significant_vectors."""
        fake_pdf_open([_Page(
            text="Chart caption with enough characters here",
            curves=[mock.MagicMock()] * 10,  # 30 weighted, triggers
        )])
        result = ztl.classify_pdf_pages(b"%PDF-stub")
        assert result[0]["kind"] == "mixed"

    def test_text_page_with_minor_borders_not_mixed(self, fake_pdf_open):
        """4 rects (page border) + text → 'text', not 'mixed'."""
        fake_pdf_open([_Page(
            text="A" * 50,
            rects=[mock.MagicMock()] * 4,
        )])
        result = ztl.classify_pdf_pages(b"%PDF-stub")
        assert result[0]["kind"] == "text"

    def test_short_text_page_classified_image_only(self, fake_pdf_open):
        """Text below TEXT_PAGE_MIN_CHARS (15) → image_only even if non-empty."""
        fake_pdf_open([_Page(text="Page 2")])  # 6 chars
        result = ztl.classify_pdf_pages(b"%PDF-stub")
        assert result[0]["kind"] == "image_only"

    def test_per_page_exception_isolated(self, fake_pdf_open):
        """One bad page does not abort classification of others."""
        bad = mock.MagicMock()
        bad.extract_text.side_effect = RuntimeError("bad page")
        bad.images = []
        bad.rects = bad.lines = bad.curves = []
        fake_pdf_open([_Page(text="A" * 50), bad, _Page(text="B" * 50)])
        result = ztl.classify_pdf_pages(b"%PDF-stub")
        assert len(result) == 3
        assert result[0]["kind"] == "text"
        # Bad page falls into image_only by exception handler
        assert result[1]["kind"] == "image_only"
        assert result[2]["kind"] == "text"

    def test_pdfplumber_crash_warns_to_stderr(self, monkeypatch, capsys):
        mock_plumber = mock.MagicMock()
        mock_plumber.open.side_effect = RuntimeError("malformed PDF")
        monkeypatch.setattr(ztl, "pdfplumber", mock_plumber)

        result = ztl.classify_pdf_pages(b"%PDF-stub")
        assert result == []
        captured = capsys.readouterr()
        assert "pdfplumber failed to open PDF" in captured.err
