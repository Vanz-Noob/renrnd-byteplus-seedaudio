"""
Test configuration dan shared fixtures untuk BytePlus Voice Chat

Menyediakan:
- Mock API keys untuk testing
- Mock WebSocket server untuk STT/TTS
- Mock HTTP server untuk ModelArk AI
- Temporary audio data (PCM 16kHz)
"""

import asyncio
import json
import struct
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Import protocol constants untuk membuat mock responses
import sys
sys.path.insert(0, ".")  # Pastikan modul proyek bisa di-import

from binary_protocol import (
    PROTOCOL_VERSION,
    HEADER_SIZE_DEFAULT,
    HEADER_SIZE_WITH_EVENT,
    MSG_FULL_CLIENT_REQUEST,
    MSG_AUDIO_ONLY_REQUEST,
    MSG_FULL_SERVER_RESPONSE,
    MSG_AUDIO_ONLY_RESPONSE,
    MSG_ERROR,
    SER_JSON,
    SER_RAW,
    COMP_NONE,
    COMP_GZIP,
    FLAG_NOT_LAST,
    FLAG_LAST_AUDIO,
    FLAG_NON_LAST_RESPONSE,
    FLAG_LAST_RESPONSE,
    TTS_FLAG_WITH_EVENT,
    # TTS 2.0 event numbers
    TTS_EVENT_START_CONNECTION,
    TTS_EVENT_FINISH_CONNECTION,
    TTS_EVENT_START_SESSION,
    TTS_EVENT_SESSION_CANCEL,
    TTS_EVENT_SESSION_FINISH,
    TTS_EVENT_TASK_REQUEST,
    TTS_EVENT_CONNECTION_STARTED,
    TTS_EVENT_CONNECTION_FAILED,
    TTS_EVENT_CONNECTION_FINISHED,
    TTS_EVENT_SESSION_STARTED,
    TTS_EVENT_SESSION_CANCELED,
    TTS_EVENT_SESSION_FINISHED,
    TTS_EVENT_SESSION_FAILED,
    TTS_EVENT_SENTENCE_START,
    TTS_EVENT_SENTENCE_END,
    TTS_EVENT_RESPONSE,
    # Legacy aliases
    TTS_EVENT_AUDIO_RESPONSE,
    TTS_EVENT_ERROR,
    build_stt_full_request,
    build_stt_audio_request,
    parse_stt_response,
    build_tts_request,
    build_tts_connect_request,
    build_tts_session_request,
    parse_tts_response,
)


# ============================================
# Test API Keys (dummy, bukan key asli)
# ============================================
TEST_STT_API_KEY = "test-stt-key-12345"
TEST_TTS_API_KEY = "test-tts-key-12345"
TEST_ARK_API_KEY = "ark-test-key-12345"


# ============================================
# Fixtures: Dummy Audio Data
# ============================================

@pytest.fixture
def sample_pcm_audio():
    """Generate dummy PCM audio data (16kHz, 16-bit, mono, 1 detik)"""
    # 16000 samples * 2 bytes per sample = 32000 bytes = 1 detik audio
    return b'\x00\x01' * 16000


@pytest.fixture
def sample_pcm_short():
    """Generate dummy PCM audio pendek (100ms)"""
    # 1600 samples * 2 bytes = 3200 bytes = 100ms
    return b'\x00\x01' * 1600


@pytest.fixture
def sample_mp3_audio():
    """Generate dummy MP3 audio bytes"""
    # Header MP3 + dummy frames
    return b'\xff\xfb\x90\x00' * 100


# ============================================
# Fixtures: Mock STT WebSocket Responses
# ============================================

def make_stt_ack_response():
    """Buat mock STT acknowledgment response"""
    payload = json.dumps({"result": {"text": ""}}).encode("utf-8")
    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_FULL_SERVER_RESPONSE << 4) | FLAG_NON_LAST_RESPONSE,
        (SER_JSON << 4) | COMP_NONE,
        0x00,
    ])
    sequence = struct.pack(">I", 0)
    payload_size = struct.pack(">I", len(payload))
    return header + sequence + payload_size + payload


def make_stt_partial_response(text: str):
    """Buat mock STT partial response (streaming, belum definitive)"""
    payload = json.dumps({
        "result": {"text": text, "definite": False}
    }).encode("utf-8")
    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_FULL_SERVER_RESPONSE << 4) | FLAG_NON_LAST_RESPONSE,
        (SER_JSON << 4) | COMP_NONE,
        0x00,
    ])
    sequence = struct.pack(">I", 0)
    payload_size = struct.pack(">I", len(payload))
    return header + sequence + payload_size + payload


def make_stt_final_response(text: str):
    """Buat mock STT final response (definitive, is_last)"""
    payload = json.dumps({
        "result": {"text": text, "definite": True}
    }).encode("utf-8")
    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_FULL_SERVER_RESPONSE << 4) | FLAG_LAST_RESPONSE,
        (SER_JSON << 4) | COMP_NONE,
        0x00,
    ])
    sequence = struct.pack(">I", 0)
    payload_size = struct.pack(">I", len(payload))
    return header + sequence + payload_size + payload


def make_stt_error_response(error_msg: str = "Test error"):
    """Buat mock STT error response"""
    payload = json.dumps({"error": {"message": error_msg}}).encode("utf-8")
    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_ERROR << 4) | 0,
        (SER_JSON << 4) | COMP_NONE,
        0x00,
    ])
    payload_size = struct.pack(">I", len(payload))
    return header + payload_size + payload


# ============================================
# Fixtures: Mock TTS 2.0 WebSocket Responses
# ============================================

def _make_tts_server_response(event: int, payload: bytes, msg_type=MSG_FULL_SERVER_RESPONSE,
                               serialization=SER_JSON, event_id: str = None):
    """
    Build a TTS 2.0 server response frame.
    Format: [Header 4B (flags=0x04)] [Event 4B] [Optional EventID Size 4B + EventID] [Payload Size 4B] [Payload]
    """
    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (msg_type << 4) | TTS_FLAG_WITH_EVENT,  # flags=0x04 (WithEvent)
        (serialization << 4) | COMP_NONE,
        0x00,
    ])
    event_bytes = struct.pack(">I", event)

    frame = header + event_bytes

    if event_id:
        event_id_bytes = event_id.encode("utf-8")
        event_id_size = struct.pack(">I", len(event_id_bytes))
        frame += event_id_size + event_id_bytes

    payload_size = struct.pack(">I", len(payload))
    frame += payload_size + payload
    return frame


def make_tts_connection_started_response(connect_id: str = "test-connect-id"):
    """Buat mock TTS ConnectionStarted response"""
    payload = json.dumps({"event": TTS_EVENT_CONNECTION_STARTED}).encode("utf-8")
    return _make_tts_server_response(TTS_EVENT_CONNECTION_STARTED, payload, event_id=connect_id)


def make_tts_session_started_response(session_id: str = "test-session-id"):
    """Buat mock TTS SessionStarted response"""
    payload = json.dumps({"event": TTS_EVENT_SESSION_STARTED}).encode("utf-8")
    return _make_tts_server_response(TTS_EVENT_SESSION_STARTED, payload, event_id=session_id)


def make_tts_audio_response(audio_data: bytes, session_id: str = "test-session-id"):
    """Buat mock TTS audio chunk response (AudioOnlyServer)"""
    return _make_tts_server_response(
        TTS_EVENT_RESPONSE, audio_data,
        msg_type=MSG_AUDIO_ONLY_RESPONSE,
        serialization=SER_RAW,
        event_id=session_id,
    )


def make_tts_session_finished_response(session_id: str = "test-session-id"):
    """Buat mock TTS SessionFinished response"""
    payload = json.dumps({"event": TTS_EVENT_SESSION_FINISHED}).encode("utf-8")
    return _make_tts_server_response(TTS_EVENT_SESSION_FINISHED, payload, event_id=session_id)


def make_tts_error_response(error_msg: str = "TTS test error"):
    """Buat mock TTS error response"""
    payload = json.dumps({"error": {"message": error_msg}}).encode("utf-8")
    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_ERROR << 4) | 0,
        (SER_JSON << 4) | COMP_NONE,
        0x00,
    ])
    error_code = struct.pack(">I", 0)
    payload_size = struct.pack(">I", len(payload))
    return header + error_code + payload_size + payload


# ============================================
# Fixtures: Mock ModelArk SSE Response
# ============================================

def make_sse_chunks(text: str, chunk_size: int = 5) -> list[str]:
    """
    Pecah teks menjadi SSE chunks (simulasi streaming dari ModelArk).
    Format: data: {"choices":[{"delta":{"content":"..."}}]}
    """
    chunks = []
    for i in range(0, len(text), chunk_size):
        piece = text[i:i + chunk_size]
        chunk_data = {
            "choices": [{"delta": {"content": piece}}]
        }
        chunks.append(f"data: {json.dumps(chunk_data)}")
    chunks.append("data: [DONE]")
    return chunks


# ============================================
# Fixtures: Mock WebSocket
# ============================================

class MockWebSocket:
    """Mock WebSocket yang mensimulasikan koneksi WebSocket BytePlus"""

    def __init__(self, responses: list[bytes]):
        self.responses = list(responses)
        self.sent_messages = []
        self._closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self._closed = True

    async def send(self, data):
        self.sent_messages.append(data)

    async def recv(self):
        if not self.responses:
            await asyncio.sleep(0.01)
            raise asyncio.TimeoutError("No more mock responses")
        return self.responses.pop(0)

    async def close(self):
        self._closed = True


@pytest.fixture
def mock_stt_ws():
    """Mock WebSocket untuk STT dengan response sequence standar"""
    responses = [
        make_stt_ack_response(),
        make_stt_partial_response("Halo"),
        make_stt_partial_response("Halo apa"),
        make_stt_final_response("Halo apa kabar?"),
    ]
    return MockWebSocket(responses)


@pytest.fixture
def mock_tts_ws():
    """Mock WebSocket untuk TTS dengan response sequence standar (TTS 2.0)"""
    responses = [
        make_tts_connection_started_response(),
        make_tts_session_started_response(),
        make_tts_audio_response(b'\xff\xfb\x90\x00' * 50),
        make_tts_audio_response(b'\xff\xfb\x90\x00' * 50),
        make_tts_session_finished_response(),
    ]
    return MockWebSocket(responses)


# ============================================
# Fixtures: Event Loop
# ============================================

@pytest.fixture
def event_loop():
    """Event loop untuk async tests"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
