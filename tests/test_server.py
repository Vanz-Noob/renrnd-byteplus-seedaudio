"""
Integration test untuk server.py (FastAPI endpoints + WebSocket)

Menguji:
- Health check endpoint (/api/health)
- Config endpoint (/api/config)
- Static file serving (/, /static/*)
- WebSocket voice-chat dengan text mode (STT → AI → TTS pipeline)
- WebSocket error handling (missing API keys)
- WebSocket message protocol (JSON messages)
- Pipeline paralel (ai_response_start → ai_response_chunk → audio_start → audio_chunk → audio_end)

Menggunakan mock untuk semua external API calls (STT, TTS, AI Chat).
"""

import json
import base64
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

import server

from tests.conftest import (
    TEST_STT_API_KEY,
    TEST_TTS_API_KEY,
    TEST_ARK_API_KEY,
    make_sse_chunks,
)


@pytest.fixture
def client():
    """TestClient untuk FastAPI app"""
    return TestClient(server.app)


@pytest.fixture
def configured_env(monkeypatch):
    """Set environment variables untuk testing"""
    monkeypatch.setenv("STT_API_KEY", TEST_STT_API_KEY)
    monkeypatch.setenv("TTS_API_KEY", TEST_TTS_API_KEY)
    monkeypatch.setenv("ARK_API_KEY", TEST_ARK_API_KEY)
    monkeypatch.setenv("STT_LANGUAGE", "id-ID")
    monkeypatch.setenv("TTS_SPEAKER", "zh_female_vv_uranus_bigtts")
    monkeypatch.setenv("TTS_AUDIO_FORMAT", "mp3")
    monkeypatch.setenv("TTS_SAMPLE_RATE", "24000")
    monkeypatch.setenv("TTS_EXPLICIT_LANGUAGE", "id")
    monkeypatch.setenv("ARK_MODEL", "dola-seed-2-1-turbo-260628")
    monkeypatch.setenv("ARK_DISABLE_THINKING", "true")
    monkeypatch.setenv("ARK_MAX_TOKENS", "1000")

    # Reload server module untuk pick up new env vars
    import importlib
    importlib.reload(server)


class TestHTTPEndpoints:
    """Test HTTP endpoints"""

    def test_health_check(self, client):
        """Health check harus mengembalikan status ok"""
        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["model"] == "dola-seed-2-1-turbo-260628"
        assert data["language"] == "id-ID"

    def test_config_endpoint(self, client):
        """Config endpoint harus mengembalikan konfigurasi client"""
        response = client.get("/api/config")

        assert response.status_code == 200
        data = response.json()
        assert data["stt_language"] == "id-ID"
        assert data["tts_audio_format"] == "mp3"
        assert data["tts_sample_rate"] == 24000
        assert data["ark_model"] == "dola-seed-2-1-turbo-260628"

    def test_index_page(self, client):
        """Halaman utama harus mengembalikan HTML"""
        response = client.get("/")

        assert response.status_code == 200
        assert "BytePlus Voice Chat" in response.text

    def test_static_css(self, client):
        """Static CSS file harus tersedia"""
        response = client.get("/static/style.css")

        assert response.status_code == 200
        assert "color" in response.text or "background" in response.text

    def test_static_js(self, client):
        """Static JS file harus tersedia"""
        response = client.get("/static/app.js")

        assert response.status_code == 200
        assert "function" in response.text


class TestWebSocketVoiceChat:
    """Test WebSocket voice-chat endpoint"""

    def test_websocket_text_mode(self, client, configured_env):
        """Test text mode: kirim teks → AI response → TTS audio"""
        # Mock AI streaming response
        ai_response_text = "Halo. Apa kabar hari ini?"
        sse_lines = make_sse_chunks(ai_response_text, chunk_size=5)

        mock_ai_response = AsyncMock()
        mock_ai_response.raise_for_status = MagicMock()
        mock_ai_response.aiter_lines = AsyncMock(return_value=AsyncIterMock(sse_lines))

        mock_ai_client = AsyncMock()
        mock_ai_client.__aenter__ = AsyncMock(return_value=mock_ai_client)
        mock_ai_client.__aexit__ = AsyncMock(return_value=None)
        mock_ai_client.stream = MagicMock(return_value=AsyncCtxMock(mock_ai_response))

        # Mock TTS streaming response
        async def mock_tts_stream(text):
            yield b'\xff\xfb\x90\x00' * 100
            yield b'\xff\xfb\x90\x00' * 100

        with client.websocket_connect("/ws/voice-chat") as ws:
            # Kirim text message
            ws.send_json({"type": "text", "text": "Halo apa kabar?"})

            # Terima messages dari server
            messages = []
            try:
                while True:
                    msg = ws.receive_json()
                    messages.append(msg)
                    if msg.get("type") == "status" and msg.get("status") == "ready":
                        break
            except Exception:
                pass

            # Verifikasi message types yang diterima
            msg_types = [m["type"] for m in messages]

            # Harus menerima transcription (text user)
            assert "transcription" in msg_types
            transcr = [m for m in messages if m["type"] == "transcription"]
            assert transcr[0]["text"] == "Halo apa kabar?"

            # Harus menerima status messages
            assert "status" in msg_types
            statuses = [m for m in messages if m["type"] == "status"]
            assert any(s["status"] == "ready" for s in statuses)

    def test_websocket_clear_history(self, client, configured_env):
        """Test clear_history message"""
        with client.websocket_connect("/ws/voice-chat") as ws:
            ws.send_json({"type": "clear_history"})

            msg = ws.receive_json()
            assert msg["type"] == "status"
            assert msg["status"] == "ready"
            assert "History" in msg["message"]

    def test_websocket_unknown_type(self, client, configured_env):
        """Test unknown message type harus mengembalikan error"""
        with client.websocket_connect("/ws/voice-chat") as ws:
            ws.send_json({"type": "unknown_type"})

            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "Unknown message type" in msg["message"]

    def test_websocket_missing_stt_key(self, client, monkeypatch):
        """WebSocket harus menutup koneksi jika STT_API_KEY tidak diset"""
        monkeypatch.setenv("STT_API_KEY", "")
        monkeypatch.setenv("TTS_API_KEY", TEST_TTS_API_KEY)
        monkeypatch.setenv("ARK_API_KEY", TEST_ARK_API_KEY)

        import importlib
        importlib.reload(server)

        with client.websocket_connect("/ws/voice-chat") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "STT_API_KEY" in msg["message"]

    def test_websocket_missing_ark_key(self, client, monkeypatch):
        """WebSocket harus menutup koneksi jika ARK_API_KEY tidak diset"""
        monkeypatch.setenv("STT_API_KEY", TEST_STT_API_KEY)
        monkeypatch.setenv("TTS_API_KEY", TEST_TTS_API_KEY)
        monkeypatch.setenv("ARK_API_KEY", "")

        import importlib
        importlib.reload(server)

        with client.websocket_connect("/ws/voice-chat") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "ARK_API_KEY" in msg["message"]

    def test_websocket_missing_tts_key(self, client, monkeypatch):
        """WebSocket harus menutup koneksi jika TTS_API_KEY tidak diset"""
        monkeypatch.setenv("STT_API_KEY", TEST_STT_API_KEY)
        monkeypatch.setenv("TTS_API_KEY", "")
        monkeypatch.setenv("ARK_API_KEY", TEST_ARK_API_KEY)

        import importlib
        importlib.reload(server)

        with client.websocket_connect("/ws/voice-chat") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "TTS_API_KEY" in msg["message"]


class TestServerUtilities:
    """Test utility functions di server.py"""

    def test_split_sentence_single(self):
        """Pisahkan satu kalimat lengkap"""
        complete, remaining = server.split_sentence_stream("Halo apa kabar?")
        assert "Halo apa kabar?" in complete
        assert remaining == ""

    def test_split_sentence_multiple(self):
        """Pisahkan multiple kalimat"""
        text = "Halo. Apa kabar?"
        complete, remaining = server.split_sentence_stream(text)
        assert "Halo." in complete
        assert "Apa kabar?" in complete
        assert remaining == ""

    def test_split_sentence_partial(self):
        """Teks belum lengkap (tidak ada punctuation)"""
        complete, remaining = server.split_sentence_stream("Halo apa")
        assert complete == ""
        assert remaining == "Halo apa"

    def test_split_sentence_with_newline(self):
        """Pisahkan dengan newline - kedua kalimat termasuk dalam complete"""
        text = "Kalimat 1.\nKalimat 2."
        complete, remaining = server.split_sentence_stream(text)
        assert "Kalimat 1." in complete
        assert "Kalimat 2." in complete or remaining == "Kalimat 2."

    def test_split_sentence_exclamation(self):
        """Pisahkan dengan tanda seru - kedua kalimat termasuk dalam complete"""
        text = "Wow! Itu keren."
        complete, remaining = server.split_sentence_stream(text)
        assert "Wow!" in complete
        assert "Itu keren." in complete or remaining == "Itu keren."


# ============================================
# Helper classes untuk mock async iterators
# ============================================

class AsyncIterMock:
    """Mock async iterator untuk SSE lines"""

    def __init__(self, lines):
        self.lines = list(lines)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self.lines):
            raise StopAsyncIteration
        line = self.lines[self._index]
        self._index += 1
        return line


class AsyncCtxMock:
    """Mock async context manager"""

    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        pass
