"""
BytePlus Voice Chat - FastAPI Server (Optimized Pipeline)

Aplikasi voice chat dengan pipeline paralel untuk latensi minimal:

  User bicara → STT (streaming) → AI (streaming) → TTS (streaming) → Audio play

Optimasi:
1. STT: bigmodel_async (streaming, first char ~600ms)
2. AI: SSE streaming (token per token)
3. TTS: dikirim per kalimat saat AI masih generate kalimat berikutnya
4. Audio: dikirim ke browser per chunk untuk playback paralel
5. Bahasa Indonesia di-enforce di semua level

Flow pipeline:
  - AI yields token → akumulasi teks
  - Deteksi kalimat lengkap (., !, ?, \n) → kirim ke TTS segera
  - TTS yields audio chunk → kirim ke browser segera
  - Browser play audio chunk saat diterima

Cara menjalankan:
  1. Set environment variables di .env file
  2. pip install -r requirements.txt
  3. python server.py
  4. Buka http://localhost:8000 di browser
"""

import os
import re
import json
import base64
import asyncio
import logging
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from stt_client import STTClient
from tts_client import TTSClient
from chat_client import ChatClient

# Load environment variables
load_dotenv()

# Setup logging - output ke console DAN file
log_format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
date_format = "%H:%M:%S"

logging.basicConfig(
    level=logging.INFO,
    format=log_format,
    datefmt=date_format,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("byteaudio.log", mode="a", encoding="utf-8"),
    ],
)
logger = logging.getLogger("byteaudio")

# Environment variables
STT_API_KEY = os.getenv("STT_API_KEY", "")
TTS_API_KEY = os.getenv("TTS_API_KEY", "")
ARK_API_KEY = os.getenv("ARK_API_KEY", "")

# Enforce Bahasa Indonesia sebagai default
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "id-ID")
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "zh_female_vv_uranus_bigtts")
TTS_AUDIO_FORMAT = os.getenv("TTS_AUDIO_FORMAT", "mp3")
TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE", "24000"))
TTS_EXPLICIT_LANGUAGE = os.getenv("TTS_EXPLICIT_LANGUAGE", "id")  # Enforce ID untuk TTS

ARK_MODEL = os.getenv("ARK_MODEL", "dola-seed-2-1-turbo-260628")
ARK_DISABLE_THINKING = os.getenv("ARK_DISABLE_THINKING", "true").lower() == "true"
ARK_MAX_TOKENS = int(os.getenv("ARK_MAX_TOKENS", "1000"))
SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "")

# FastAPI app
app = FastAPI(title="BytePlus Voice Chat", version="2.0.0")

# Static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def index():
    """Serve main page"""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Static folder not found</h1>", status_code=404)


@app.get("/api/config")
async def get_config():
    """Return client configuration"""
    return JSONResponse({
        "stt_language": STT_LANGUAGE,
        "tts_audio_format": TTS_AUDIO_FORMAT,
        "tts_sample_rate": TTS_SAMPLE_RATE,
        "ark_model": ARK_MODEL,
    })


@app.get("/api/health")
async def health():
    """Health check"""
    return {
        "status": "ok",
        "stt_configured": bool(STT_API_KEY),
        "tts_configured": bool(TTS_API_KEY),
        "ark_configured": bool(ARK_API_KEY),
        "model": ARK_MODEL,
        "language": STT_LANGUAGE,
    }


# Pattern untuk deteksi akhir kalimat
SENTENCE_END_PATTERN = re.compile(r'[.!?]\s*|\n')


def split_sentence_stream(text: str) -> tuple[str, str]:
    """
    Pisahkan teks menjadi kalimat lengkap dan sisa.

    Returns:
        (complete_sentences, remaining_text)
    """
    sentences = []
    remaining = text

    while True:
        match = SENTENCE_END_PATTERN.search(remaining)
        if not match:
            break

        # Ambil kalimat sampai akhir kalimat (termasuk punctuation)
        sentence = remaining[:match.end()]
        sentences.append(sentence)
        remaining = remaining[match.end():]

    return "".join(sentences), remaining


@app.websocket("/ws/voice-chat")
async def voice_chat(ws: WebSocket):
    """
    WebSocket endpoint untuk voice chat dengan pipeline paralel.

    Protocol pesan dari client (JSON):
    1. {"type": "start_recording"} - Mulai sesi rekaman
    2. {"type": "audio", "data": "<base64 PCM>"} - Kirim audio PCM
    3. {"type": "stop_recording"} - Stop rekaman, proses STT → AI → TTS
    4. {"type": "text", "text": "..."} - Kirim teks langsung (tanpa STT)
    5. {"type": "clear_history"} - Bersihkan conversation history
    6. {"type": "interrupt"} - Cancel pipeline yang sedang berjalan (TTS/AI)

    Protocol pesan ke client (JSON):
    1. {"type": "status", "status": "...", "message": "..."}
    2. {"type": "partial_transcription", "text": "..."} - STT partial (real-time)
    3. {"type": "transcription", "text": "..."} - STT final
    4. {"type": "ai_response_start"} - AI mulai generate
    5. {"type": "ai_response_chunk", "text": "..."} - AI token streaming
    6. {"type": "ai_response_done", "text": "..."} - AI selesai
    7. {"type": "audio_start", "format": "mp3"} - Audio mulai dikirim
    8. {"type": "audio_chunk", "data": "<base64>"} - Audio chunk streaming
    9. {"type": "audio_end"} - Audio selesai
    10. {"type": "error", "message": "..."}
    """
    await ws.accept()

    # Validasi API keys
    if not STT_API_KEY:
        await ws.send_json({"type": "error", "message": "STT_API_KEY belum dikonfigurasi. Set di file .env"})
        await ws.close()
        return

    if not ARK_API_KEY:
        await ws.send_json({"type": "error", "message": "ARK_API_KEY belum dikonfigurasi. Set di file .env"})
        await ws.close()
        return

    if not TTS_API_KEY:
        await ws.send_json({"type": "error", "message": "TTS_API_KEY belum dikonfigurasi. Set di file .env"})
        await ws.close()
        return

    # Initialize clients dengan konfigurasi Bahasa Indonesia
    stt_client = STTClient(
        api_key=STT_API_KEY,
        language=STT_LANGUAGE,  # id-ID
    )

    tts_client = TTSClient(
        api_key=TTS_API_KEY,
        speaker=TTS_SPEAKER,
        audio_format=TTS_AUDIO_FORMAT,
        sample_rate=TTS_SAMPLE_RATE,
        explicit_language=TTS_EXPLICIT_LANGUAGE,  # Enforce ID untuk TTS
    )

    chat_client = ChatClient(
        api_key=ARK_API_KEY,
        model=ARK_MODEL,
        system_prompt=SYSTEM_PROMPT if SYSTEM_PROMPT else None,  # Default: enforce ID
        disable_thinking=ARK_DISABLE_THINKING,
        max_tokens=ARK_MAX_TOKENS,
    )

    audio_buffer = bytearray()
    current_task = None  # Track ongoing pipeline task (for interrupt)

    logger.info("Voice chat WebSocket connected")

    try:
        while True:
            message = await ws.receive_text()
            data = json.loads(message)
            msg_type = data.get("type")

            if msg_type == "start_recording":
                audio_buffer.clear()
                await ws.send_json({"type": "status", "status": "recording", "message": "Mulai bicara..."})

            elif msg_type == "audio":
                # Terima audio PCM (base64 encoded)
                audio_b64 = data.get("data", "")
                if audio_b64:
                    audio_bytes = base64.b64decode(audio_b64)
                    audio_buffer.extend(audio_bytes)

            elif msg_type == "stop_recording":
                # Jalankan pipeline sebagai background task (bisa di-interrupt)
                audio_copy = bytes(audio_buffer)
                audio_buffer.clear()
                current_task = asyncio.create_task(
                    process_voice_input(ws, audio_copy, stt_client, chat_client, tts_client)
                )

            elif msg_type == "text":
                # Mode teks langsung (tanpa STT)
                text = data.get("text", "").strip()
                if text:
                    current_task = asyncio.create_task(
                        process_text_input(ws, text, chat_client, tts_client)
                    )

            elif msg_type == "interrupt":
                # Cancel pipeline yang sedang berjalan (TTS/AI)
                if current_task and not current_task.done():
                    logger.info("Interrupt: cancelling current pipeline task")
                    current_task.cancel()
                    try:
                        await current_task
                    except asyncio.CancelledError:
                        pass
                    # Kirim audio_end untuk finalize state di client
                    await ws.send_json({"type": "audio_end"})
                await ws.send_json({"type": "status", "status": "ready", "message": "Siap"})

            elif msg_type == "clear_history":
                chat_client.clear_history()
                await ws.send_json({"type": "status", "status": "ready", "message": "History dibersihkan"})

            else:
                await ws.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected")
        if current_task and not current_task.done():
            current_task.cancel()
    except Exception as e:
        logger.error("WebSocket error: %s", e, exc_info=True)
        try:
            await ws.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


async def process_voice_input(
    ws: WebSocket,
    audio_buffer: bytes,
    stt_client: STTClient,
    chat_client: ChatClient,
    tts_client: TTSClient,
):
    """Proses input suara: STT (streaming) → AI (streaming) → TTS (streaming)"""

    if len(audio_buffer) == 0:
        await ws.send_json({"type": "error", "message": "Tidak ada audio yang direkam"})
        return

    # Step 1: Speech-to-Text (streaming dengan partial results)
    await ws.send_json({"type": "status", "status": "transcribing", "message": "Mengenali suara..."})

    async def on_partial(text: str):
        """Kirim partial transcription ke browser untuk display real-time"""
        await ws.send_json({"type": "partial_transcription", "text": text})

    try:
        logger.info("Memulai STT streaming dengan %d bytes audio", len(audio_buffer))
        transcription = await stt_client.transcribe_bytes(bytes(audio_buffer), on_partial=on_partial)
        logger.info("STT final result: '%s'", transcription)

        if not transcription:
            await ws.send_json({"type": "status", "status": "ready", "message": "Tidak ada ucapan terdeteksi. Coba lagi."})
            return

        await ws.send_json({"type": "transcription", "text": transcription})

    except Exception as e:
        logger.error("STT error: %s", e, exc_info=True)
        await ws.send_json({"type": "error", "message": f"STT error: {e}"})
        return

    # Step 2+3: AI Chat (streaming) → TTS (streaming per kalimat) - PIPELINE PARALEL
    await pipeline_ai_to_tts(ws, transcription, chat_client, tts_client)


async def process_text_input(
    ws: WebSocket,
    text: str,
    chat_client: ChatClient,
    tts_client: TTSClient,
):
    """Proses input teks: AI (streaming) → TTS (streaming) - PIPELINE PARALEL"""
    await ws.send_json({"type": "transcription", "text": text})
    await pipeline_ai_to_tts(ws, text, chat_client, tts_client)


async def pipeline_ai_to_tts(
    ws: WebSocket,
    user_text: str,
    chat_client: ChatClient,
    tts_client: TTSClient,
):
    """
    Pipeline paralel: AI streaming → TTS streaming → Audio streaming ke browser.

    Flow (optimized - satu TTS session untuk seluruh AI response):
    1. AI yields token per token (SSE streaming)
    2. Token dikirim ke browser untuk display real-time
    3. Token dikirim ke TTS sebagai TaskRequest (streaming text input)
    4. TTS memecah teks menjadi kalimat secara internal dan menghasilkan audio
    5. Audio chunks diyield ke browser segera saat diterima

    Best practice dari dokumentasi TTS 2.0:
    "推荐将流式输出的文本直接输入该接口，而不要额外增加切句或者攒句的逻辑"
    (Masukkan teks streaming langsung ke TTS, jangan pecah kalimat sendiri)
    """
    await ws.send_json({"type": "status", "status": "thinking", "message": "AI berpikir..."})
    await ws.send_json({"type": "ai_response_start"})

    response_holder = {"text": ""}
    text_buffer = ""

    # Queue untuk passing text chunks dari AI ke TTS
    text_queue: asyncio.Queue = asyncio.Queue()
    TTS_SENTINEL = None  # Signal bahwa AI text sudah selesai

    async def ai_producer():
        """Konsumsi AI streaming, kirim token ke browser dan ke TTS queue"""
        nonlocal text_buffer
        try:
            async for token in chat_client.chat_stream(user_text):
                response_holder["text"] += token
                text_buffer += token

                # Kirim token ke browser untuk display real-time
                await ws.send_json({"type": "ai_response_chunk", "text": token})

                # Cek apakah ada kalimat/frasa lengkap (., !, ?, \n)
                # Kirim ke TTS per kalimat agar audio dimulai lebih cepat
                complete, remaining = split_sentence_stream(text_buffer)
                if complete:
                    await text_queue.put(complete)
                    text_buffer = remaining

        except Exception as e:
            logger.error("AI streaming error: %s", e, exc_info=True)
            await ws.send_json({"type": "error", "message": f"AI error: {e}"})
        finally:
            # Kirim sisa teks
            if text_buffer.strip():
                await text_queue.put(text_buffer)
            # Signal: tidak ada lagi teks
            await text_queue.put(TTS_SENTINEL)

    async def tts_consumer():
        """Konsumsi text dari queue, stream ke TTS dalam SATU session, kirim audio ke browser"""
        audio_started = False
        try:
            # Kumpulkan text chunks ke dalam async generator
            async def text_generator():
                while True:
                    chunk = await text_queue.get()
                    if chunk is TTS_SENTINEL:
                        return
                    if chunk and chunk.strip():
                        yield chunk.strip()

            # Mulai audio stream
            await ws.send_json({
                "type": "audio_start",
                "format": TTS_AUDIO_FORMAT,
                "sample_rate": TTS_SAMPLE_RATE,
            })
            await ws.send_json({"type": "status", "status": "speaking", "message": "Berbicara..."})
            audio_started = True

            # Satu TTS session untuk seluruh AI response
            async for audio_chunk in tts_client.synthesize_streaming(text_generator()):
                if audio_chunk:
                    audio_b64 = base64.b64encode(audio_chunk).decode("utf-8")
                    await ws.send_json({
                        "type": "audio_chunk",
                        "data": audio_b64,
                    })

        except Exception as e:
            logger.error("TTS streaming error: %s", e, exc_info=True)
            await ws.send_json({"type": "error", "message": f"TTS error: {e}"})
        finally:
            if audio_started:
                await ws.send_json({"type": "audio_end"})

    # Jalankan AI producer dan TTS consumer secara paralel
    ai_task = asyncio.create_task(ai_producer())
    tts_task = asyncio.create_task(tts_consumer())

    try:
        await asyncio.gather(ai_task, tts_task)
    except asyncio.CancelledError:
        # Pipeline di-interrupt oleh user - cancel sub-tasks
        logger.info("Pipeline cancelled by interrupt")
        ai_task.cancel()
        tts_task.cancel()
        await asyncio.gather(ai_task, tts_task, return_exceptions=True)
        raise

    await ws.send_json({"type": "ai_response_done", "text": response_holder["text"]})
    await ws.send_json({"type": "status", "status": "ready", "message": "Siap"})


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))

    logger.info("=" * 60)
    logger.info("BytePlus Voice Chat Server v2.0 (Optimized Pipeline)")
    logger.info("=" * 60)
    logger.info("Model AI: %s", ARK_MODEL)
    logger.info("STT Language: %s (streaming bigmodel_async)", STT_LANGUAGE)
    logger.info("TTS Speaker: %s", TTS_SPEAKER)
    logger.info("TTS Language: %s (enforced)", TTS_EXPLICIT_LANGUAGE)
    logger.info("TTS Format: %s @ %dHz", TTS_AUDIO_FORMAT, TTS_SAMPLE_RATE)
    logger.info("Thinking: %s", "disabled (fast)" if ARK_DISABLE_THINKING else "enabled")
    logger.info("Pipeline: STT stream → AI stream → TTS stream (parallel)")
    logger.info("STT API Key: %s", "***configured***" if STT_API_KEY else "***MISSING***")
    logger.info("TTS API Key: %s", "***configured***" if TTS_API_KEY else "***MISSING***")
    logger.info("ARK API Key: %s", "***configured***" if ARK_API_KEY else "***MISSING***")
    logger.info("=" * 60)
    logger.info("Server: http://%s:%d", host, port)
    logger.info("=" * 60)

    uvicorn.run(app, host=host, port=port, log_level="info")
