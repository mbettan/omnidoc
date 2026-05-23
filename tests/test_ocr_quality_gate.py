"""Unit tests for the OCR confidence gate and quality-validation helpers."""
import pytest
from unittest import mock
import os

import zip_to_llm as ztl


class TestAlphaRatio:
    """_compute_alpha_ratio: excludes whitespace, allows safe punctuation."""

    def test_empty_string(self):
        assert ztl._compute_alpha_ratio("") == 0.0

    def test_whitespace_only_returns_zero(self):
        """Pure whitespace should not pass the ratio (it's not 'good content')."""
        assert ztl._compute_alpha_ratio("   \n\t  ") == 0.0

    def test_pure_alphanumeric(self):
        assert ztl._compute_alpha_ratio("Hello123") == 1.0

    def test_punctuation_counts_as_good(self):
        # "Total: $124.50" → all non-space chars are alnum or safe punct
        assert ztl._compute_alpha_ratio("Total: $124.50") == 1.0

    def test_garbage_chars_lower_ratio(self):
        # `~` IS in safe punctuation; pick chars genuinely outside the set
        text = "abcd\u0001\u0002"  # control chars not in safe set
        ratio = ztl._compute_alpha_ratio(text)
        assert ratio == pytest.approx(4 / 6)

    def test_whitespace_excluded_from_denominator(self):
        # 'ab cd' → 4 non-space chars, all alnum → ratio 1.0
        assert ztl._compute_alpha_ratio("ab cd") == 1.0


class TestIsReliable:
    """_is_reliable: standard gate vs adaptive (high-confidence short text)."""

    def test_empty_text_unreliable(self):
        assert ztl._is_reliable("", 99.0, min_confidence=60) is False

    def test_high_conf_short_text_accepted(self):
        """'PAID' at 95% confidence should pass the adaptive gate."""
        assert ztl._is_reliable("PAID", 95.0, min_confidence=60) is True

    def test_high_conf_too_short_rejected(self):
        """Below SHORT_TEXT_MIN_CHARS even at high confidence."""
        assert ztl._is_reliable("OK", 99.0, min_confidence=60) is False

    def test_standard_gate_confidence_boundary(self):
        """Exactly at min_confidence with sufficient chars should pass."""
        text = "A" * ztl.OCR_MIN_CHARS  # 20 chars, ratio 1.0
        assert ztl._is_reliable(text, 60.0, min_confidence=60) is True
        assert ztl._is_reliable(text, 59.99, min_confidence=60) is False

    def test_standard_gate_char_boundary(self):
        """Exactly at OCR_MIN_CHARS with sufficient confidence."""
        text = "A" * ztl.OCR_MIN_CHARS
        assert ztl._is_reliable(text, 75.0, min_confidence=60) is True
        text_short = "A" * (ztl.OCR_MIN_CHARS - 1)
        assert ztl._is_reliable(text_short, 75.0, min_confidence=60) is False

    def test_standard_gate_alpha_ratio_boundary(self):
        """Mixed text that fails alpha ratio is rejected at standard confidence."""
        # 20 chars where < 50% are alnum/punct/space
        text = "a" + "\u0001" * 19  # 1 alnum + 19 control chars
        assert ztl._is_reliable(text, 75.0, min_confidence=60) is False

    def test_high_conf_lower_alpha_ratio_threshold(self):
        """High confidence applies relaxed alpha_ratio (0.4 vs 0.5)."""
        # 5 chars, 2 alnum, 3 control → ratio 0.4
        text = "ab\u0001\u0001\u0001"
        # alpha_ratio is exactly 0.4 → passes adaptive (>= 0.4)
        assert ztl._is_reliable(text, 95.0, min_confidence=60) is True


class TestOcrWithConfidence:
    """ocr_with_confidence: orchestrates image_to_data + fallback to image_to_string."""

    def test_returns_zeros_when_pytesseract_none(self, monkeypatch):
        monkeypatch.setattr(ztl, "pytesseract", None)
        text, conf, reliable = ztl.ocr_with_confidence(mock.MagicMock())
        assert text == ""
        assert conf == 0.0
        assert reliable is False

    def test_returns_zeros_when_image_none(self):
        text, conf, reliable = ztl.ocr_with_confidence(None)
        assert (text, conf, reliable) == ("", 0.0, False)

    def test_falls_back_to_image_to_string_on_mock_dict(self, monkeypatch):
        """When image_to_data returns non-dict (e.g. test mock), falls back."""
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = "not a dict"
        mock_tess.image_to_string.return_value = "A" * 30  # passes gate
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        text, conf, reliable = ztl.ocr_with_confidence(mock.MagicMock())
        assert text == "A" * 30
        assert conf == ztl.OCR_FALLBACK_CONFIDENCE  # 70.0
        assert reliable is True

    def test_fallback_returns_unreliable_for_short_text(self, monkeypatch):
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.side_effect = TypeError("mock raise")
        mock_tess.image_to_string.return_value = "short"
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        text, conf, reliable = ztl.ocr_with_confidence(mock.MagicMock())
        assert reliable is False

    def test_environment_error_falls_back_gracefully(self, monkeypatch):
        """TesseractNotFoundError inherits from EnvironmentError → caught."""
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.side_effect = EnvironmentError("tesseract missing")
        mock_tess.image_to_string.return_value = ""
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        text, conf, reliable = ztl.ocr_with_confidence(mock.MagicMock())
        assert (text, conf, reliable) == ("", 0.0, False)

    def test_high_confidence_data_passes_gate(self, monkeypatch):
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {
            "conf": [95, 92, 98],
            "text": ["This", "is", "extracted text with enough characters here"],
        }
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        text, conf, reliable = ztl.ocr_with_confidence(mock.MagicMock(), min_confidence=60)
        assert reliable is True
        assert conf == pytest.approx((95 + 92 + 98) / 3)

    def test_low_confidence_data_fails_gate(self, monkeypatch):
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {
            "conf": [40, 35, 30],
            "text": ["garbled", "noise", "from a bad scan with enough text"],
        }
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        _, _, reliable = ztl.ocr_with_confidence(mock.MagicMock(), min_confidence=60)
        assert reliable is False


class TestTesseractAvailability:
    def test_caches_result(self, monkeypatch):
        """Subsequent calls should not re-query pytesseract."""
        monkeypatch.setattr(ztl, "_TESSERACT_AVAILABLE", None)
        mock_tess = mock.MagicMock()
        mock_tess.get_tesseract_version.return_value = "5.0.0"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        assert ztl.is_tesseract_available() is True
        assert ztl.is_tesseract_available() is True
        # get_tesseract_version called only once
        mock_tess.get_tesseract_version.assert_called_once()

    def test_returns_false_when_pytesseract_none(self, monkeypatch):
        monkeypatch.setattr(ztl, "_TESSERACT_AVAILABLE", None)
        monkeypatch.setattr(ztl, "pytesseract", None)
        assert ztl.is_tesseract_available() is False

    def test_returns_false_when_binary_missing(self, monkeypatch):
        monkeypatch.setattr(ztl, "_TESSERACT_AVAILABLE", None)
        mock_tess = mock.MagicMock()
        mock_tess.get_tesseract_version.side_effect = EnvironmentError("not found")
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)
        assert ztl.is_tesseract_available() is False
