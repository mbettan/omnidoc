#!/usr/bin/env python3
"""
Comprehensive test suite verifying the fallback from Tesseract OCR to Gemini 3.1 Pro Preview
across various image extraction scenarios (long text, 8K resolution without text, errors, etc.).
"""

import io
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure src/ is in sys.path so we can import zip_to_llm
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import zip_to_llm as ztl


def _create_dummy_png(width: int = 1, height: int = 1, color: str = 'blue') -> bytes:
    """Helper to generate in-memory PNG image bytes."""
    from PIL import Image
    img = Image.new('RGB', (width, height), color=color)
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()


def test_extract_image_ocr_success_long_text():
    """Test scenario 1: Image contains long text; OCR succeeds, Gemini is skipped."""
    img_bytes = _create_dummy_png(100, 100, 'white')
    long_text = "This is a very long document containing extensive legal and financial records " * 10

    with mock.patch.object(ztl, 'pytesseract') as mock_tesseract, \
         mock.patch.object(ztl, 'genai') as mock_genai:
        
        mock_tesseract.image_to_string.return_value = long_text
        
        out = ztl.extract_image(img_bytes, "scanned_doc.png")

        # Verify Tesseract was called
        mock_tesseract.image_to_string.assert_called_once()
        # Verify Gemini was never called
        mock_genai.Client.assert_not_called()

        assert long_text.strip() in out


def test_extract_image_8k_resolution_no_text():
    """Test scenario 2: An 8K resolution image without text; OCR returns empty, Gemini analyzes."""
    # 8K Ultra HD resolution is 7680 x 4320
    img_bytes = _create_dummy_png(7680, 4320, 'black')

    with mock.patch.object(ztl, 'pytesseract') as mock_tesseract, \
         mock.patch.object(ztl, 'genai') as mock_genai, \
         mock.patch.object(ztl, 'types') as mock_types, \
         mock.patch.dict(os.environ, {"PROJECT_ID": "test-project", "OMNIDOC_VISION_MODEL": "gemini-3.1-pro-preview"}):
        
        mock_tesseract.image_to_string.return_value = ""
        
        mock_client_instance = mock.MagicMock()
        mock_genai.Client.return_value = mock_client_instance
        mock_response = mock.MagicMock()
        mock_response.text = "An 8K ultra-high-resolution photograph showing a serene landscape with no text."
        mock_client_instance.models.generate_content.return_value = mock_response

        opts = ztl.ExtractOptions(vision_fallback="gemini")
        out = ztl.extract_image(img_bytes, "8k_photo.png", opts=opts)

        mock_tesseract.image_to_string.assert_called_once()
        mock_genai.Client.assert_called_once_with(vertexai=True, project="test-project", location="global")
        mock_client_instance.models.generate_content.assert_called_once()
        
        _, kwargs = mock_client_instance.models.generate_content.call_args
        assert kwargs['model'] == "gemini-3.1-pro-preview"

        assert "_[Image Description (Gemini)]_" in out
        assert "An 8K ultra-high-resolution photograph showing a serene landscape with no text." in out


def test_extract_image_gemini_fallback_api_error():
    """Test scenario 3: OCR returns empty, but Gemini fallback encounters an API exception."""
    img_bytes = _create_dummy_png(10, 10, 'green')

    with mock.patch.object(ztl, 'pytesseract') as mock_tesseract, \
         mock.patch.object(ztl, 'genai') as mock_genai, \
         mock.patch.object(ztl, 'types') as mock_types, \
         mock.patch.dict(os.environ, {"PROJECT_ID": "test-project"}):
        
        mock_tesseract.image_to_string.return_value = ""
        
        mock_client_instance = mock.MagicMock()
        mock_genai.Client.return_value = mock_client_instance
        # Simulate Vertex AI quota or network error
        mock_client_instance.models.generate_content.side_effect = RuntimeError("Vertex AI quota exceeded")

        opts = ztl.ExtractOptions(vision_fallback="gemini")
        out = ztl.extract_image(img_bytes, "error_photo.png", opts=opts)

        mock_tesseract.image_to_string.assert_called_once()
        mock_client_instance.models.generate_content.assert_called_once()

        assert "vision fallback error: Vertex AI quota exceeded" in out


def test_extract_image_ocr_exception():
    """Test scenario 4: Tesseract OCR raises an exception; should not trigger Gemini."""
    img_bytes = _create_dummy_png(50, 50, 'yellow')

    with mock.patch.object(ztl, 'pytesseract') as mock_tesseract, \
         mock.patch.object(ztl, 'genai') as mock_genai:
        
        mock_tesseract.image_to_string.side_effect = RuntimeError("Tesseract binary not found")
        
        out = ztl.extract_image(img_bytes, "corrupt.png")

        mock_tesseract.image_to_string.assert_called_once()
        mock_genai.Client.assert_not_called()

        assert "_[Image OCR error: Tesseract binary not found]_" in out


def test_extract_image_invalid_image_data():
    """Test scenario 5: Non-image garbage bytes passed; Pillow raises exception."""
    bad_bytes = b"definitely not a png image file"

    with mock.patch.object(ztl, 'pytesseract') as mock_tesseract, \
         mock.patch.object(ztl, 'Image') as mock_image, \
         mock.patch.object(ztl, 'genai') as mock_genai:
        
        mock_image.open.side_effect = IOError("cannot identify image file")
        
        out = ztl.extract_image(bad_bytes, "bad.png")

        mock_genai.Client.assert_not_called()
        assert "_[Image OCR error: cannot identify image file]_" in out


def test_extract_image_no_genai_sdk(monkeypatch):
    """Test scenario 6: OCR returns empty, but google-genai SDK is not installed."""
    img_bytes = _create_dummy_png(20, 20, 'purple')

    monkeypatch.setattr(ztl, 'genai', None)

    with mock.patch.object(ztl, 'pytesseract') as mock_tesseract:
        mock_tesseract.image_to_string.return_value = ""

        out = ztl.extract_image(img_bytes, "no_sdk.png")

        mock_tesseract.image_to_string.assert_called_once()
        assert "_[no text detected by OCR]_" in out
