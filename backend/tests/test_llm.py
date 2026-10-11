from unittest.mock import MagicMock, patch
import pytest

from app import config, llm


def test_mock_mode():
    with patch.object(config, "MOCK_LLM", True), patch.object(
        config, "LLM_PROVIDER", "mock"
    ):
        text, usage = llm.complete("system prompt", "user query")
        assert len(text) > 0
        assert usage["llm_calls"] == 0
        assert usage["tokens"] == 0
        assert usage["provider"] == "mock"
        assert usage["fallback"] is False


def test_gemini_missing_key_fallback():
    with patch.object(config, "MOCK_LLM", False), patch.object(
        config, "LLM_PROVIDER", "gemini"
    ), patch.object(config, "GEMINI_API_KEY", ""):
        text, usage = llm.complete("system prompt", "user query")
        assert len(text) > 0
        assert usage["fallback"] is True
        assert usage["provider"] == "gemini"


def test_gemini_success():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": "Order O-101 was reassigned to CNC-2."}]
                }
            }
        ],
        "usageMetadata": {"totalTokenCount": 42},
    }

    with patch.object(config, "MOCK_LLM", False), patch.object(
        config, "LLM_PROVIDER", "gemini"
    ), patch.object(config, "GEMINI_API_KEY", "secret-test-key"), patch(
        "httpx.Client.post", return_value=mock_resp
    ):
        text, usage = llm.complete("system prompt", "user query")
        assert text == "Order O-101 was reassigned to CNC-2."
        assert usage["llm_calls"] == 1
        assert usage["tokens"] == 42
        assert usage["fallback"] is False
        assert usage["provider"] == "gemini"


def test_gemini_retry_and_fallback_on_network_error():
    with patch.object(config, "MOCK_LLM", False), patch.object(
        config, "LLM_PROVIDER", "gemini"
    ), patch.object(config, "GEMINI_API_KEY", "secret-test-key"), patch(
        "httpx.Client.post", side_effect=Exception("Connection refused")
    ), patch(
        "time.sleep", return_value=None
    ):
        text, usage = llm.complete("system prompt", "user query")
        assert len(text) > 0
        assert usage["llm_calls"] == 2
        assert usage["fallback"] is True
        assert usage["provider"] == "gemini"


def test_api_key_not_leaked_in_metadata_or_output():
    secret_key = "AIzaSy_TEST_SECRET_KEY_12345"
    with patch.object(config, "MOCK_LLM", False), patch.object(
        config, "LLM_PROVIDER", "gemini"
    ), patch.object(config, "GEMINI_API_KEY", secret_key), patch(
        "httpx.Client.post", side_effect=Exception(f"Error containing {secret_key}")
    ), patch(
        "time.sleep", return_value=None
    ):
        text, usage = llm.complete("system prompt", "user query")
        assert secret_key not in text
        assert secret_key not in str(usage)

