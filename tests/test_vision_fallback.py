"""Vision (Gemini) fallback path: gating, env var handling, error surfacing."""
import io
import os
from unittest import mock

import pytest
from PIL import Image

import zip_to_llm as ztl


def _png():
    img = Image.new("RGB", (10, 10), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestVisionFallbackGating:
    def test_does_not_run_when_vision_fallback_none(self, monkeypatch):
        mock_tess = mock.MagicMock()
        mock_tess.image_to_string.return_value = ""
        mock_tess.image_to_data.return_value = {"conf": [], "text": []}
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        mock_genai = mock.MagicMock()
        monkeypatch.setattr(ztl, "genai", mock_genai)
        monkeypatch.setattr(ztl, "types", mock.MagicMock())

        opts = ztl.ExtractOptions(vision_fallback="none")
        result = ztl.extract_image(_png(), "x.png", opts=opts)

        mock_genai.Client.assert_not_called()
        assert "no text detected" in result

    def test_runs_when_vision_fallback_gemini(self, monkeypatch):
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [], "text": []}
        mock_tess.image_to_string.return_value = ""
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        mock_genai = mock.MagicMock()
        client = mock.MagicMock()
        mock_genai.Client.return_value = client
        response = mock.MagicMock()
        response.text = "Description here"
        client.models.generate_content.return_value = response
        monkeypatch.setattr(ztl, "genai", mock_genai)
        monkeypatch.setattr(ztl, "types", mock.MagicMock())

        with mock.patch.dict(os.environ, {"PROJECT_ID": "p"}):
            opts = ztl.ExtractOptions(vision_fallback="gemini")
            result = ztl.extract_image(_png(), "x.png", opts=opts)

        mock_genai.Client.assert_called_once()
        assert "Description here" in result


class TestVisionFallbackConfiguration:
    def test_missing_project_id_returns_clear_message(self, monkeypatch):
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [], "text": []}
        mock_tess.image_to_string.return_value = ""
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)
        mock_genai = mock.MagicMock()
        monkeypatch.setattr(ztl, "genai", mock_genai)
        monkeypatch.setattr(ztl, "types", mock.MagicMock())

        with mock.patch.dict(os.environ, {}, clear=True):
            opts = ztl.ExtractOptions(vision_fallback="gemini")
            result = ztl.extract_image(_png(), "x.png", opts=opts)

        mock_genai.Client.assert_not_called()
        assert "PROJECT_ID" in result

    def test_default_model_used_when_env_unset(self, monkeypatch):
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [], "text": []}
        mock_tess.image_to_string.return_value = ""
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        mock_genai = mock.MagicMock()
        client = mock.MagicMock()
        mock_genai.Client.return_value = client
        response = mock.MagicMock()
        response.text = "ok"
        client.models.generate_content.return_value = response
        monkeypatch.setattr(ztl, "genai", mock_genai)
        monkeypatch.setattr(ztl, "types", mock.MagicMock())

        env = {"PROJECT_ID": "p"}
        with mock.patch.dict(os.environ, env, clear=True):
            opts = ztl.ExtractOptions(vision_fallback="gemini")
            ztl.extract_image(_png(), "x.png", opts=opts)

        kwargs = client.models.generate_content.call_args[1]
        # Documented default: gemini-3.1-pro-preview
        assert kwargs["model"] == "gemini-3.1-pro-preview"

    def test_custom_model_via_env_var(self, monkeypatch):
        mock_tess = mock.MagicMock()
        mock_tess.image_to_data.return_value = {"conf": [], "text": []}
        mock_tess.image_to_string.return_value = ""
        mock_tess.Output.DICT = "dict"
        monkeypatch.setattr(ztl, "pytesseract", mock_tess)

        mock_genai = mock.MagicMock()
        client = mock.MagicMock()
        mock_genai.Client.return_value = client
        response = mock.MagicMock()
        response.text = "ok"
        client.models.generate_content.return_value = response
        monkeypatch.setattr(ztl, "genai", mock_genai)
        monkeypatch.setattr(ztl, "types", mock.MagicMock())

        with mock.patch.dict(os.environ, {"PROJECT_ID": "p", "OMNIDOC_VISION_MODEL": "gemini-pro-v2"}):
            opts = ztl.ExtractOptions(vision_fallback="gemini")
            ztl.extract_image(_png(), "x.png", opts=opts)

        assert client.models.generate_content.call_args[1]["model"] == "gemini-pro-v2"
