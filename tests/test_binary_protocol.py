"""
Unit test untuk binary_protocol.py

Menguji:
- Konstruksi pesan Full Client Request (STT)
- Konstruksi pesan Audio Only Request (STT)
- Konstruksi pesan TTS request (dengan event)
- Parse response STT (normal, partial, final, error)
- Parse response TTS (session started, audio, session finished, error)
- Round-trip encode -> decode
- Edge cases: empty payload, gzip compression
"""

import json
import struct
import pytest

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
    TTS_EVENT_START_SESSION,
    TTS_EVENT_TASK_REQUEST,
    TTS_EVENT_SESSION_FINISH,
    TTS_EVENT_SESSION_STARTED,
    TTS_EVENT_SESSION_FINISHED,
    TTS_EVENT_AUDIO_RESPONSE,
    TTS_EVENT_ERROR,
    build_stt_full_request,
    build_stt_audio_request,
    parse_stt_response,
    build_tts_request,
    parse_tts_response,
)

from tests.conftest import (
    make_stt_ack_response,
    make_stt_partial_response,
    make_stt_final_response,
    make_stt_error_response,
    make_tts_session_started_response,
    make_tts_audio_response,
    make_tts_session_finished_response,
    make_tts_error_response,
)


class TestSTTRequestBuilding:
    """Test konstruksi pesan request STT"""

    def test_build_stt_full_request_basic(self):
        """Full client request harus memiliki header 4 byte + payload size + payload"""
        payload = {"audio": {"format": "pcm"}, "request": {"model_name": "bigmodel"}}
        data = build_stt_full_request(payload)

        # Header: 4 bytes
        assert len(data) > 4
        header = data[:4]

        # Protocol version = 1, header size = 1 (4 bytes)
        assert (header[0] >> 4) == PROTOCOL_VERSION
        assert (header[0] & 0x0F) == HEADER_SIZE_DEFAULT

        # Message type = full client request
        assert (header[1] >> 4) == MSG_FULL_CLIENT_REQUEST

        # Serialization = JSON
        assert (header[2] >> 4) == SER_JSON

        # Compression = none
        assert (header[2] & 0x0F) == COMP_NONE

        # Payload size (bytes 4-7)
        payload_size = struct.unpack(">I", data[4:8])[0]
        assert payload_size > 0

        # Payload (bytes 8+)
        payload_bytes = data[8:8 + payload_size]
        decoded = json.loads(payload_bytes.decode("utf-8"))
        assert decoded["audio"]["format"] == "pcm"

    def test_build_stt_full_request_with_gzip(self):
        """Full client request dengan gzip compression"""
        payload = {"request": {"model_name": "bigmodel", "data": "x" * 1000}}
        data = build_stt_full_request(payload, use_gzip=True)

        header = data[:4]
        assert (header[2] & 0x0F) == COMP_GZIP

        # Payload harus bisa di-decode (parse_stt_response menangani decompress)
        payload_size = struct.unpack(">I", data[4:8])[0]
        assert payload_size > 0

    def test_build_stt_audio_request_basic(self):
        """Audio only request dengan data PCM"""
        audio = b'\x00\x01' * 100
        data = build_stt_audio_request(audio, is_last=False)

        header = data[:4]

        # Message type = audio only request
        assert (header[1] >> 4) == MSG_AUDIO_ONLY_REQUEST

        # Flag = not last
        assert (header[1] & 0x0F) == FLAG_NOT_LAST

        # Serialization = raw (bukan JSON)
        assert (header[2] >> 4) == SER_RAW

        # Payload = audio data
        payload_size = struct.unpack(">I", data[4:8])[0]
        assert payload_size == len(audio)
        assert data[8:8 + payload_size] == audio

    def test_build_stt_audio_request_last_packet(self):
        """Audio only request dengan flag is_last=True"""
        audio = b'\x00\x01' * 50
        data = build_stt_audio_request(audio, is_last=True)

        header = data[:4]
        assert (header[1] & 0x0F) == FLAG_LAST_AUDIO

    def test_build_stt_audio_request_empty(self):
        """Audio only request dengan data kosong (final packet)"""
        data = build_stt_audio_request(b"", is_last=True)

        header = data[:4]
        payload_size = struct.unpack(">I", data[4:8])[0]
        assert payload_size == 0
        assert (header[1] & 0x0F) == FLAG_LAST_AUDIO


class TestSTTResponseParsing:
    """Test parsing response dari STT server"""

    def test_parse_stt_ack(self):
        """Parse acknowledgment response"""
        raw = make_stt_ack_response()
        result = parse_stt_response(raw)

        assert "result" in result
        assert result["result"]["text"] == ""
        assert result["_msg_type"] == MSG_FULL_SERVER_RESPONSE

    def test_parse_stt_partial(self):
        """Parse partial transcription response"""
        raw = make_stt_partial_response("Halo semuanya")
        result = parse_stt_response(raw)

        assert result["result"]["text"] == "Halo semuanya"
        assert result["result"]["definite"] is False
        assert result["_is_last"] is False

    def test_parse_stt_final(self):
        """Parse final transcription response"""
        raw = make_stt_final_response("Halo apa kabar?")
        result = parse_stt_response(raw)

        assert result["result"]["text"] == "Halo apa kabar?"
        assert result["result"]["definite"] is True
        assert result["_is_last"] is True

    def test_parse_stt_error(self):
        """Parse error response"""
        raw = make_stt_error_response("Connection failed")
        result = parse_stt_response(raw)

        assert "error" in result
        assert "Connection failed" in str(result["error"])


class TestTTSRequestBuilding:
    """Test konstruksi pesan request TTS"""

    def test_build_tts_request_start_session(self):
        """TTS StartSession request dengan event number"""
        payload = {"event": TTS_EVENT_START_SESSION, "namespace": "BidirectionalTTS"}
        data = build_tts_request(payload, TTS_EVENT_START_SESSION)

        header = data[:4]

        # Header size = 1 (4 bytes, TTS 2.0 uses default header size)
        assert (header[0] & 0x0F) == HEADER_SIZE_DEFAULT

        # Message type = full client request
        assert (header[1] >> 4) == MSG_FULL_CLIENT_REQUEST

        # Flags = 0x04 (WithEvent, bit2 set)
        assert (header[1] & 0x0F) == TTS_FLAG_WITH_EVENT

        # Event number (bytes 4-7, in binary frame not in JSON)
        event = struct.unpack(">I", data[4:8])[0]
        assert event == TTS_EVENT_START_SESSION

        # Payload size (bytes 8-11)
        payload_size = struct.unpack(">I", data[8:12])[0]
        assert payload_size > 0

        # Payload (bytes 12+)
        payload_bytes = data[12:12 + payload_size]
        decoded = json.loads(payload_bytes.decode("utf-8"))
        assert decoded["namespace"] == "BidirectionalTTS"

    def test_build_tts_request_task_request(self):
        """TTS TaskRequest dengan text"""
        payload = {"event": TTS_EVENT_TASK_REQUEST, "req_params": {"text": "Halo"}}
        data = build_tts_request(payload, TTS_EVENT_TASK_REQUEST)

        header = data[:4]

        # Flags = 0x04 (WithEvent)
        assert (header[1] & 0x0F) == TTS_FLAG_WITH_EVENT

        # Event number (bytes 4-7)
        event = struct.unpack(">I", data[4:8])[0]
        assert event == TTS_EVENT_TASK_REQUEST

    def test_build_tts_request_finish_session(self):
        """TTS FinishSession request (TTS_EVENT_SESSION_FINISH)"""
        payload = {}
        data = build_tts_request(payload, TTS_EVENT_SESSION_FINISH)

        header = data[:4]

        # Flags = 0x04 (WithEvent)
        assert (header[1] & 0x0F) == TTS_FLAG_WITH_EVENT

        # Event number (bytes 4-7)
        event = struct.unpack(">I", data[4:8])[0]
        assert event == TTS_EVENT_SESSION_FINISH

    def test_build_tts_request_with_gzip(self):
        """TTS request dengan gzip compression"""
        payload = {"req_params": {"text": "Halo" * 1000}}
        data = build_tts_request(payload, TTS_EVENT_TASK_REQUEST, use_gzip=True)

        header = data[:4]
        assert (header[2] & 0x0F) == COMP_GZIP


class TestTTSResponseParsing:
    """Test parsing response dari TTS server"""

    def test_parse_tts_session_started(self):
        """Parse TTS SessionStarted response"""
        raw = make_tts_session_started_response()
        result = parse_tts_response(raw)

        assert result["event"] == TTS_EVENT_SESSION_STARTED
        assert result["is_error"] is False
        assert result["msg_type"] == MSG_FULL_SERVER_RESPONSE

    def test_parse_tts_audio_response(self):
        """Parse TTS audio chunk response"""
        audio_data = b'\xff\xfb\x90\x00' * 100
        raw = make_tts_audio_response(audio_data)
        result = parse_tts_response(raw)

        assert result["is_audio"] is True
        assert result["audio"] == audio_data
        assert result["event"] == TTS_EVENT_AUDIO_RESPONSE
        assert result["msg_type"] == MSG_AUDIO_ONLY_RESPONSE

    def test_parse_tts_session_finished(self):
        """Parse TTS SessionFinished response"""
        raw = make_tts_session_finished_response()
        result = parse_tts_response(raw)

        assert result["event"] == TTS_EVENT_SESSION_FINISHED
        assert result["is_error"] is False

    def test_parse_tts_error(self):
        """Parse TTS error response"""
        raw = make_tts_error_response("TTS synthesis failed")
        result = parse_tts_response(raw)

        assert result["is_error"] is True
        assert "TTS synthesis failed" in str(result["error"])


class TestRoundTrip:
    """Test round-trip encode -> decode untuk memastikan konsistensi"""

    def test_stt_round_trip(self):
        """Encode STT request lalu parse kembali seolah-olah response"""
        original_payload = {
            "user": {"uid": "test_user"},
            "audio": {"format": "pcm", "rate": 16000},
            "request": {"model_name": "bigmodel"},
        }

        # Build request
        data = build_stt_full_request(original_payload)

        # Extract payload dari request (skip header + size)
        payload_size = struct.unpack(">I", data[4:8])[0]
        payload_bytes = data[8:8 + payload_size]
        decoded = json.loads(payload_bytes.decode("utf-8"))

        assert decoded == original_payload

    def test_tts_round_trip(self):
        """Encode TTS request lalu extract payload"""
        original_payload = {
            "event": TTS_EVENT_START_SESSION,
            "namespace": "BidirectionalTTS",
            "req_params": {
                "speaker": "zh_female_vv_uranus_bigtts",
                "audio_params": {"format": "mp3", "sample_rate": 24000},
            },
        }

        data = build_tts_request(original_payload, TTS_EVENT_START_SESSION)

        # Skip header (4 bytes) + event (4 bytes) = 8 bytes
        payload_size = struct.unpack(">I", data[8:12])[0]
        payload_bytes = data[12:12 + payload_size]
        decoded = json.loads(payload_bytes.decode("utf-8"))

        assert decoded == original_payload


class TestEdgeCases:
    """Test edge cases dan error handling"""

    def test_parse_stt_response_too_short(self):
        """Response terlalu pendek harus raise ValueError"""
        with pytest.raises(ValueError, match="terlalu pendek"):
            parse_stt_response(b'\x00\x01')

    def test_parse_tts_response_too_short(self):
        """Response TTS terlalu pendek harus raise ValueError"""
        with pytest.raises(ValueError, match="terlalu pendek"):
            parse_tts_response(b'\x00\x01')

    def test_build_stt_full_request_empty_dict(self):
        """Build request dengan payload kosong"""
        data = build_stt_full_request({})
        payload_size = struct.unpack(">I", data[4:8])[0]
        assert payload_size == 2  # "{}"

    def test_build_stt_audio_request_large(self):
        """Build audio request dengan data besar"""
        audio = b'\x00' * 100000  # 100KB
        data = build_stt_audio_request(audio, is_last=False)
        payload_size = struct.unpack(">I", data[4:8])[0]
        assert payload_size == 100000
