"""
BytePlus Text-to-Speech (TTS) 2.0 WebSocket Client

Optimized: Satu WebSocket connection + satu session untuk seluruh AI response.
Mengikuti best practice dari dokumentasi: "推荐将流式输出的文本直接输入该接口，
而不要额外增加切句或者攒句的逻辑"

Protocol Flow (optimized):
  1. WebSocket connect
  2. StartConnection → ConnectionStarted
  3. StartSession → SessionStarted
  4. Multiple TaskRequest (streaming text dari AI) → audio chunks
  5. FinishSession → SessionFinished
  6. FinishConnection

Voice: zh_female_vv_uranus_bigtts (Vivi 2.0) - supports Indonesian
Endpoint: wss://voice.ap-southeast-1.bytepluses.com/api/v3/tts/bidirection
"""

import asyncio
import json
import uuid
import string
import random
import logging
from typing import AsyncGenerator, Optional

import websockets

from binary_protocol import (
    build_tts_connect_request,
    build_tts_session_request,
    parse_tts_response,
    debug_frame,
    debug_hex,
    TTS_EVENT_START_CONNECTION,
    TTS_EVENT_FINISH_CONNECTION,
    TTS_EVENT_START_SESSION,
    TTS_EVENT_SESSION_FINISH,
    TTS_EVENT_TASK_REQUEST,
    TTS_EVENT_CONNECTION_STARTED,
    TTS_EVENT_CONNECTION_FAILED,
    TTS_EVENT_SESSION_STARTED,
    TTS_EVENT_SESSION_CANCELED,
    TTS_EVENT_SESSION_FINISHED,
    TTS_EVENT_SESSION_FAILED,
    TTS_EVENT_SENTENCE_START,
    TTS_EVENT_SENTENCE_END,
    TTS_EVENT_RESPONSE,
)

logger = logging.getLogger(__name__)

TTS_WS_URL = "wss://voice.ap-southeast-1.bytepluses.com/api/v3/tts/bidirection"
TTS_RESOURCE_ID = "seed-tts-2.0"


def _generate_session_id(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


class TTSClient:
    """Client untuk BytePlus TTS 2.0 - optimized dengan session reuse"""

    def __init__(
        self,
        api_key: str,
        speaker: str = "zh_female_vv_uranus_bigtts",
        audio_format: str = "mp3",
        sample_rate: int = 24000,
        resource_id: str = TTS_RESOURCE_ID,
        explicit_language: str = "id",
    ):
        self.api_key = api_key
        self.speaker = speaker
        self.audio_format = audio_format
        self.sample_rate = sample_rate
        self.resource_id = resource_id
        self.explicit_language = explicit_language

    def _build_headers(self) -> dict:
        return {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

    def _build_start_session_payload(self) -> dict:
        payload = {
            "user": {"uid": ""},
            "event": TTS_EVENT_START_SESSION,
            "req_params": {
                "speaker": self.speaker,
                "audio_params": {
                    "format": self.audio_format,
                    "sample_rate": self.sample_rate,
                    "channel": 1,
                },
            },
        }
        if self.explicit_language:
            additions = {"explicit_language": self.explicit_language}
            payload["req_params"]["additions"] = json.dumps(additions, ensure_ascii=False)
        return payload

    def _build_task_request_payload(self, text: str) -> dict:
        return {
            "user": {"uid": ""},
            "event": TTS_EVENT_TASK_REQUEST,
            "req_params": {"text": text},
        }

    async def synthesize_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        """Synthesize satu teks (backward compat - membuka/tutup koneksi sendiri)."""
        async for chunk in self.synthesize_streaming([text]):
            yield chunk

    async def synthesize_streaming(
        self, text_chunks: AsyncGenerator[str, None] | list[str]
    ) -> AsyncGenerator[bytes, None]:
        """
        Synthesize multiple text chunks dalam SATU session TTS.

        Ini adalah method utama yang dioptimasi:
        - Satu WebSocket connection
        - Satu StartSession
        - Multiple TaskRequest (streaming text)
        - Audio chunks diyield secara real-time
        - Satu FinishSession di akhir

        TTS API akan otomatis memecah teks menjadi kalimat yang sesuai.
        """
        headers = self._build_headers()
        connect_id = headers["X-Api-Connect-Id"]
        session_id = _generate_session_id()

        logger.info("TTS: connecting (speaker: %s, session: %s)", self.speaker, session_id)

        try:
            async with websockets.connect(
                TTS_WS_URL,
                additional_headers=headers,
                max_size=10 * 1024 * 1024,
            ) as ws:
                # 1. StartConnection → ConnectionStarted
                conn_msg = build_tts_connect_request(
                    TTS_EVENT_START_CONNECTION, {"namespace": "BidirectionalTTS"}
                )
                await ws.send(conn_msg)

                resp = await asyncio.wait_for(ws.recv(), timeout=10.0)
                resp_data = parse_tts_response(resp)
                if resp_data.get("is_error") or resp_data.get("event") == TTS_EVENT_CONNECTION_FAILED:
                    raise RuntimeError(f"TTS ConnectionFailed: {resp_data.get('error')}")
                logger.info("TTS: ConnectionStarted (event=%s)", resp_data.get("event"))

                # 2. StartSession → SessionStarted
                sess_payload = self._build_start_session_payload()
                sess_msg = build_tts_session_request(session_id, TTS_EVENT_START_SESSION, sess_payload)
                await ws.send(sess_msg)

                resp = await asyncio.wait_for(ws.recv(), timeout=10.0)
                resp_data = parse_tts_response(resp)
                if resp_data.get("is_error") or resp_data.get("event") == TTS_EVENT_SESSION_FAILED:
                    raise RuntimeError(f"TTS SessionFailed: {resp_data.get('error')}")
                logger.info("TTS: SessionStarted (event=%s)", resp_data.get("event"))

                # 3. Streaming: kirim text chunks + terima audio secara paralel
                audio_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
                send_done = asyncio.Event()

                async def send_text():
                    """Kirim text chunks sebagai TaskRequest."""
                    try:
                        if hasattr(text_chunks, "__aiter__"):
                            # AsyncGenerator
                            async for chunk in text_chunks:
                                chunk = chunk.strip()
                                if chunk:
                                    task_payload = self._build_task_request_payload(chunk)
                                    task_msg = build_tts_session_request(
                                        session_id, TTS_EVENT_TASK_REQUEST, task_payload
                                    )
                                    await ws.send(task_msg)
                                    logger.info("TTS: TaskRequest sent (%d chars)", len(chunk))
                        else:
                            # List of strings
                            for chunk in text_chunks:
                                chunk = chunk.strip()
                                if chunk:
                                    task_payload = self._build_task_request_payload(chunk)
                                    task_msg = build_tts_session_request(
                                        session_id, TTS_EVENT_TASK_REQUEST, task_payload
                                    )
                                    await ws.send(task_msg)
                                    logger.info("TTS: TaskRequest sent (%d chars)", len(chunk))
                    except Exception as e:
                        logger.error("TTS send error: %s", e)
                    finally:
                        # Kirim FinishSession
                        try:
                            finish_msg = build_tts_session_request(
                                session_id, TTS_EVENT_SESSION_FINISH, {}
                            )
                            await ws.send(finish_msg)
                            logger.info("TTS: FinishSession sent")
                        except Exception:
                            pass
                        send_done.set()

                async def recv_audio():
                    """Terima audio chunks dari server."""
                    total = 0
                    try:
                        while True:
                            try:
                                resp = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            except asyncio.TimeoutError:
                                if total > 0:
                                    logger.info("TTS: recv done (%d bytes, timeout)", total)
                                break

                            try:
                                resp_data = parse_tts_response(resp)
                            except Exception as e:
                                logger.warning("TTS parse error: %s", e)
                                continue

                            if resp_data.get("is_error"):
                                logger.error("TTS error: %s", resp_data.get("error"))
                                break

                            event = resp_data.get("event")

                            if resp_data.get("is_audio"):
                                audio = resp_data.get("audio", b"")
                                if audio:
                                    total += len(audio)
                                    await audio_queue.put(audio)

                            elif event == TTS_EVENT_SESSION_FINISHED:
                                logger.info("TTS: SessionFinished (%d bytes)", total)
                                break
                            elif event in (TTS_EVENT_SESSION_CANCELED, TTS_EVENT_SESSION_FAILED):
                                logger.info("TTS: session end event=%s", event)
                                break

                    except websockets.exceptions.ConnectionClosed:
                        pass
                    finally:
                        await audio_queue.put(None)  # Signal selesai

                # Jalankan send dan recv secara paralel
                send_task = asyncio.create_task(send_text())
                recv_task = asyncio.create_task(recv_audio())

                # Yield audio chunks saat diterima
                while True:
                    chunk = await audio_queue.get()
                    if chunk is None:
                        break
                    yield chunk

                # Tunggu task selesai
                await asyncio.gather(send_task, recv_task, return_exceptions=True)

                # 4. FinishConnection
                try:
                    finish_conn = build_tts_connect_request(
                        TTS_EVENT_FINISH_CONNECTION, {}
                    )
                    await ws.send(finish_conn)
                except Exception:
                    pass

                logger.info("TTS: stream complete")

        except websockets.exceptions.ConnectionClosed as e:
            logger.error("TTS WebSocket closed: %s", e)
            raise
        except Exception as e:
            logger.error("TTS stream error: %s", e, exc_info=True)
            raise

    async def synthesize(self, text: str) -> bytes:
        """Synthesize teks menjadi audio (non-streaming)."""
        chunks = []
        async for chunk in self.synthesize_stream(text):
            chunks.append(chunk)
        return b"".join(chunks)
