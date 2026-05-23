#!/usr/bin/env python3
"""
Unit and integration tests for hybrid visual bundle isolation and confidence gate features.
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

class _FakePage:
    def __init__(self, text: str, images=None):
        self._text = text
        self.images = images or []

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


class TestHybridVisualBundle:
    def test_standalone_image_isolated_on_low_confidence(self, tmp_zip, tmp_path, monkeypatch):
        # Mock pytesseract image_to_data to return low confidence data
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {
            "conf": [45, 50],
            "text": ["garbage", "scan"]
        }
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        # Mock PIL Image.open
        mock_img = mock.MagicMock()
        mock_img.mode = "RGB"
        mock_img.width = 100
        mock_img.height = 100
        mock_img_class = mock.MagicMock()
        mock_img_class.open.return_value = mock_img
        monkeypatch.setattr(ztl, "Image", mock_img_class)

        # Mock pypdf PdfWriter
        mock_writer = mock.MagicMock()
        mock_writer.pages = [mock.MagicMock()]
        monkeypatch.setattr("pypdf.PdfWriter", lambda *args, **kwargs: mock_writer)

        zpath = tmp_zip({"photo.png": b"\x89PNG\r\n\x1a\n"})
        visual_pdf = tmp_path / "out_visual.pdf"

        out = ztl.process_zip(
            zpath,
            isolate_non_text=True,
            non_text_pdf_path=visual_pdf,
            show_progress=False,
            ocr_min_confidence=60
        )

        # Output should contain a stable anchor placeholder
        assert "Image with no extractable text" in out
        assert "visual-0001" in out
        assert "photo.png" in out
        assert mock_writer.write.called

    def test_pdf_page_classification_and_isolation(self, tmp_zip, tmp_path, monkeypatch):
        # Mock pdfplumber to return one text page and one mixed page
        fake_plumber = mock.MagicMock()
        fake_plumber.open.return_value = _FakePdf([
            _FakePage("Pristine text that has more than fifty characters to classify as a normal text page."),
            _FakePage("", images=[mock.MagicMock()]) # Mixed/image_only page
        ])
        monkeypatch.setattr(ztl, "pdfplumber", fake_plumber)

        # Mock OCR to fail or have low confidence
        monkeypatch.setattr(ztl, "convert_from_bytes", lambda *args, **kwargs: [mock.MagicMock(), mock.MagicMock()])
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [30], "text": ["unreliable"]}
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        # Mock pypdf PdfWriter and PdfReader
        mock_reader = mock.MagicMock()
        mock_reader.pages = [mock.MagicMock(), mock.MagicMock()]
        mock_writer = mock.MagicMock()
        mock_writer.pages = [mock.MagicMock()]
        monkeypatch.setattr("pypdf.PdfReader", lambda *args, **kwargs: mock_reader)
        monkeypatch.setattr("pypdf.PdfWriter", lambda *args, **kwargs: mock_writer)

        zpath = tmp_zip({"scanned.pdf": b"%PDF-stub"})
        visual_pdf = tmp_path / "out_visual.pdf"

        out = ztl.process_zip(
            zpath,
            isolate_non_text=True,
            non_text_pdf_path=visual_pdf,
            show_progress=False,
            ocr_min_confidence=60
        )

        # Pristine text is extracted
        assert "Pristine text" in out
        # Mixed/low-confidence page is isolated to the visual bundle
        assert "Visual content" in out
        assert "visual-0001" in out
        assert "scanned.pdf" in out
        assert mock_writer.write.called

    def test_no_visual_bundle_cli_behavior(self, tmp_zip, tmp_path, monkeypatch):
        # Mock pytesseract to return empty string
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [], "text": []}
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        # Mock PIL Image.open
        mock_img = mock.MagicMock()
        mock_img.mode = "RGB"
        mock_img_class = mock.MagicMock()
        mock_img_class.open.return_value = mock_img
        monkeypatch.setattr(ztl, "Image", mock_img_class)

        zpath = tmp_zip({"photo.png": b"\x89PNG\r\n\x1a\n"})
        visual_pdf = tmp_path / "out_visual.pdf"

        out = ztl.process_zip(
            zpath,
            isolate_non_text=False,
            non_text_pdf_path=visual_pdf,
            show_progress=False
        )

        # Low quality OCR fails and output falls back to default warning
        assert "no text detected by OCR" in out
        assert "visual-0001" not in out
        assert not visual_pdf.exists()

    def test_pypdf_missing_raises_value_error(self, tmp_zip, monkeypatch):
        monkeypatch.setitem(sys.modules, "pypdf", None)

        zpath = tmp_zip({"photo.png": b"hello"})
        with pytest.raises(ValueError) as exc:
            ztl.process_zip(zpath, isolate_non_text=True)
        assert "pypdf must be installed" in str(exc.value)

    def test_visual_bundle_drop_on_pypdf_failure(self, monkeypatch, capsys):
        # Force add_pdf_page to raise an exception by feeding invalid bytes and forcing PdfReader failure
        bundle = ztl.VisualBundle()
        
        # Test 1: Slicing failure drop on corrupt bytes
        anchor, page = bundle.add_pdf_page("test.pdf", page_num=5, page_bytes=b"%PDF-stub")
        assert anchor == "visual-0001"
        assert page == 1
        assert len(bundle._entries) == 0 # Discarded!

        captured = capsys.readouterr()
        assert "Warning: failed to extract page 5 from test.pdf" in captured.err

        # Test 2: Parsing error drop on corrupt garbage
        anchor, page = bundle.add_pdf_page("test.pdf", page_num=1, page_bytes=b"corrupt garbage bytes")
        assert anchor == "visual-0001"
        assert page == 1
        assert len(bundle._entries) == 0 # Discarded!

        captured = capsys.readouterr()
        assert "Warning: failed to extract page 1 from test.pdf" in captured.err
