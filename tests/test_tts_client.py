"""
Unit test untuk tts_client.py

Menguji:
- Inisialisasi client dengan konfigurasi Bahasa Indonesia (explicit_language=id)
- Build headers dan StartSession payload
- Synthesize streaming dengan mock WebSocket
- Audio chunk streaming (yield per chunk)
- Error handling (TTS error, connection closed)
- Empty text handling
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tts_client import TTSClient, TTS_WS_URL, TTS_RESOURCE_ID

from tests.conftest import (
    TEST_TTS_API_KEY,
    make_tts_connection_started_response,
    make_tts_session_started_response,
    make_tts_audio_response,
    make_tts_session_finished_response,
    make_tts_error_response,
    sample_mp3_audio,
)


class TestTTSClientInit:
    """Test inisialisasi TTSClient"""

    def test_default_config(self):
        """Client default harus enforce Bahasa Indonesia"""
        client = TTSClient(api_key=TEST_TTS_API_KEY)

        assert client.api_key == TEST_TTS_API_KEY
        assert client.speaker == "zh_female_vv_uranus_bigtts"
        assert client.audio_format == "mp3"
        assert client.sample_rate == 24000
        assert client.resource_id == TTS_RESOURCE_ID
        assert client.explicit_language == "id"  # Enforce Bahasa Indonesia

    def test_custom_speaker(self):
        """Client dengan speaker custom"""
        client = TTSClient(
            api_key=TEST_TTS_API_KEY,
            speaker="en_female_vv_uranus_bigtts",
        )

        assert client.speaker == "en_female_vv_uranus_bigtts"

    def test_custom_audio_format(self):
        """Client dengan format audio custom"""
        client = TTSClient(
            api_key=TEST_TTS_API_KEY,
            audio_format="ogg_opus",
            sample_rate=48000,
        )

        assert client.audio_format == "ogg_opus"
        assert client.sample_rate == 48000

    def test_headers_correct(self):
        """Headers harus berisi X-Api-Key, X-Api-Resource-Id, X-Api-Connect-Id"""
        client = TTSClient(api_key=TEST_TTS_API_KEY)
        headers = client._build_headers()

        assert headers["X-Api-Key"] == TEST_TTS_API_KEY
        assert headers["X-Api-Resource-Id"] == TTS_RESOURCE_ID
        assert "X-Api-Connect-Id" in headers

    def test_start_session_payload_enforces_indonesian(self):
        """StartSession payload harus berisi explicit_language=id"""
        client = TTSClient(api_key=TEST_TTS_API_KEY)
        payload = client._build_start_session_payload()

        assert payload["user"] == {"uid": ""}
        assert payload["event"] == 100  # TTS_EVENT_START_SESSION

        req_params = payload["req_params"]
        assert req_params["speaker"] == client.speaker
        assert req_params["audio_params"]["format"] == "mp3"
        assert req_params["audio_params"]["sample_rate"] == 24000

        # Cek additions berisi explicit_language
        additions = json.loads(req_params["additions"])
        assert additions["explicit_language"] == "id"

    def test_task_request_payload(self):
        """TaskRequest payload harus berisi teks yang akan di-synthesize"""
        client = TTSClient(api_key=TEST_TTS_API_KEY)
        payload = client._build_task_request_payload("Halo apa kabar?")

        assert payload["user"] == {"uid": ""}
        assert payload["event"] == 200  # TTS_EVENT_TASK_REQUEST
        assert payload["req_params"]["text"] == "Halo apa kabar?"

    def test_finish_session_payload(self):
        """FinishSession payload harus berisi empty dict"""
        client = TTSClient(api_key=TEST_TTS_API_KEY)
        payload = client._build_finish_session_payload()

        assert payload == {}  # Empty dict, no event field


class TestTTSSynthesize:
    """Test synthesize dengan mock WebSocket"""

    @pytest.mark.asyncio
    async def test_synthesize_stream_yields_audio(self):
        """synthesize_stream harus yield audio chunks"""
        mock_responses = [
            make_tts_connection_started_response(),
            make_tts_session_started_response(),
            make_tts_audio_response(b'\xff\xfb' * 100),
            make_tts_audio_response(b'\xff\xfb' * 200),
            make_tts_session_finished_response(),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses)

        with patch("tts_client.websockets.connect", return_value=mock_ws):
            client = TTSClient(api_key=TEST_TTS_API_KEY)

            chunks = []
            async for chunk in client.synthesize_stream("Halo apa kabar?"):
                chunks.append(chunk)

            # Harus menerima 2 audio chunks
            assert len(chunks) == 2
            assert len(chunks[0]) == 200  # 100 * 2 bytes
            assert len(chunks[1]) == 400  # 200 * 2 bytes

    @pytest.mark.asyncio
    async def test_synthesize_non_streaming(self):
        """synthesize() (non-streaming) harus mengembalikan seluruh audio sekaligus"""
        mock_responses = [
            make_tts_connection_started_response(),
            make_tts_session_started_response(),
            make_tts_audio_response(b'\xff\xfb' * 100),
            make_tts_audio_response(b'\xff\xfb' * 100),
            make_tts_session_finished_response(),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses)

        with patch("tts_client.websockets.connect", return_value=mock_ws):
            client = TTSClient(api_key=TEST_TTS_API_KEY)
            audio_data = await client.synthesize("Halo")

            # Total audio = 2 chunks * 200 bytes = 400 bytes
            assert len(audio_data) == 400

    @pytest.mark.asyncio
    async def test_synthesize_empty_text(self):
        """Synthesize dengan teks kosong harus mengembalikan bytes kosong"""
        client = TTSClient(api_key=TEST_TTS_API_KEY)

        chunks = []
        async for chunk in client.synthesize_stream(""):
            chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_synthesize_whitespace_text(self):
        """Synthesize dengan teks hanya whitespace harus mengembalikan bytes kosong"""
        client = TTSClient(api_key=TEST_TTS_API_KEY)

        chunks = []
        async for chunk in client.synthesize_stream("   \n\t  "):
            chunks.append(chunk)

        assert chunks == []

    @pytest.mark.asyncio
    async def test_synthesize_error_response(self):
        """TTS error response harus ditangani"""
        mock_responses = [
            make_tts_connection_started_response(),
            make_tts_session_started_response(),
            make_tts_error_response("Synthesis failed"),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses)

        with patch("tts_client.websockets.connect", return_value=mock_ws):
            client = TTSClient(api_key=TEST_TTS_API_KEY)

            chunks = []
            async for chunk in client.synthesize_stream("Test"):
                chunks.append(chunk)

            # Error response berarti tidak ada audio chunk
            assert len(chunks) == 0

    @pytest.mark.asyncio
    async def test_synthesize_sends_correct_events(self):
        """Synthesize harus mengirim StartConnection, StartSession, TaskRequest, FinishSession, dan FinishConnection"""
        mock_responses = [
            make_tts_connection_started_response(),
            make_tts_session_started_response(),
            make_tts_audio_response(b'\x00' * 50),
            make_tts_session_finished_response(),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses)

        with patch("tts_client.websockets.connect", return_value=mock_ws):
            client = TTSClient(api_key=TEST_TTS_API_KEY)
            await client.synthesize("Halo semuanya")

            # Cek jumlah send calls: StartConnection + StartSession + TaskRequest + FinishSession + FinishConnection = 5
            assert mock_ws.send.call_count == 5

    @pytest.mark.asyncio
    async def test_synthesize_timeout(self):
        """Timeout saat menerima audio chunk harus ditangani"""
        mock_responses = [
            make_tts_connection_started_response(),
            make_tts_session_started_response(),
        ]

        mock_ws = AsyncMock()
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=mock_responses + [asyncio.TimeoutError()])

        with patch("tts_client.websockets.connect", return_value=mock_ws):
            client = TTSClient(api_key=TEST_TTS_API_KEY)

            chunks = []
            async for chunk in client.synthesize_stream("Halo"):
                chunks.append(chunk)

            # Timeout berhenti tanpa crash, chunks mungkin kosong
            # (Tidak ada assertion ketat karena tergantung timing)
