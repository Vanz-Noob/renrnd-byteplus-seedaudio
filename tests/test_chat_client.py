"""
Unit test untuk chat_client.py

Menguji:
- Inisialisasi client dengan konfigurasi default (enforce Bahasa Indonesia)
- Build messages array (system prompt + history + user message)
- SSE streaming chat dengan mock httpx response
- Non-streaming chat (wrapper chat())
- Conversation history management
- Error handling (HTTP error, request error)
- System prompt enforce Bahasa Indonesia
"""

import json
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from chat_client import ChatClient, DEFAULT_SYSTEM_PROMPT, DEFAULT_MODEL

from tests.conftest import (
    TEST_ARK_API_KEY,
    make_sse_chunks,
)


class TestChatClientInit:
    """Test inisialisasi ChatClient"""

    def test_default_config(self):
        """Client dengan konfigurasi default harus enforce Bahasa Indonesia"""
        client = ChatClient(api_key=TEST_ARK_API_KEY)

        assert client.api_key == TEST_ARK_API_KEY
        assert client.model == DEFAULT_MODEL
        assert "Bahasa Indonesia" in client.system_prompt
        assert client.disable_thinking is True
        assert client.max_tokens == 1000
        assert client.conversation_history == []

    def test_custom_config(self):
        """Client dengan konfigurasi custom"""
        client = ChatClient(
            api_key=TEST_ARK_API_KEY,
            model="custom-model",
            system_prompt="Jawab singkat",
            disable_thinking=False,
            max_tokens=500,
        )

        assert client.model == "custom-model"
        assert client.system_prompt == "Jawab singkat"
        assert client.disable_thinking is False
        assert client.max_tokens == 500

    def test_system_prompt_enforces_indonesian(self):
        """System prompt default harus mengandung aturan Bahasa Indonesia"""
        client = ChatClient(api_key=TEST_ARK_API_KEY)

        assert "SELALU" in client.system_prompt
        assert "Bahasa Indonesia" in client.system_prompt
        assert "tidak bahasa lain" in client.system_prompt

    def test_headers_correct(self):
        """Headers harus berisi Authorization Bearer + Content-Type"""
        client = ChatClient(api_key=TEST_ARK_API_KEY)
        headers = client._build_headers()

        assert headers["Authorization"] == f"Bearer {TEST_ARK_API_KEY}"
        assert headers["Content-Type"] == "application/json"


class TestBuildMessages:
    """Test konstruksi messages array"""

    def test_messages_with_system_prompt(self):
        """Messages harus diawali dengan system prompt"""
        client = ChatClient(api_key=TEST_ARK_API_KEY)
        messages = client._build_messages("Halo")

        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == client.system_prompt
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "Halo"

    def test_messages_with_history(self):
        """Messages harus menyertakan conversation history"""
        client = ChatClient(api_key=TEST_ARK_API_KEY)
        client.conversation_history = [
            {"role": "user", "content": "Pertanyaan 1"},
            {"role": "assistant", "content": "Jawaban 1"},
        ]

        messages = client._build_messages("Pertanyaan 2")

        # system + 2 history + 1 new = 4 messages
        assert len(messages) == 4
        assert messages[1]["content"] == "Pertanyaan 1"
        assert messages[2]["content"] == "Jawaban 1"
        assert messages[3]["content"] == "Pertanyaan 2"

    def test_messages_history_limit(self):
        """History dibatasi ke 10 pesan terakhir untuk efisiensi token"""
        client = ChatClient(api_key=TEST_ARK_API_KEY)

        # Tambahkan 30 pesan ke history
        for i in range(15):
            client.conversation_history.append({"role": "user", "content": f"P{i}"})
            client.conversation_history.append({"role": "assistant", "content": f"J{i}"})

        messages = client._build_messages("Pertanyaan baru")

        # system + 10 history + 1 new = 12 messages
        assert len(messages) == 12


class TestChatStreaming:
    """Test SSE streaming chat"""

    @pytest.mark.asyncio
    async def test_chat_stream_yields_tokens(self):
        """chat_stream harus yield token per token dari SSE response"""
        full_text = "Halo, apa kabar hari ini?"
        sse_lines = make_sse_chunks(full_text, chunk_size=5)

        # Mock httpx response dengan aiter_lines sebagai async generator
        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("chat_client.httpx.AsyncClient", return_value=mock_client):
            client = ChatClient(api_key=TEST_ARK_API_KEY)

            tokens = []
            async for token in client.chat_stream("Halo"):
                tokens.append(token)

            full_response = "".join(tokens)
            assert full_response == full_text

    @pytest.mark.asyncio
    async def test_chat_stream_saves_history(self):
        """Setelah streaming selesai, conversation history harus tersimpan"""
        full_text = "Baik, terima kasih."
        sse_lines = make_sse_chunks(full_text, chunk_size=5)

        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("chat_client.httpx.AsyncClient", return_value=mock_client):
            client = ChatClient(api_key=TEST_ARK_API_KEY)
            assert len(client.conversation_history) == 0

            async for _ in client.chat_stream("Apa kabar?"):
                pass

            # History harus berisi 2 entry: user + assistant
            assert len(client.conversation_history) == 2
            assert client.conversation_history[0]["role"] == "user"
            assert client.conversation_history[0]["content"] == "Apa kabar?"
            assert client.conversation_history[1]["role"] == "assistant"
            assert client.conversation_history[1]["content"] == full_text

    @pytest.mark.asyncio
    async def test_chat_non_streaming(self):
        """Method chat() (non-streaming) harus mengembalikan teks lengkap"""
        full_text = "Ini jawaban lengkap dari AI."
        sse_lines = make_sse_chunks(full_text, chunk_size=5)

        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("chat_client.httpx.AsyncClient", return_value=mock_client):
            client = ChatClient(api_key=TEST_ARK_API_KEY)
            result = await client.chat("Pertanyaan")

            assert result == full_text

    @pytest.mark.asyncio
    async def test_chat_stream_http_error(self):
        """HTTP error harus raise RuntimeError dengan pesan yang jelas"""
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json = MagicMock(return_value={
            "error": {"message": "Invalid API key"}
        })
        mock_response.text = "Unauthorized"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Simulasikan raise_for_status melempar HTTPStatusError
        error = httpx.HTTPStatusError("401", request=MagicMock(), response=mock_response)

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(side_effect=error)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("chat_client.httpx.AsyncClient", return_value=mock_client):
            client = ChatClient(api_key=TEST_ARK_API_KEY)

            with pytest.raises(RuntimeError, match="ModelArk API error"):
                async for _ in client.chat_stream("test"):
                    pass


class TestHistoryManagement:
    """Test conversation history"""

    def test_clear_history(self):
        """clear_history harus mengosongkan conversation history"""
        client = ChatClient(api_key=TEST_ARK_API_KEY)
        client.conversation_history = [
            {"role": "user", "content": "A"},
            {"role": "assistant", "content": "B"},
        ]

        client.clear_history()

        assert client.conversation_history == []

    @pytest.mark.asyncio
    async def test_history_limit_20(self):
        """History dibatasi ke 20 pesan terakhir"""
        full_text = "OK"
        sse_lines = make_sse_chunks(full_text, chunk_size=2)

        async def mock_aiter_lines():
            for line in sse_lines:
                yield line

        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_lines = mock_aiter_lines

        mock_stream_ctx = AsyncMock()
        mock_stream_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_stream_ctx.__aexit__ = AsyncMock(return_value=None)

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.stream = MagicMock(return_value=mock_stream_ctx)

        with patch("chat_client.httpx.AsyncClient", return_value=mock_client):
            client = ChatClient(api_key=TEST_ARK_API_KEY)

            # Simulasikan 12 percakapan (24 pesan)
            for i in range(12):
                async for _ in client.chat_stream(f"P{i}"):
                    pass

            # History harus dibatasi ke 20
            assert len(client.conversation_history) == 20


# ============================================
# Helper classes untuk mock async iterators
# ============================================

class AsyncIteratorMock:
    """Mock async iterator untuk httpx aiter_lines()"""

    def __init__(self, lines: list[str]):
        self.lines = list(lines)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self.lines):
            raise StopAsyncIteration
        line = self.lines[self._index]
        self._index += 1
        return line


class AsyncContextMock:
    """Mock async context manager untuk httpx stream()"""

    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        pass
