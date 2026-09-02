/**
 * BytePlus Voice Chat - Frontend Application v2.0 (Optimized Pipeline)
 *
 * Fitur:
 * - Push-to-talk voice recording (PCM 16kHz, 16-bit, mono)
 * - Text input mode
 * - Streaming AI response display (token per token)
 * - Streaming audio playback (play chunks saat diterima, tidak menunggu seluruh audio)
 * - Partial transcription display (real-time STT)
 * - Conversation history display
 * - Bahasa Indonesia sebagai default
 */

// ============================================
// State Management
// ============================================
const state = {
    ws: null,
    isConnected: false,
    isRecording: false,
    isProcessing: false,
    isSpeaking: false,         // TTS sedang berbicara (bisa di-interrupt)
    audioContext: null,
    mediaStream: null,
    scriptProcessor: null,
    audioSource: null,
    audioBuffer: [],
    config: null,
    // Streaming state
    currentAIMessage: null,     // Element untuk AI message yang sedang streaming
    audioChunksQueue: [],       // Queue audio chunks untuk playback paralel
    audioPlaybackQueue: [],     // Blob URLs untuk playback berurutan
    isPlayingAudio: false,
    currentAudioBlob: null,
};

// ============================================
// DOM Elements
// ============================================
const dom = {
    statusDot: document.getElementById('statusDot'),
    statusText: document.getElementById('statusText'),
    micButton: document.getElementById('micButton'),
    micLabel: document.getElementById('micLabel'),
    textInput: document.getElementById('textInput'),
    sendTextBtn: document.getElementById('sendTextBtn'),
    messagesContainer: document.getElementById('messagesContainer'),
    typingIndicator: document.getElementById('typingIndicator'),
    audioPlayer: document.getElementById('audioPlayer'),
    chatArea: document.getElementById('chatArea'),
};

// ============================================
// WebSocket Management
// ============================================
function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/voice-chat`;

    console.log('Connecting to:', wsUrl);
    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = () => {
        state.isConnected = true;
        updateStatus('connected', 'Siap');
        console.log('WebSocket connected');
    };

    state.ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        handleWebSocketMessage(data);
    };

    state.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        updateStatus('error', 'Connection error');
    };

    state.ws.onclose = () => {
        state.isConnected = false;
        updateStatus('disconnected', 'Koneksi terputus. Menghubungkan ulang...');
        console.log('WebSocket disconnected, reconnecting in 3s...');
        setTimeout(connectWebSocket, 3000);
    };
}

function sendJSON(data) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.send(JSON.stringify(data));
        return true;
    }
    console.warn('WebSocket not connected');
    return false;
}

// ============================================
// WebSocket Message Handler
// ============================================
function handleWebSocketMessage(data) {
    switch (data.type) {
        case 'status':
            handleStatusMessage(data);
            break;

        case 'partial_transcription':
            // STT partial - tampilkan teks parsial real-time
            updatePartialTranscription(data.text);
            break;

        case 'transcription':
            // STT final - tampilkan sebagai user message
            finalizeTranscription(data.text);
            break;

        case 'ai_response_start':
            // AI mulai generate - buat element untuk streaming text
            startAIStreamingMessage();
            break;

        case 'ai_response_chunk':
            // AI token streaming - append ke element
            appendToAIStream(data.text);
            break;

        case 'ai_response_done':
            // AI selesai
            finishAIStream();
            break;

        case 'audio_start':
            // Audio mulai dikirim - siapkan audio playback
            if (data.sample_rate) {
                ttsSampleRate = data.sample_rate;
            }
            startAudioPlayback(data.format);
            break;

        case 'audio_chunk':
            // Audio chunk streaming - tambahkan ke playback queue
            addAudioChunk(data.data);
            break;

        case 'audio_end':
            // Audio selesai
            state.isSpeaking = false;
            finishAudioPlayback();
            break;

        case 'error':
            addMessage(data.message, 'error');
            updateStatus('connected', 'Siap');
            state.isProcessing = false;
            updateMicButton();
            break;
    }
}

function handleStatusMessage(data) {
    const statusMap = {
        'recording': { dot: 'recording', text: data.message || 'Merekam...' },
        'transcribing': { dot: 'thinking', text: data.message || 'Mengenali suara...' },
        'thinking': { dot: 'thinking', text: data.message || 'AI berpikir...' },
        'speaking': { dot: 'speaking', text: data.message || 'Berbicara...' },
        'ready': { dot: 'connected', text: data.message || 'Siap' },
    };

    const statusInfo = statusMap[data.status] || statusMap['ready'];
    updateStatus(statusInfo.dot, statusInfo.text);

    // Show/hide typing indicator
    if (data.status === 'thinking' || data.status === 'transcribing') {
        showTypingIndicator(true);
    } else if (data.status === 'speaking' || data.status === 'ready') {
        showTypingIndicator(false);
    }

    if (data.status === 'speaking') {
        state.isSpeaking = true;
        updateMicButton();
    } else if (data.status === 'ready') {
        state.isProcessing = false;
        state.isSpeaking = false;
        updateMicButton();
    }
}

// ============================================
// Streaming Text Display
// ============================================

let partialTranscriptionElement = null;

function updatePartialTranscription(text) {
    // Update atau buat element untuk partial transcription
    if (!partialTranscriptionElement) {
        partialTranscriptionElement = createMessageElement('', 'user');
        partialTranscriptionElement.querySelector('.message-bubble').classList.add('partial');
        dom.messagesContainer.appendChild(partialTranscriptionElement);
    }

    partialTranscriptionElement.querySelector('.message-bubble').textContent = text;
    dom.chatArea.scrollTop = dom.chatArea.scrollHeight;
}

function finalizeTranscription(text) {
    // Hapus partial transcription element jika ada
    if (partialTranscriptionElement) {
        partialTranscriptionElement.remove();
        partialTranscriptionElement = null;
    }

    // Tambahkan sebagai user message final
    addMessage(text, 'user');
}

function startAIStreamingMessage() {
    // Buat element baru untuk AI response streaming
    state.currentAIMessage = createMessageElement('', 'ai');
    state.currentAIMessage.querySelector('.message-bubble').classList.add('streaming');
    dom.messagesContainer.appendChild(state.currentAIMessage);
    dom.chatArea.scrollTop = dom.chatArea.scrollHeight;
}

function appendToAIStream(text) {
    if (state.currentAIMessage) {
        const bubble = state.currentAIMessage.querySelector('.message-bubble');
        bubble.textContent += text;
        dom.chatArea.scrollTop = dom.chatArea.scrollHeight;
    }
}

function finishAIStream() {
    if (state.currentAIMessage) {
        const bubble = state.currentAIMessage.querySelector('.message-bubble');
        bubble.classList.remove('streaming');
        bubble.classList.add('done');
        state.currentAIMessage = null;
    }
}

// ============================================
// Streaming Audio Playback - Web Audio API (gapless PCM)
// ============================================

let audioFormat = 'pcm';
let ttsSampleRate = 24000;

// Web Audio API untuk gapless PCM playback
let playbackCtx = null;
let nextPlayTime = 0;
let isPlayingAudio = false;
let useWebAudio = false;
let isInterrupted = false;   // Flag: tolak audio chunks setelah interrupt

// Fallback: WAV blob queue (untuk PCM jika Web Audio API tidak tersedia)
let audioPlaybackQueue = [];
let currentAudioEl = null;

function startAudioPlayback(format) {
    audioFormat = format || 'pcm';
    audioPlaybackQueue = [];
    isPlayingAudio = false;
    isInterrupted = false;   // Reset: audio baru dimulai

    if (audioFormat === 'pcm') {
        // Coba Web Audio API dengan sample rate TTS
        try {
            const AudioContextClass = window.AudioContext || window.webkitAudioContext;
            playbackCtx = new AudioContextClass({ sampleRate: ttsSampleRate });
            nextPlayTime = playbackCtx.currentTime;
            useWebAudio = true;
            console.log(`Audio playback: Web Audio API (PCM ${ttsSampleRate}Hz)`);
        } catch (e) {
            console.warn('Web Audio API gagal, fallback ke WAV blob:', e);
            playbackCtx = null;
            useWebAudio = false;
        }
    } else {
        useWebAudio = false;
        console.log(`Audio playback: Audio element mode (${audioFormat})`);
    }
}

function addAudioChunk(base64Data) {
    // Tolak chunks jika sedang di-interrupt (audio chunks masih dalam flight)
    if (isInterrupted) {
        console.log('Audio chunk discarded (interrupted)');
        return;
    }

    // Decode base64 ke binary
    const binaryStr = atob(base64Data);
    const len = binaryStr.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryStr.charCodeAt(i);
    }

    if (audioFormat === 'pcm') {
        if (useWebAudio && playbackCtx) {
            playPCMChunk(bytes);
        } else {
            // Fallback: buat WAV blob dari PCM data
            playWAVFallback(bytes);
        }
    } else {
        // MP3: Audio element
        audioPlaybackQueue.push(bytes);
        if (!isPlayingAudio && audioPlaybackQueue.length >= 1) {
            playNextAudioChunk();
        }
    }
}

function playPCMChunk(bytes) {
    // PCM 16-bit signed, mono → Float32 untuk Web Audio API
    const sampleCount = Math.floor(bytes.length / 2);
    if (sampleCount === 0) return;

    const audioBuffer = playbackCtx.createBuffer(1, sampleCount, ttsSampleRate);
    const channelData = audioBuffer.getChannelData(0);

    // Konversi Int16 PCM → Float32
    const dataView = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let i = 0; i < sampleCount; i++) {
        const sample = dataView.getInt16(i * 2, true);
        channelData[i] = sample / 32768.0;
    }

    // Schedule playback dengan precise timing (gapless)
    const sourceNode = playbackCtx.createBufferSource();
    sourceNode.buffer = audioBuffer;
    sourceNode.connect(playbackCtx.destination);

    const now = playbackCtx.currentTime;
    if (nextPlayTime < now) {
        nextPlayTime = now + 0.01;
    }

    sourceNode.start(nextPlayTime);
    nextPlayTime += audioBuffer.duration;
    isPlayingAudio = true;

    if (playbackCtx.state === 'suspended') {
        playbackCtx.resume();
    }
}

function playWAVFallback(pcmBytes) {
    // Buat WAV header + PCM data untuk Audio element
    const sampleCount = Math.floor(pcmBytes.length / 2);
    const buffer = new ArrayBuffer(44 + pcmBytes.length);
    const view = new DataView(buffer);

    // WAV header
    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + pcmBytes.length, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);       // fmt chunk size
    view.setUint16(20, 1, true);         // PCM format
    view.setUint16(22, 1, true);         // mono
    view.setUint32(24, ttsSampleRate, true);
    view.setUint32(28, ttsSampleRate * 2, true); // byte rate
    view.setUint16(32, 2, true);         // block align
    view.setUint16(34, 16, true);        // bits per sample
    writeString(view, 36, 'data');
    view.setUint32(40, pcmBytes.length, true);

    // Copy PCM data
    const pcmView = new Uint8Array(buffer, 44);
    pcmView.set(pcmBytes);

    // Play sebagai WAV blob
    audioPlaybackQueue.push(new Uint8Array(buffer));
    if (!isPlayingAudio && audioPlaybackQueue.length >= 1) {
        playNextAudioChunk();
    }
}

function writeString(view, offset, str) {
    for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i));
    }
}

function playNextAudioChunk() {
    if (audioPlaybackQueue.length === 0) {
        isPlayingAudio = false;
        return;
    }

    isPlayingAudio = true;

    // Gabungkan beberapa chunk untuk smooth playback
    const chunksToPlay = audioPlaybackQueue.splice(0, Math.min(3, audioPlaybackQueue.length));
    const combined = new Uint8Array(chunksToPlay.reduce((sum, c) => sum + c.length, 0));
    let offset = 0;
    for (const chunk of chunksToPlay) {
        combined.set(chunk, offset);
        offset += chunk.length;
    }

    const mimeType = audioFormat === 'pcm' ? 'audio/wav' : 'audio/mpeg';
    const blob = new Blob([combined], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const audioEl = new Audio(url);
    currentAudioEl = audioEl;

    audioEl.onended = () => {
        URL.revokeObjectURL(url);
        if (audioPlaybackQueue.length > 0) {
            playNextAudioChunk();
        } else {
            isPlayingAudio = false;
        }
    };

    audioEl.onerror = () => {
        URL.revokeObjectURL(url);
        if (audioPlaybackQueue.length > 0) {
            playNextAudioChunk();
        } else {
            isPlayingAudio = false;
        }
    };

    audioEl.play().catch(() => {
        URL.revokeObjectURL(url);
        isPlayingAudio = false;
    });
}

function finishAudioPlayback() {
    if (useWebAudio && playbackCtx) {
        console.log('Audio playback selesai (Web Audio API)');
        setTimeout(() => {
            nextPlayTime = playbackCtx.currentTime;
            isPlayingAudio = false;
        }, 200);
    } else {
        console.log('Audio playback selesai (Audio element)');
    }
}

// ============================================
// Interrupt - Hentikan TTS saat user mulai bicara
// ============================================

function playInterruptSound() {
    // Mainkan suara beep pendek sebagai sinyal interrupt
    try {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        const ctx = new AudioContextClass();

        const oscillator = ctx.createOscillator();
        const gainNode = ctx.createGain();

        oscillator.type = 'sine';
        oscillator.frequency.value = 880; // A5

        // Envelope: quick attack, fast decay
        const now = ctx.currentTime;
        gainNode.gain.setValueAtTime(0, now);
        gainNode.gain.linearRampToValueAtTime(0.3, now + 0.01);
        gainNode.gain.exponentialRampToValueAtTime(0.001, now + 0.15);

        oscillator.connect(gainNode);
        gainNode.connect(ctx.destination);

        oscillator.start(now);
        oscillator.stop(now + 0.15);

        oscillator.onended = () => {
            ctx.close();
        };

        console.log('Interrupt sound played');
    } catch (e) {
        console.warn('Could not play interrupt sound:', e);
    }
}

function stopAudioPlayback() {
    // Set flag: tolak semua audio chunks yang masih dalam flight
    isInterrupted = true;

    // Hentikan Web Audio API playback
    if (playbackCtx) {
        try {
            playbackCtx.close();
        } catch (e) {
            console.warn('Error closing playback context:', e);
        }
        playbackCtx = null;
    }

    // Hentikan audio element yang sedang play
    if (currentAudioEl) {
        try {
            currentAudioEl.pause();
            currentAudioEl.src = '';
        } catch (e) {}
        currentAudioEl = null;
    }

    // Clear queues
    audioPlaybackQueue = [];
    isPlayingAudio = false;
    useWebAudio = false;
}

function interruptTTS() {
    console.log('Interrupting TTS playback');
    // 1. Stop TTS audio terlebih dahulu
    stopAudioPlayback();
    // 2. Mainkan suara interrupt setelah TTS berhenti
    playInterruptSound();
    // 3. Kirim sinyal interrupt ke server
    sendJSON({ type: 'interrupt' });
}

// ============================================
// Audio Recording (Push-to-Talk)
// ============================================
async function startRecording() {
    if (state.isProcessing) {
        // Izinkan interrupt saat TTS sedang berbicara
        if (state.isSpeaking) {
            interruptTTS();
            state.isProcessing = false;
            state.isSpeaking = false;
        } else {
            return; // Tidak bisa interrupt saat STT/thinking
        }
    }

    try {
        // Request microphone access dengan konfigurasi optimal untuk speech
        const stream = await navigator.mediaDevices.getUserMedia({
            audio: {
                channelCount: 1,           // Mono
                sampleRate: 16000,         // 16kHz untuk STT
                echoCancellation: true,    // Hilangkan echo
                noiseSuppression: true,    // Hilangkan noise
                autoGainControl: true,     // Auto volume
            }
        });

        state.mediaStream = stream;

        // Create AudioContext
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        state.audioContext = new AudioContextClass({ sampleRate: 16000 });

        const actualSampleRate = state.audioContext.sampleRate;
        console.log(`AudioContext sample rate: ${actualSampleRate}`);

        state.audioSource = state.audioContext.createMediaStreamSource(stream);

        // ScriptProcessorNode untuk audio capture
        const bufferSize = 4096;  // ~256ms at 16kHz
        state.scriptProcessor = state.audioContext.createScriptProcessor(bufferSize, 1, 1);

        state.audioBuffer = [];

        state.scriptProcessor.onaudioprocess = (e) => {
            if (!state.isRecording) return;

            const input = e.inputBuffer.getChannelData(0);
            const pcm16 = float32ToInt16(input);

            // Resample jika perlu
            if (actualSampleRate !== 16000) {
                const resampled = resample(pcm16, actualSampleRate, 16000);
                state.audioBuffer.push(resampled.buffer);
            } else {
                state.audioBuffer.push(pcm16.buffer);
            }
        };

        state.audioSource.connect(state.scriptProcessor);
        state.scriptProcessor.connect(state.audioContext.destination);

        state.isRecording = true;
        state.audioBuffer = [];

        // Notify backend
        sendJSON({ type: 'start_recording' });

        updateStatus('recording', 'Merekam... Bicara sekarang!');
        updateMicButton();

        console.log('Recording started');

    } catch (error) {
        console.error('Error starting recording:', error);
        addMessage('Tidak dapat mengakses mikrofon. Pastikan izin mikrofon diberikan.', 'error');
    }
}

async function stopRecording() {
    if (!state.isRecording) return;

    state.isRecording = false;
    console.log('Recording stopped');

    // Disconnect audio nodes
    if (state.scriptProcessor) {
        state.scriptProcessor.disconnect();
        state.scriptProcessor = null;
    }
    if (state.audioSource) {
        state.audioSource.disconnect();
        state.audioSource = null;
    }

    // Stop media stream
    if (state.mediaStream) {
        state.mediaStream.getTracks().forEach(track => track.stop());
        state.mediaStream = null;
    }

    // Close AudioContext
    if (state.audioContext) {
        try {
            await state.audioContext.close();
        } catch (e) {
            console.warn('Error closing AudioContext:', e);
        }
        state.audioContext = null;
    }

    // Send all audio data to backend
    if (state.audioBuffer.length > 0) {
        state.isProcessing = true;
        updateMicButton();
        updateStatus('thinking', 'Memproses audio...');

        // Combine all audio chunks
        const totalLength = state.audioBuffer.reduce((sum, buf) => sum + buf.byteLength, 0);
        const combined = new Uint8Array(totalLength);
        let offset = 0;
        for (const buf of state.audioBuffer) {
            combined.set(new Uint8Array(buf), offset);
            offset += buf.byteLength;
        }

        // Send as base64
        const base64Data = arrayBufferToBase64(combined.buffer);
        sendJSON({ type: 'audio', data: base64Data });
        sendJSON({ type: 'stop_recording' });

        console.log(`Sent ${totalLength} bytes of audio data`);
    } else {
        updateStatus('connected', 'Siap');
    }

    state.audioBuffer = [];
}

// ============================================
// Audio Utilities
// ============================================

function float32ToInt16(float32) {
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
        const s = Math.max(-1, Math.min(1, float32[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16;
}

function resample(int16Data, fromRate, toRate) {
    if (fromRate === toRate) return int16Data;

    const ratio = fromRate / toRate;
    const newLength = Math.round(int16Data.length / ratio);
    const result = new Int16Array(newLength);

    for (let i = 0; i < newLength; i++) {
        const srcIndex = Math.floor(i * ratio);
        result[i] = int16Data[srcIndex];
    }

    return result;
}

function arrayBufferToBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    const chunkSize = 8192;
    for (let i = 0; i < bytes.length; i += chunkSize) {
        const chunk = bytes.subarray(i, i + chunkSize);
        binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
}

// ============================================
// UI Functions
// ============================================

function updateStatus(dotClass, text) {
    dom.statusDot.className = `status-dot ${dotClass}`;
    dom.statusText.textContent = text;
}

function updateMicButton() {
    if (state.isRecording) {
        dom.micButton.classList.add('recording');
        dom.micButton.querySelector('.mic-icon').style.display = 'none';
        dom.micButton.querySelector('.stop-icon').style.display = 'block';
        dom.micLabel.textContent = 'Lepaskan untuk mengirim';
    } else {
        dom.micButton.classList.remove('recording');
        dom.micButton.querySelector('.mic-icon').style.display = 'block';
        dom.micButton.querySelector('.stop-icon').style.display = 'none';
        if (state.isSpeaking) {
            dom.micLabel.textContent = 'Tahan untuk bicara (interrupt)';
        } else {
            dom.micLabel.textContent = state.isProcessing ? 'Memproses...' : 'Tahan untuk bicara';
        }
    }

    // Enable mic button saat TTS speaking (untuk interrupt)
    dom.micButton.disabled = state.isProcessing && !state.isSpeaking;
    dom.textInput.disabled = state.isProcessing;
    dom.sendTextBtn.disabled = state.isProcessing;
}

function createMessageElement(text, role) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${role}-message`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';

    if (role === 'user') {
        avatar.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/>
                <circle cx="12" cy="7" r="4"/>
            </svg>`;
    } else if (role === 'ai') {
        avatar.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M12 8V4H8"/>
                <rect width="16" height="12" x="4" y="8" rx="2"/>
                <path d="M2 14h2"/>
                <path d="M20 14h2"/>
                <path d="M15 13v2"/>
                <path d="M9 13v2"/>
            </svg>`;
    } else if (role === 'error') {
        avatar.innerHTML = `
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>`;
        messageDiv.classList.add('error-message');
    }

    const content = document.createElement('div');
    content.className = 'message-content';

    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    bubble.textContent = text;

    content.appendChild(bubble);
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);

    return messageDiv;
}

function addMessage(text, role) {
    const messageDiv = createMessageElement(text, role);
    dom.messagesContainer.appendChild(messageDiv);
    dom.chatArea.scrollTop = dom.chatArea.scrollHeight;
}

function showTypingIndicator(show) {
    dom.typingIndicator.style.display = show ? 'flex' : 'none';
    if (show) {
        dom.chatArea.scrollTop = dom.chatArea.scrollHeight;
    }
}

// ============================================
// Event Listeners
// ============================================

// Push-to-talk: mouse and touch events
let isMouseDown = false;

dom.micButton.addEventListener('mousedown', (e) => {
    e.preventDefault();
    isMouseDown = true;
    startRecording();
});

dom.micButton.addEventListener('mouseup', (e) => {
    e.preventDefault();
    if (isMouseDown) {
        isMouseDown = false;
        stopRecording();
    }
});

dom.micButton.addEventListener('mouseleave', () => {
    if (isMouseDown) {
        isMouseDown = false;
        stopRecording();
    }
});

// Touch events for mobile
dom.micButton.addEventListener('touchstart', (e) => {
    e.preventDefault();
    startRecording();
});

dom.micButton.addEventListener('touchend', (e) => {
    e.preventDefault();
    stopRecording();
});

// Text input
dom.sendTextBtn.addEventListener('click', sendTextMessage);

dom.textInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendTextMessage();
    }
});

function sendTextMessage() {
    const text = dom.textInput.value.trim();
    if (!text || state.isProcessing) return;

    dom.textInput.value = '';
    state.isProcessing = true;
    updateMicButton();

    sendJSON({ type: 'text', text: text });
    addMessage(text, 'user');
    updateStatus('thinking', 'AI berpikir...');
    showTypingIndicator(true);
}

// Keyboard shortcut: Space to talk (when not typing)
document.addEventListener('keydown', (e) => {
    if (e.code === 'Space' && document.activeElement !== dom.textInput) {
        // Izinkan interrupt saat TTS speaking, block saat processing lainnya
        if (state.isProcessing && !state.isSpeaking) return;
        e.preventDefault();
        if (!state.isRecording) {
            startRecording();
        }
    }
});

document.addEventListener('keyup', (e) => {
    if (e.code === 'Space' && state.isRecording) {
        e.preventDefault();
        stopRecording();
    }
});

// ============================================
// Initialize
// ============================================
window.addEventListener('load', () => {
    console.log('BytePlus Voice Chat v2.0 - Initializing...');
    console.log('Optimizations: streaming STT, streaming AI, streaming TTS, parallel pipeline');
    connectWebSocket();
});

// Handle page unload
window.addEventListener('beforeunload', () => {
    if (state.ws) {
        state.ws.close();
    }
    if (state.mediaStream) {
        state.mediaStream.getTracks().forEach(track => track.stop());
    }
});
