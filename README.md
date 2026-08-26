# BytePlus Voice Chat v2.0

Aplikasi voice chat real-time yang menggabungkan **BytePlus STT 2.0**, **TTS 2.0**, dan **ModelArk AI** dengan pipeline paralel untuk latensi minimal. Bahasa Indonesia di-enforce di semua level.

## Fitur Utama

- **Streaming penuh** - STT → AI → TTS dipipeline secara paralel, audio mulai diputar ~2-3 detik
- **Bahasa Indonesia** - Di-enforce di 4 level (STT, AI system prompt, TTS explicit_language, UI)
- **TTS 2.0 dengan voice Vivi** - `zh_female_vv_uranus_bigtts` (supports Indonesian)
- **Gapless PCM playback** - Web Audio API untuk audio tanpa putus
- **Push-to-Talk** - Tahan tombol mikrofon atau tekan Space
- **Text mode** - Ketik pesan jika tidak ingin bicara
- **Real-time text display** - AI response muncul token per token

## Arsitektur

```
Browser (Microphone)
    │ PCM 16kHz mono
    ▼
┌──────────────────────────────────────────────┐
│  FastAPI Server (Python)                     │
│                                              │
│  ┌─────────┐   ┌─────────┐   ┌──────────┐  │
│  │ STT 2.0 │──►│ ModelArk│──►│ TTS 2.0  │  │
│  │ Stream  │   │ Stream  │   │ Stream   │  │
│  └─────────┘   └─────────┘   └──────────┘  │
│                                   │          │
│                    Audio chunks ──┘          │
└──────────────────────────────────────────────┘
    │ WebSocket (audio chunks + text)
    ▼
Browser (Web Audio API - gapless PCM playback)
```

### Optimasi Pipeline

| Komponen | Teknik | Latensi |
|----------|--------|---------|
| STT 2.0 | `bigmodel_nostream` binary WebSocket | ~1-2s |
| ModelArk AI | SSE streaming, thinking disabled | ~500ms first token |
| TTS 2.0 | Single session, streaming text input | ~1s first audio |
| Audio | Web Audio API PCM, gapless scheduling | 0ms gap |

**Total first-audio latency: ~2-3 detik** (vs 8-15 detik sequential)

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/yourusername/byteplus-voice-chat.git
cd byteplus-voice-chat

# Copy environment template
cp .env.example .env
```

### 2. Dapatkan API Keys

- **STT & TTS**: [BytePlus Voice Console](https://console.byteplus.com/voice/service/8)
- **ModelArk AI**: [API Key Management](https://ai.byteplus.com/ark/region:ap-southeast-1/apikey)
- **Aktifkan model**: `dola-seed-2-1-turbo-260628` di [Model Activation](https://ai.byteplus.com/ark/region:ap-southeast-1/openManagement)

### 3. Isi `.env`

```env
STT_API_KEY=your-stt-key
TTS_API_KEY=your-tts-key
ARK_API_KEY=ark-your-ark-key
```

### 4. Jalankan

**Linux / macOS:**
```bash
chmod +x start.sh stop.sh
./start.sh
```

**Windows (PowerShell):**
```powershell
.\start.ps1
```

Buka `http://localhost:8000` di browser Chrome/Firefox.

### Stop Server

```bash
./stop.sh        # Linux/macOS
.\stop.ps1       # Windows
```

## Konfigurasi `.env`

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `STT_API_KEY` | - | API Key BytePlus Speech-to-Text |
| `STT_LANGUAGE` | `id-ID` | Bahasa STT (Indonesia) |
| `TTS_API_KEY` | - | API Key BytePlus Text-to-Speech |
| `TTS_SPEAKER` | `zh_female_vv_uranus_bigtts` | Voice ID (Vivi 2.0, supports Indonesian) |
| `TTS_AUDIO_FORMAT` | `pcm` | Format audio (pcm, mp3, ogg_opus) |
| `TTS_SAMPLE_RATE` | `24000` | Sample rate (8000-48000) |
| `TTS_EXPLICIT_LANGUAGE` | `id` | Enforce bahasa TTS |
| `ARK_API_KEY` | - | API Key ModelArk |
| `ARK_MODEL` | `dola-seed-2-1-turbo-260628` | Model AI |
| `ARK_DISABLE_THINKING` | `true` | Disable thinking mode untuk speed |
| `ARK_MAX_TOKENS` | `1000` | Max output tokens |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |

## TTS 2.0 Protocol

Aplikasi menggunakan TTS 2.0 bidirectional WebSocket dengan binary protocol:

```
Flow:
  1. WebSocket connect (headers: X-Api-Key, X-Api-Resource-Id, X-Api-Connect-Id)
  2. StartConnection (event=1) → ConnectionStarted (event=50)
  3. StartSession (event=100) → SessionStarted (event=150)
  4. Multiple TaskRequest (event=200) → audio chunks (event=352)
  5. FinishSession (event=102) → SessionFinished (event=152)
  6. FinishConnection (event=2)
```

Best practice dari dokumentasi: teks streaming dari AI langsung diinput ke TTS tanpa split kalimat manual. TTS API akan otomatis memecah menjadi kalimat yang sesuai.

## Voice List

TTS 2.0 menggunakan voice dengan suffix `*_uranus_bigtts`. Voice yang mendukung Bahasa Indonesia:

| Voice | ID | Bahasa |
|-------|----|--------|
| Vivi 2.0 | `zh_female_vv_uranus_bigtts` | Chinese, Japanese, **Indonesian**, Spanish |

Lihat daftar lengkap di [BytePlus Voice List](https://docs.byteplus.com/en/docs/byteplusvoice/voicelist).

## Struktur Project

```
byteplus-voice-chat/
├── server.py              # FastAPI server (pipeline paralel)
├── binary_protocol.py     # Binary WebSocket protocol (STT & TTS 2.0)
├── stt_client.py          # STT 2.0 client (streaming WebSocket)
├── tts_client.py          # TTS 2.0 client (session reuse, streaming)
├── chat_client.py         # ModelArk client (SSE streaming)
├── requirements.txt       # Python dependencies
├── requirements-test.txt  # Test dependencies
├── pytest.ini             # Test configuration
├── .env.example           # Environment template
├── .env                   # Environment config (gitignored)
├── .gitignore
├── start.sh               # Start script (Linux/macOS)
├── stop.sh                # Stop script (Linux/macOS)
├── start.ps1              # Start script (Windows)
├── stop.ps1               # Stop script (Windows)
├── static/
│   ├── index.html         # Frontend UI
│   ├── app.js             # Frontend (streaming text + gapless PCM audio)
│   └── style.css          # Dark theme styling
├── tests/
│   ├── conftest.py        # Test fixtures & mock builders
│   ├── test_binary_protocol.py  # 76 unit tests
│   ├── test_chat_client.py
│   ├── test_server.py
│   ├── test_stt_client.py
│   └── test_tts_client.py
├── byteplus-voice-chat-prd/   # PRD documentation (HTML)
└── README.md
```

## Cara Penggunaan

### Voice Mode (Push-to-Talk)
1. **Tahan** tombol mikrofon (atau tekan **Space**)
2. Bicara dalam Bahasa Indonesia
3. **Lepaskan** untuk mengirim
4. Teks AI muncul real-time, audio diputar saat tersedia

### Text Mode
1. Ketik pesan dalam Bahasa Indonesia
2. Tekan **Enter** atau klik tombol kirim
3. AI response muncul token per token, audio diputar paralel

## Testing

```bash
pip install -r requirements-test.txt
python -m pytest tests/ -v
```

## Cloudflare Tunnel (Opsional)

Untuk akses dari internet:

```bash
# Download cloudflared
# Windows: sudah include cloudflared.exe
# Linux: wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64

# Jalankan tunnel
cloudflared tunnel --url http://localhost:8000
```

## Teknologi

| Komponen | Teknologi |
|----------|-----------|
| Backend | Python 3.10+, FastAPI, uvicorn |
| STT | BytePlus STT 2.0 (WebSocket binary protocol) |
| TTS | BytePlus TTS 2.0 (WebSocket binary protocol, session reuse) |
| AI | BytePlus ModelArk (SSE streaming, OpenAI-compatible) |
| Frontend | Vanilla JS, Web Audio API, WebSocket |
| Audio | PCM 24kHz mono, gapless playback via AudioContext |

## Referensi

- [BytePlus STT 2.0 Docs](https://docs.byteplus.com/en/docs/byteplusvoice/speechtotextv2)
- [BytePlus TTS 2.0 Docs](https://docs.byteplus.com/en/docs/byteplusvoice/texttospeechv2)
- [BytePlus Voice List](https://docs.byteplus.com/en/docs/byteplusvoice/voicelist)
- [BytePlus ModelArk](https://docs.byteplus.com/en/docs/ModelArk/1399008)

## License

MIT
