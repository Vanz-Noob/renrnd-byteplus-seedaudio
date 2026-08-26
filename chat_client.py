"""
BytePlus ModelArk Chat Client

Menggunakan OpenAI-compatible Chat Completions API dengan SSE streaming.
- Streaming response untuk menampilkan teks real-time per token
- Thinking disabled by default untuk response cepat
- System prompt meng-enforce Bahasa Indonesia

Endpoint: https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions
Model: dola-seed-2-1-turbo-260628
"""

import json
import logging
from typing import Optional, AsyncGenerator

import httpx

logger = logging.getLogger(__name__)

# ModelArk API endpoints
ARK_BASE_URL = "https://ark.ap-southeast.bytepluses.com/api/v3"
ARK_CHAT_URL = f"{ARK_BASE_URL}/chat/completions"

# Default model
DEFAULT_MODEL = "dola-seed-2-1-turbo-260628"

# System prompt yang meng-enforce Bahasa Indonesia
DEFAULT_SYSTEM_PROMPT = (
    "Kamu adalah asisten AI suara yang ramah dan responsif. "
    "Aturan WAJIB:\n"
    "1. SELALU jawab dalam Bahasa Indonesia, tidak bahasa lain.\n"
    "2. Jawab dengan singkat, padat, dan jelas. Maksimal 2-3 kalimat untuk jawaban sederhana.\n"
    "3. Jangan gunakan markdown, formatting, atau simbol khusus (karena akan dibacakan oleh TTS).\n"
    "4. Gunakan bahasa percakapan yang natural dan mudah dibacakan.\n"
    "5. Jika user bertanya dalam bahasa lain, tetap jawab dalam Bahasa Indonesia.\n"
    "6. Untuk pertanyaan kompleks, pecah jawaban menjadi kalimat-kalimat pendek yang jelas."
)


class ChatClient:
    """Client untuk BytePlus ModelArk Chat API dengan streaming support"""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = ARK_BASE_URL,
        system_prompt: Optional[str] = None,
        disable_thinking: bool = True,
        max_tokens: int = 1000,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.disable_thinking = disable_thinking
        self.max_tokens = max_tokens
        self.conversation_history: list = []

    def _build_headers(self) -> dict:
        """Build HTTP headers"""
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_messages(self, user_message: str) -> list:
        """Build messages array untuk chat API"""
        messages = []

        # System prompt
        if self.system_prompt:
            messages.append({
                "role": "system",
                "content": self.system_prompt,
            })

        # Conversation history (batasi ke 10 pesan terakhir untuk efisiensi token)
        messages.extend(self.conversation_history[-10:])

        # Current user message
        messages.append({
            "role": "user",
            "content": user_message,
        })

        return messages

    async def chat_stream(self, user_message: str) -> AsyncGenerator[str, None]:
        """
        Streaming chat - yields teks per token (SSE streaming).

        Memungkinkan pipeline paralel: AI teks streaming → TTS per kalimat → audio play.

        Args:
            user_message: Pesan dari user

        Yields:
            Token teks dari AI secara streaming
        """
        messages = self._build_messages(user_message)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,  # SSE streaming untuk response real-time
            "max_tokens": self.max_tokens,
        }

        # Disable thinking untuk response cepat
        if self.disable_thinking:
            payload["thinking"] = {"type": "disabled"}

        logger.info("Mengirim streaming request ke ModelArk (model: %s)", self.model)

        full_response = ""

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    ARK_CHAT_URL,
                    headers=self._build_headers(),
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:]  # Remove "data: " prefix

                        if data_str.strip() == "[DONE]":
                            break

                        try:
                            chunk = json.loads(data_str)
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")

                            if content:
                                full_response += content
                                yield content

                        except json.JSONDecodeError:
                            continue

        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_data = e.response.json()
                error_detail = error_data.get("error", {}).get("message", str(error_data))
            except Exception:
                error_detail = e.response.text
            logger.error("ModelArk HTTP error %d: %s", e.response.status_code, error_detail)
            raise RuntimeError(f"ModelArk API error ({e.response.status_code}): {error_detail}")

        except httpx.RequestError as e:
            logger.error("ModelArk request error: %s", e)
            raise RuntimeError(f"ModelArk request error: {e}")

        # Simpan ke conversation history
        if full_response:
            self.conversation_history.append({
                "role": "user",
                "content": user_message,
            })
            self.conversation_history.append({
                "role": "assistant",
                "content": full_response,
            })

            # Batasi history ke 20 pesan terakhir
            if len(self.conversation_history) > 20:
                self.conversation_history = self.conversation_history[-20:]

        logger.info("ModelArk streaming selesai: %d chars", len(full_response))

    async def chat(self, user_message: str, timeout: float = 60.0) -> str:
        """
        Non-streaming chat (untuk backward compatibility).

        Args:
            user_message: Pesan dari user
            timeout: Timeout dalam detik

        Returns:
            Response teks lengkap dari AI
        """
        full_text = ""
        async for token in self.chat_stream(user_message):
            full_text += token
        return full_text

    def clear_history(self):
        """Bersihkan conversation history"""
        self.conversation_history.clear()
        logger.info("Conversation history dibersihkan")
