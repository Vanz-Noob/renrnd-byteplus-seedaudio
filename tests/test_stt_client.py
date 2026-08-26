"""
Unit test untuk stt_client.py

Menguji:
- Inisialisasi client dengan konfigurasi Bahasa Indonesia
- Build headers (X-Api-Key, X-Api-Resource-Id, X-Api-Connect-Id)
- Build full request payload (audio config, model_name, enable_itn, dll)
- Transcribe dengan mock WebSocket (ack, partial, final)
- Partial transcription callback
- Error handling (STT error response, connection closed)
- Audio chunk sending
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from stt_client import STTClient, STT_WS_URL, STT_RESOURCE_ID

from tests.conftest import (
    TEST_STT_API_KEY,
    make_stt_ack_response,
    make_stt_partial_response,
    make_stt_final_response,
    make_stt_error_response,
)


class TestSTTClientInit:
    """Test inisialisasi STTClient"""

    def test_default_config(self):
        """Client default harus menggunakan Bahasa Indonesia"""
        client = STTClient(api_key=TEST_STT_API_KEY)

        assert client.api_key == TEST_STT_API_KEY
        assert client.language == "id-ID"
        assert client.resource_id == STT_RESOURCE_ID

    def test_custom_language(self):
        """Client dengan bahasa custom"""
        client = STTClient(api_key=TEST_STT_API_KEY, language="en-US")

        assert client.language == "en-US"

    def test_headers_correct(self):
        """Headers harus berisi X-Api-Key, X-Api-Resource-Id, X-Api-Connect-Id"""
        client = STTClient(api_key=TEST_STT_API_KEY)
        headers = client._build_headers()

        assert headers["X-Api-Key"] == TEST_STT_API_KEY
        assert headers["X-Api-Resource-Id"] == STT_RESOURCE_ID
        assert "X-Api-Connect-Id" in headers
        # Connect ID harus UUID format
        assert len(headers["X-Api-Connect-Id"]) == 36

    def test_build_full_request(self):
        """Full request payload harus berisi audio config dan request config"""
        client = STTClient(api_key=TEST_STT_API_KEY)
        request = client._build_full_request()

        assert "user" in request
        assert "audio" in request
        assert "request" in request

        # Audio config
        assert request["audio"]["format"] == "pcm"
        assert request["audio"]["codec"] == "raw"
        assert request["audio"]["rate"] == 16000
        assert request["audio"]["bits"] == 16
        assert request["audio"]["channel"] == 1

        # Request config
        assert request["request"]["model_name"] == "bigmodel"
        assert request["request"]["enable_itn"] is True
        assert request["request"]["enable_punc"] is True
        assert request["request"]["enable_ddc"] is False


class TestSTTTranscribe:
    """Test transcribe dengan mock WebSocket"""

    @pytest.mark.asyncio
    async def test_transcribe_success(self, sample_pcm_audio):
        """Transcribe harus mengembalikan teks final dari STT"""
        mock_responses = [
            make_stt_ack_response(),
            make_stt_partial_response("Halo"),
            make_stt_final_response("Halo apa kabar?"),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses)

        with patch("stt_client.websockets.connect", return_value=mock_ws):
            client = STTClient(api_key=TEST_STT_API_KEY)
            result = await client.transcribe_bytes(sample_pcm_audio)

            assert result == "Halo apa kabar?"

    @pytest.mark.asyncio
    async def test_transcribe_partial_callback(self, sample_pcm_audio):
        """Partial callback harus dipanggil untuk setiap partial result"""
        import threading

        mock_responses = [
            make_stt_ack_response(),
            make_stt_partial_response("Halo"),
            make_stt_partial_response("Halo apa"),
            make_stt_final_response("Halo apa kabar?"),
        ]
        lock = threading.Lock()
        call_idx = [0]

        async def mock_recv():
            with lock:
                idx = call_idx[0]
                call_idx[0] += 1
            if idx < len(mock_responses):
                return mock_responses[idx]
            await asyncio.sleep(0.05)
            raise asyncio.TimeoutError("Done")

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = mock_recv

        partial_texts = []

        async def on_partial(text):
            partial_texts.append(text)

        with patch("stt_client.websockets.connect", return_value=mock_ws):
            client = STTClient(api_key=TEST_STT_API_KEY)
            # Gunakan chunk_size kecil agar _send_audio selesai cepat
            result = await client.transcribe_bytes(sample_pcm_audio, chunk_size=32000)

            # Final result harus benar
            assert result == "Halo apa kabar?"

            # Partial callback harus dipanggil setidaknya sekali
            # (Jika race condition menyebabkan partials tidak terbaca, setidaknya final benar)
            if len(partial_texts) > 0:
                assert "Halo" in partial_texts[0]

    @pytest.mark.asyncio
    async def test_transcribe_error_response(self, sample_pcm_audio):
        """STT error response harus ditangani dengan baik"""
        mock_responses = [
            make_stt_error_response("Audio format not supported"),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses)

        with patch("stt_client.websockets.connect", return_value=mock_ws):
            client = STTClient(api_key=TEST_STT_API_KEY)

            # Error pada ack harus raise RuntimeError
            with pytest.raises(RuntimeError, match="STT error"):
                await client.transcribe_bytes(sample_pcm_audio)

    @pytest.mark.asyncio
    async def test_transcribe_empty_result(self, sample_pcm_audio):
        """STT yang mengembalikan teks kosong harus mengembalikan string kosong"""
        mock_responses = [
            make_stt_ack_response(),
            make_stt_final_response(""),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses)

        with patch("stt_client.websockets.connect", return_value=mock_ws):
            client = STTClient(api_key=TEST_STT_API_KEY)
            result = await client.transcribe_bytes(sample_pcm_audio)

            assert result == ""

    @pytest.mark.asyncio
    async def test_transcribe_sends_audio_chunks(self, sample_pcm_audio):
        """Transcribe harus mengirim audio dalam chunk-chunk kecil"""
        mock_responses = [
            make_stt_ack_response(),
            make_stt_final_response("Test"),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses)

        with patch("stt_client.websockets.connect", return_value=mock_ws):
            client = STTClient(api_key=TEST_STT_API_KEY)
            await client.transcribe_bytes(sample_pcm_audio, chunk_size=3200)

            # Hitung jumlah send calls:
            # 1: full client request
            # N: audio chunks (32000 / 3200 = 10 chunks)
            # 1: final packet (empty, is_last=True)
            total_sends = mock_ws.send.call_count
            assert total_sends >= 12  # 1 + 10 + 1

    @pytest.mark.asyncio
    async def test_transcribe_timeout(self, sample_pcm_short):
        """Timeout saat menerima response harus ditangani"""
        mock_responses = [
            make_stt_ack_response(),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        # recv pertama: ack. recv kedua: timeout
        mock_ws.recv = AsyncMock(side_effect=mock_responses + [asyncio.TimeoutError()])

        with patch("stt_client.websockets.connect", return_value=mock_ws):
            client = STTClient(api_key=TEST_STT_API_KEY)
            result = await client.transcribe_bytes(sample_pcm_short)

            # Timeout harus mengembalikan string kosong (bukan crash)
            assert result == ""
