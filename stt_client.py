"""
BytePlus Speech-to-Text (STT/ASR) 2.0 WebSocket Client

Menggunakan mode streaming input (bigmodel_nostream) untuk akurasi tinggi.
Mode ini mengirim audio dan menunggu hasil setelah final packet dikirim.

Endpoint: wss://voice.ap-southeast-1.bytepluses.com/api/v3/sauc/bigmodel_nostream

Protocol: WebSocket Binary Protocol (lihat binary_protocol.py)
"""

import asyncio
import json
import uuid
import struct
import logging
from typing import Optional, AsyncGenerator, Callable, Awaitable

import websockets

from binary_protocol import (
    build_stt_full_request,
    build_stt_audio_request,
    parse_stt_response,
    debug_frame,
)

logger = logging.getLogger(__name__)

# STT WebSocket endpoint - mode streaming input (akurasi tinggi)
STT_WS_URL = "wss://voice.ap-southeast-1.bytepluses.com/api/v3/sauc/bigmodel_nostream"

# Resource ID untuk ASR 2.0
STT_RESOURCE_ID = "volc.seedasr.sauc.duration"


class STTClient:
    """Client untuk BytePlus Speech-to-Text 2.0"""

    def __init__(
        self,
        api_key: str,
        language: str = "id-ID",
        resource_id: str = STT_RESOURCE_ID,
    ):
        self.api_key = api_key
        self.language = language
        self.resource_id = resource_id

    def _build_headers(self) -> dict:
        """Build WebSocket connection headers"""
        return {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": self.resource_id,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

    def _build_full_request(self) -> dict:
        """Build full client request payload"""
        return {
            "user": {
                "uid": "byteaudio_user",
            },
            "audio": {
                "format": "pcm",
                "codec": "raw",
                "rate": 16000,
                "bits": 16,
                "channel": 1,
                "language": self.language,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": False,
            },
        }

    async def transcribe(
        self,
        audio_chunks: AsyncGenerator[bytes, None],
        chunk_size: int = 3200,
        on_partial: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """
        Transcribe audio stream ke teks.

        Args:
            audio_chunks: Async generator yang menghasilkan PCM audio bytes
            chunk_size: Ukuran chunk audio (3200 bytes = 100ms @ 16kHz 16-bit)
            on_partial: Callback untuk partial transcription (tidak digunakan di mode nostream)

        Returns:
            Teks hasil transkripsi
        """
        headers = self._build_headers()
        full_request = self._build_full_request()

        logger.info("Menghubungkan ke STT WebSocket: %s", STT_WS_URL)

        try:
            async with websockets.connect(
                STT_WS_URL,
                additional_headers=headers,
                max_size=10 * 1024 * 1024,
            ) as ws:
                logger.info("STT WebSocket terhubung, mengirim full client request")

                # Kirim full client request
                request_data = build_stt_full_request(full_request)
                await ws.send(request_data)

                # Tunggu acknowledgment dari server
                ack = await ws.recv()
                logger.info("STT ack frame: %s", debug_frame(ack) if isinstance(ack, bytes) else type(ack))

                try:
                    ack_data = parse_stt_response(ack)
                except Exception as e:
                    logger.warning("STT ack parse error (non-fatal): %s", e)
                    ack_data = {}

                if "error" in ack_data:
                    raise RuntimeError(f"STT error pada acknowledgment: {ack_data['error']}")

                logger.info("STT server acknowledgment diterima")

                # Kirim audio chunks
                total_sent = 0
                async for chunk in audio_chunks:
                    for i in range(0, len(chunk), chunk_size):
                        sub_chunk = chunk[i:i + chunk_size]
                        audio_msg = build_stt_audio_request(sub_chunk, is_last=False)
                        await ws.send(audio_msg)
                        total_sent += len(sub_chunk)
                        # Interval 100ms sesuai best practice
                        await asyncio.sleep(0.1)

                # Kirim final packet (empty, dengan flag last)
                logger.info("Audio terkirim: %d bytes, mengirim final packet", total_sent)
                final_msg = build_stt_audio_request(b"", is_last=True)
                await ws.send(final_msg)

                # Terima hasil transkripsi
                final_text = ""
                while True:
                    try:
                        response = await asyncio.wait_for(ws.recv(), timeout=30.0)

                        # Debug: log raw frame info
                        if isinstance(response, bytes):
                            logger.info("STT response frame: %s", debug_frame(response))
                        else:
                            logger.info("STT response type: %s, content: %s", type(response), str(response)[:200])

                        try:
                            resp_data = parse_stt_response(response)
                        except Exception as e:
                            logger.warning("STT response parse error: %s", e)
                            # Coba baca sebagai text jika bukan binary protocol
                            if isinstance(response, str):
                                try:
                                    resp_data = json.loads(response)
                                except Exception:
                                    resp_data = {"raw": response}
                            else:
                                continue

                        if "error" in resp_data:
                            logger.error("STT error: %s", resp_data["error"])
                            break

                        # Ekstrak teks dari response
                        result = resp_data.get("result", {})
                        text = result.get("text", "")

                        if text:
                            final_text = text
                            logger.info("STT teks: %s", text)

                        # Cek apakah ini response terakhir
                        if resp_data.get("_is_last", False):
                            logger.info("STT response terakhir diterima")
                            break

                    except asyncio.TimeoutError:
                        logger.warning("STT timeout menunggu response")
                        break

                return final_text.strip()

        except websockets.exceptions.ConnectionClosed as e:
            logger.error("STT WebSocket connection closed: %s", e)
            raise
        except Exception as e:
            logger.error("STT error: %s", e)
            raise

    async def transcribe_bytes(
        self,
        audio_data: bytes,
        chunk_size: int = 3200,
        on_partial: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> str:
        """
        Transcribe audio bytes ke teks (convenience method).

        Args:
            audio_data: PCM audio bytes (16kHz, 16-bit, mono)
            chunk_size: Ukuran chunk dalam bytes
            on_partial: Callback untuk partial transcription

        Returns:
            Teks hasil transkripsi
        """
        async def chunk_generator():
            for i in range(0, len(audio_data), chunk_size):
                yield audio_data[i:i + chunk_size]

        return await self.transcribe(chunk_generator(), chunk_size, on_partial=on_partial)
