"""
Binary Protocol Helper untuk BytePlus Voice API (STT & TTS)

Implementasi protokol biner WebSocket untuk komunikasi dengan:
- Speech-to-Text (ASR/STT) 2.0
- Text-to-Speech (TTS) 2.0

STT Format pesan:
  [Header: 4 byte] [Optional Event: 4 byte] [Payload Size: 4 byte] [Payload]

TTS 2.0 Format pesan (bidirectional WebSocket):
  Connect event: [Header 4B (flags=0x04)] [Event 4B] [Payload Size 4B] [Payload]
  Session event: [Header 4B (flags=0x04)] [Event 4B] [SessionID Size 4B] [SessionID] [Payload Size 4B] [Payload]
  Server response: [Header 4B (flags=0x04)] [Event 4B] [Optional EventID Size 4B + EventID] [Payload Size 4B] [Payload]
  Audio response: [Header 4B (flags=0x04)] [Event 4B] [Optional EventID Size 4B + EventID] [Audio data]
  Error response: [Header 4B (flags=0x00)] [Error Code 4B] [Payload Size 4B] [Payload]

Header (4 byte):
  Byte 0: (protocol_version << 4) | header_size
  Byte 1: (message_type << 4) | message_type_specific_flags
  Byte 2: (serialization << 4) | compression
  Byte 3: reserved (0x00)

STT Message type specific flags:
  bit0: menunjukkan apakah ada sequence/event value (4 byte) setelah header
  bit1: menunjukkan apakah ini packet terakhir

TTS Message type specific flags:
  bit0 (0x01): positive sequence
  bit1 (0x02): negative sequence
  bit2 (0x04): with event (event field present in binary frame)
"""

import struct
import json
import gzip
import logging

logger = logging.getLogger(__name__)


def debug_hex(data: bytes, max_bytes: int = 80) -> str:
    """Format bytes sebagai hex string untuk debugging"""
    if not isinstance(data, (bytes, bytearray)):
        return f"(not bytes: {type(data)})"
    hex_str = data[:max_bytes].hex()
    return " ".join(hex_str[i:i+2] for i in range(0, len(hex_str), 2))


def debug_frame(data: bytes) -> str:
    """Debug info untuk binary frame WebSocket"""
    if not isinstance(data, (bytes, bytearray)):
        return f"type={type(data)}"

    if len(data) < 4:
        return f"too short ({len(data)} bytes): {debug_hex(data)}"

    header = data[:4]
    protocol_ver = (header[0] >> 4) & 0x0F
    header_size_val = (header[0] & 0x0F)
    msg_type = (header[1] >> 4) & 0x0F
    msg_flags = header[1] & 0x0F
    serialization = (header[2] >> 4) & 0x0F
    compression = header[2] & 0x0F

    actual_header_size = header_size_val * 4

    # STT uses bit0 for sequence/event, TTS uses bit2 for event
    has_stt_event = bool(msg_flags & 0b0001)
    has_tts_event = bool(msg_flags & 0b0100)

    msg_type_names = {1: "FULL_CLIENT_REQ", 2: "AUDIO_ONLY_REQ", 9: "FULL_SERVER_RESP", 11: "AUDIO_ONLY_RESP", 15: "ERROR"}
    ser_names = {0: "RAW", 1: "JSON"}
    comp_names = {0: "NONE", 1: "GZIP"}

    info = (
        f"len={len(data)} "
        f"proto_ver={protocol_ver} "
        f"header_size={header_size_val}({actual_header_size}B) "
        f"msg_type={msg_type}({msg_type_names.get(msg_type, '?')}) "
        f"flags={msg_flags:04b}(stt_evt={has_stt_event},tts_evt={has_tts_event}) "
        f"ser={serialization}({ser_names.get(serialization, '?')}) "
        f"comp={compression}({comp_names.get(compression, '?')})"
    )

    offset = actual_header_size

    # STT: bit0 = sequence/event field
    if has_stt_event and len(data) >= offset + 4:
        event = struct.unpack(">I", data[offset:offset + 4])[0]
        info += f" stt_event={event}"
        offset += 4

    # TTS: bit2 = event field
    if has_tts_event and len(data) >= offset + 4:
        event = struct.unpack(">I", data[offset:offset + 4])[0]
        info += f" tts_event={event}"
        offset += 4

        # Check for event_id (connect_id or session_id) - size-prefixed string
        if len(data) >= offset + 4:
            event_id_size = struct.unpack(">I", data[offset:offset + 4])[0]
            if event_id_size > 0 and event_id_size < 200 and len(data) >= offset + 4 + event_id_size:
                event_id = data[offset + 4:offset + 4 + event_id_size].decode("utf-8", errors="replace")
                info += f" event_id={event_id}"
                offset += 4 + event_id_size

    # Payload size
    if len(data) >= offset + 4:
        payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
        info += f" payload_size={payload_size}"
        offset += 4
        payload_preview = data[offset:offset + min(80, payload_size)]
        if serialization == 1:  # JSON
            try:
                preview = json.loads(payload_preview.decode("utf-8"))
                info += f" payload={str(preview)[:120]}"
            except Exception:
                info += f" payload_hex={debug_hex(payload_preview, 40)}"
        else:
            info += f" payload_hex={debug_hex(payload_preview, 40)}"
    else:
        info += f" raw_hex={debug_hex(data, 40)}"

    return info


# Protocol constants
PROTOCOL_VERSION = 0b0001
HEADER_SIZE_DEFAULT = 0b0001  # 1 * 4 = 4 bytes
HEADER_SIZE_WITH_EVENT = 0b0010  # 2 * 4 = 8 bytes

# Message types
MSG_FULL_CLIENT_REQUEST = 0b0001
MSG_AUDIO_ONLY_REQUEST = 0b0010
MSG_FULL_SERVER_RESPONSE = 0b1001
MSG_AUDIO_ONLY_RESPONSE = 0b1011
MSG_ERROR = 0b1111

# Message type specific flags (for STT)
FLAG_NOT_LAST = 0b0000
FLAG_LAST_AUDIO = 0b0010  # last audio packet from client
FLAG_NON_LAST_RESPONSE = 0b0001
FLAG_LAST_RESPONSE = 0b0011

# TTS 2.0 flags
TTS_FLAG_NO_SEQUENCE = 0x00
TTS_FLAG_POSITIVE_SEQ = 0x01
TTS_FLAG_NEGATIVE_SEQ = 0x02
TTS_FLAG_NEGATIVE_WITH_SEQ = 0x03
TTS_FLAG_WITH_EVENT = 0x04  # bit2: event field present in binary frame

# Serialization methods
SER_RAW = 0b0000
SER_JSON = 0b0001

# Compression methods
COMP_NONE = 0b0000
COMP_GZIP = 0b0001

# ==================== TTS 2.0 Event Numbers ====================

# Client events
TTS_EVENT_START_CONNECTION = 1
TTS_EVENT_FINISH_CONNECTION = 2
TTS_EVENT_START_SESSION = 100
TTS_EVENT_SESSION_CANCEL = 101
TTS_EVENT_SESSION_FINISH = 102
TTS_EVENT_TASK_REQUEST = 200

# Server events
TTS_EVENT_CONNECTION_STARTED = 50
TTS_EVENT_CONNECTION_FAILED = 51
TTS_EVENT_CONNECTION_FINISHED = 52
TTS_EVENT_SESSION_STARTED = 150
TTS_EVENT_SESSION_CANCELED = 151
TTS_EVENT_SESSION_FINISHED = 152
TTS_EVENT_SESSION_FAILED = 153
TTS_EVENT_SENTENCE_START = 350
TTS_EVENT_SENTENCE_END = 351
TTS_EVENT_RESPONSE = 352

# Legacy aliases (for backward compat with tests)
TTS_EVENT_AUDIO_RESPONSE = TTS_EVENT_RESPONSE
TTS_EVENT_SUBTITLE = 6
TTS_EVENT_ERROR = 7


# ==================== STT Functions ====================

def build_stt_full_request(payload: dict, use_gzip: bool = False) -> bytes:
    """
    Membangun pesan Full Client Request untuk STT.
    Format: [Header 4B] [Payload Size 4B] [Payload]
    """
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    compression = COMP_GZIP if use_gzip else COMP_NONE
    if use_gzip:
        payload_bytes = gzip.compress(payload_bytes)

    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_FULL_CLIENT_REQUEST << 4) | FLAG_NOT_LAST,
        (SER_JSON << 4) | compression,
        0x00,
    ])

    payload_size = struct.pack(">I", len(payload_bytes))
    return header + payload_size + payload_bytes


def build_stt_audio_request(audio_data: bytes, is_last: bool = False) -> bytes:
    """
    Membangun pesan Audio Only Request untuk STT.
    Format: [Header 4B] [Payload Size 4B] [Payload (raw audio)]
    """
    flag = FLAG_LAST_AUDIO if is_last else FLAG_NOT_LAST
    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_AUDIO_ONLY_REQUEST << 4) | flag,
        (SER_RAW << 4) | COMP_NONE,
        0x00,
    ])

    payload_size = struct.pack(">I", len(audio_data))
    return header + payload_size + audio_data


def parse_stt_response(data: bytes) -> dict:
    """
    Parse pesan response dari STT server.

    Format response:
    [Header 4B] [Optional Event 4B] [Payload Size 4B] [Payload (JSON)]

    Event field ada jika bit0 dari msg_flags diset (has_sequence).
    """
    if len(data) < 8:
        raise ValueError(f"Response terlalu pendek: {len(data)} bytes")

    header = data[:4]
    msg_type = (header[1] >> 4) & 0x0F
    msg_flags = header[1] & 0x0F
    serialization = (header[2] >> 4) & 0x0F
    compression = header[2] & 0x0F

    # Header size dari byte 0
    header_size = (header[0] & 0x0F) * 4
    offset = header_size

    # bit0 dari msg_flags menunjukkan ada sequence/event value (4 byte)
    has_sequence = bool(msg_flags & 0b0001)
    if has_sequence and len(data) >= offset + 4:
        # Skip event/sequence field (4 bytes)
        offset += 4

    if msg_type == MSG_ERROR:
        # Error message
        if len(data) < offset + 4:
            return {"error": "Unknown error (no payload)"}
        payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
        payload = data[offset:offset + payload_size]
        try:
            return {"error": json.loads(payload.decode("utf-8"))}
        except Exception:
            return {"error": payload.decode("utf-8", errors="replace")}

    # Read payload size
    if len(data) < offset + 4:
        return {"raw": data[offset:]}

    payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4
    payload = data[offset:offset + payload_size]

    # Decompress if needed
    if compression == COMP_GZIP:
        try:
            payload = gzip.decompress(payload)
        except Exception as e:
            logger.error("STT decompress error: %s", e)

    # Deserialize
    if serialization == SER_JSON:
        try:
            result = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error("STT JSON decode error: %s, payload_hex: %s", e, debug_hex(payload, 40))
            raise
    else:
        result = {"raw": payload}

    result["_msg_type"] = msg_type
    result["_msg_flags"] = msg_flags
    result["_is_last"] = bool(msg_flags & 0b0010)
    return result


# ==================== TTS 2.0 Functions ====================

def build_tts_connect_request(event: int, payload: dict, use_gzip: bool = False) -> bytes:
    """
    Membangun pesan Connect Event untuk TTS 2.0 (StartConnection, FinishConnection).

    Format: [Header 4B (flags=0x04)] [Event 4B] [Payload Size 4B] [Payload]

    Connect events tidak menyertakan session_id di binary frame
    (connect_id sudah ada di HTTP header X-Api-Connect-Id).
    """
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    compression = COMP_GZIP if use_gzip else COMP_NONE
    if use_gzip:
        payload_bytes = gzip.compress(payload_bytes)

    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_FULL_CLIENT_REQUEST << 4) | TTS_FLAG_WITH_EVENT,  # flags=0x04 (WithEvent)
        (SER_JSON << 4) | compression,
        0x00,
    ])

    event_bytes = struct.pack(">I", event)
    payload_size = struct.pack(">I", len(payload_bytes))

    return header + event_bytes + payload_size + payload_bytes


def build_tts_session_request(session_id: str, event: int, payload: dict, use_gzip: bool = False) -> bytes:
    """
    Membangun pesan Session Event untuk TTS 2.0 (StartSession, TaskRequest, FinishSession).

    Format: [Header 4B (flags=0x04)] [Event 4B] [SessionID Size 4B] [SessionID] [Payload Size 4B] [Payload]

    Session events menyertakan session_id di binary frame untuk
    mengidentifikasi session yang aktif.
    """
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    session_id_bytes = session_id.encode("utf-8")

    compression = COMP_GZIP if use_gzip else COMP_NONE
    if use_gzip:
        payload_bytes = gzip.compress(payload_bytes)

    header = bytes([
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_DEFAULT,
        (MSG_FULL_CLIENT_REQUEST << 4) | TTS_FLAG_WITH_EVENT,  # flags=0x04 (WithEvent)
        (SER_JSON << 4) | compression,
        0x00,
    ])

    event_bytes = struct.pack(">I", event)
    session_id_size = struct.pack(">I", len(session_id_bytes))
    payload_size = struct.pack(">I", len(payload_bytes))

    return header + event_bytes + session_id_size + session_id_bytes + payload_size + payload_bytes


def parse_tts_response(data: bytes) -> dict:
    """
    Parse pesan response dari TTS 2.0 server.

    Format response:
    [Header 4B] [Optional Event 4B] [Optional EventID Size 4B + EventID] [Payload Size 4B] [Payload]

    - bit2 (0x04) pada flags = event field present
    - Setelah event, ada optional event_id (connect_id atau session_id) sebagai size-prefixed string
    - Untuk error frames, ada error code (4B) setelah header
    - Untuk audio-only responses, payload adalah raw audio bytes
    """
    if len(data) < 4:
        raise ValueError(f"Response terlalu pendek: {len(data)} bytes")

    header = data[:4]
    msg_type = (header[1] >> 4) & 0x0F
    msg_flags = header[1] & 0x0F
    serialization = (header[2] >> 4) & 0x0F
    compression = header[2] & 0x0F

    header_size = (header[0] & 0x0F) * 4
    offset = header_size

    # Check for sequence field (bit0/bit1)
    has_sequence = bool(msg_flags & 0b0011)
    if has_sequence and len(data) >= offset + 4:
        offset += 4  # Skip sequence field

    # Check for event field (bit2)
    event = None
    event_id = None
    has_event = bool(msg_flags & TTS_FLAG_WITH_EVENT)

    if has_event:
        if len(data) >= offset + 4:
            event = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4

        # Check for event_id (size-prefixed string)
        # Server responses include connect_id or session_id after the event number
        if len(data) >= offset + 4:
            event_id_size = struct.unpack(">I", data[offset:offset + 4])[0]
            # Sanity check: event_id_size should be reasonable (< 256 bytes)
            if 0 < event_id_size < 256 and len(data) >= offset + 4 + event_id_size:
                event_id = data[offset + 4:offset + 4 + event_id_size].decode("utf-8", errors="replace")
                offset += 4 + event_id_size
            elif event_id_size == 0:
                # Empty event_id, skip the size field
                offset += 4

    if msg_type == MSG_ERROR:
        # Error frame: [Header] [Optional Event] [Error Code 4B] [Payload Size 4B] [Payload]
        # Or: [Header] [Error Code 4B] [Payload Size 4B] [Payload]
        if len(data) < offset + 4:
            return {"event": event, "is_error": True, "error": "Unknown error"}
        error_code = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4

        if len(data) < offset + 4:
            return {"event": event, "is_error": True, "error": f"Error code: {error_code}"}
        payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
        payload = data[offset:offset + payload_size]

        if compression == COMP_GZIP:
            try:
                payload = gzip.decompress(payload)
            except Exception:
                pass

        try:
            error_info = json.loads(payload.decode("utf-8"))
        except Exception:
            error_info = payload.decode("utf-8", errors="replace")

        return {
            "event": event,
            "event_id": event_id,
            "msg_type": msg_type,
            "is_error": True,
            "error_code": error_code,
            "error": error_info,
        }

    # Read payload size
    if len(data) < offset + 4:
        # No payload size field - might be audio-only with raw data
        if msg_type == MSG_AUDIO_ONLY_RESPONSE:
            audio_data = data[offset:]
            return {
                "event": event,
                "event_id": event_id,
                "msg_type": msg_type,
                "is_audio": True,
                "audio": audio_data,
            }
        return {"event": event, "event_id": event_id, "msg_type": msg_type, "is_error": False, "raw": data[offset:]}

    payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4
    payload = data[offset:offset + payload_size]

    # Decompress if needed
    if compression == COMP_GZIP:
        try:
            payload = gzip.decompress(payload)
        except Exception as e:
            logger.error("TTS decompress error: %s", e)

    # Untuk audio-only response, payload adalah raw audio bytes
    if msg_type == MSG_AUDIO_ONLY_RESPONSE:
        return {
            "event": event,
            "event_id": event_id,
            "msg_type": msg_type,
            "is_audio": True,
            "audio": payload,
        }

    # Untuk full server response, parse JSON
    if serialization == SER_JSON:
        try:
            result = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as e:
            logger.error("TTS JSON decode error: %s, payload_hex: %s", e, debug_hex(payload, 40))
            result = {"raw": payload.decode("utf-8", errors="replace")}
    else:
        # Raw serialization - could be audio data
        result = {"raw": payload}
        # If msg_type is audio-only response, mark as audio
        if msg_type == MSG_AUDIO_ONLY_RESPONSE:
            result = {"audio": payload}

    result["event"] = event
    result["event_id"] = event_id
    result["msg_type"] = msg_type
    result["is_error"] = False
    return result


# ==================== Legacy TTS Functions (backward compat) ====================

def build_tts_request(payload: dict, event: int, use_gzip: bool = False) -> bytes:
    """
    Legacy function untuk backward compatibility.
    Sekarang menggunakan build_tts_connect_request (tanpa session_id).
    Hanya untuk connect-level events.
    """
    return build_tts_connect_request(event, payload, use_gzip)
