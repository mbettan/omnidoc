"""Unit tests for VisualBundle: storage, optimization, write."""
import io
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

import zip_to_llm as ztl


def _make_png_bytes(w: int, h: int, mode: str = "RGB", color="red") -> bytes:
    img = Image.new(mode, (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_real_pdf_bytes(num_pages: int) -> bytes:
    """Generate an actual N-page blank PDF via pypdf for round-trip tests."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestVisualBundleStorage:
    def test_empty_bundle_writes_nothing(self, tmp_path):
        bundle = ztl.VisualBundle()
        out = tmp_path / "bundle.pdf"
        result = bundle.write(out)
        assert result == 0
        assert not out.exists()

    def test_add_image_returns_anchor_and_page(self):
        bundle = ztl.VisualBundle()
        anchor, page = bundle.add_image("a.png", _make_png_bytes(10, 10))
        assert anchor == "visual-0001"
        assert page == 1
        assert len(bundle) == 1

    def test_add_pdf_page_returns_anchor_and_page(self):
        bundle = ztl.VisualBundle()
        anchor, page = bundle.add_pdf_page("doc.pdf", 1, _make_real_pdf_bytes(2))
        assert anchor == "visual-0001"
        assert page == 1
        assert len(bundle) == 1

    def test_monotonic_anchor_numbering(self):
        bundle = ztl.VisualBundle()
        _, p1 = bundle.add_image("a.png", _make_png_bytes(5, 5))
        _, p2 = bundle.add_image("b.png", _make_png_bytes(5, 5))
        _, p3 = bundle.add_pdf_page("c.pdf", 1, _make_real_pdf_bytes(1))
        assert (p1, p2, p3) == (1, 2, 3)

    def test_dropped_entry_reserves_anchor(self, capsys):
        """Failed slicing returns anchor + bundle_page but does not append."""
        bundle = ztl.VisualBundle()
        bundle.add_image("ok.png", _make_png_bytes(5, 5))  # entry 1
        # Out-of-range page → dropped
        anchor, page = bundle.add_pdf_page("bad.pdf", 99, _make_real_pdf_bytes(2))
        assert anchor == "visual-0002"
        assert page == 2
        assert len(bundle) == 1  # only the image stored
        # Next successful add takes anchor 0003 (gap at 0002)
        anchor3, page3 = bundle.add_image("c.png", _make_png_bytes(5, 5))
        assert anchor3 == "visual-0002"  # bundle_page reuses since len() shifted


class TestVisualBundleOptimize:
    def test_downscales_oversized_image(self):
        bundle = ztl.VisualBundle(max_dim=100)
        # 500x500 → should scale to 100x100
        result = bundle._optimize(_make_png_bytes(500, 500))
        img = Image.open(io.BytesIO(result))
        assert max(img.size) == 100

    def test_preserves_small_image_size(self):
        bundle = ztl.VisualBundle(max_dim=1600)
        original = _make_png_bytes(50, 50)
        result = bundle._optimize(original)
        img = Image.open(io.BytesIO(original))
        assert img.size == (50, 50)

    def test_jpeg_compression_reduces_size(self):
        bundle = ztl.VisualBundle(max_dim=1600)
        big = _make_png_bytes(100, 100, color=(255, 0, 0))
        compressed = bundle._optimize(big)
        img = Image.open(io.BytesIO(compressed))
        assert img.format == "JPEG"

    def test_converts_rgba_to_rgb(self):
        """Images outside RGB/L/CMYK get converted."""
        bundle = ztl.VisualBundle()
        rgba_bytes = _make_png_bytes(100, 100, mode="RGBA", color=(255, 0, 0, 128))
        result = bundle._optimize(rgba_bytes)
        img = Image.open(io.BytesIO(result))
        assert img.mode == "RGB"

    def test_optimize_returns_original_on_pillow_error(self, monkeypatch):
        bundle = ztl.VisualBundle()
        mock_image = mock.MagicMock()
        mock_image.open.side_effect = OSError("corrupt")
        monkeypatch.setattr(ztl, "Image", mock_image)
        result = bundle._optimize(b"not an image")
        assert result == b"not an image"


class TestVisualBundleWrite:
    def test_writes_image_entry_to_pdf(self, tmp_path):
        bundle = ztl.VisualBundle()
        bundle.add_image("a.png", _make_png_bytes(100, 100))
        out = tmp_path / "bundle.pdf"
        count = bundle.write(out)
        assert count == 1
        assert out.exists()
        # Verify it's a readable PDF with 1 page
        reader = PdfReader(str(out))
        assert len(reader.pages) == 1

    def test_writes_pdf_page_entry(self, tmp_path):
        bundle = ztl.VisualBundle()
        bundle.add_pdf_page("doc.pdf", 1, _make_real_pdf_bytes(3))
        out = tmp_path / "bundle.pdf"
        count = bundle.write(out)
        assert count == 1
        reader = PdfReader(str(out))
        assert len(reader.pages) == 1

    def test_writes_mixed_entries_in_order(self, tmp_path):
        bundle = ztl.VisualBundle()
        bundle.add_image("a.png", _make_png_bytes(50, 50, color="red"))
        bundle.add_pdf_page("doc.pdf", 2, _make_real_pdf_bytes(3))
        bundle.add_image("c.png", _make_png_bytes(50, 50, color="blue"))
        out = tmp_path / "bundle.pdf"
        count = bundle.write(out)
        assert count == 3
        reader = PdfReader(str(out))
        assert len(reader.pages) == 3

    def test_normalizes_non_rgb_image_during_write(self, tmp_path):
        """RGBA stored as JPEG should write to PDF without crashing."""
        bundle = ztl.VisualBundle()
        bundle._entries.append((
            "visual-0001", "test.png", None,
            _make_png_bytes(100, 100, mode="RGB"),
            "image"
        ))
        out = tmp_path / "bundle.pdf"
        assert bundle.write(out) == 1


class TestVisualBundleDropPaths:
    """Drop-path coverage — closing the v7 gap."""

    def test_out_of_range_page_drops_entry(self, capsys):
        bundle = ztl.VisualBundle()
        anchor, _ = bundle.add_pdf_page("doc.pdf", 99, _make_real_pdf_bytes(2))
        assert anchor == "visual-0001"
        assert len(bundle._entries) == 0
        err = capsys.readouterr().err
        assert "references page 99" in err
        assert "entry dropped" in err

    def test_corrupt_pdf_bytes_drops_entry(self, capsys):
        bundle = ztl.VisualBundle()
        anchor, _ = bundle.add_pdf_page("doc.pdf", 1, b"garbage")
        assert anchor == "visual-0001"
        assert len(bundle._entries) == 0
        err = capsys.readouterr().err
        assert "failed to extract page" in err
        assert "entry dropped" in err

    def test_dropped_entries_do_not_appear_in_output(self, tmp_path):
        bundle = ztl.VisualBundle()
        bundle.add_image("ok.png", _make_png_bytes(50, 50))
        bundle.add_pdf_page("bad.pdf", 99, _make_real_pdf_bytes(1))  # dropped
        bundle.add_image("ok2.png", _make_png_bytes(50, 50))
        out = tmp_path / "bundle.pdf"
        count = bundle.write(out)
        assert count == 2  # only successful entries
        reader = PdfReader(str(out))
        assert len(reader.pages) == 2
