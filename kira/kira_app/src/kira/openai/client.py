"""OpenAI API client with local fallback support."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from kira.memory.conversation import ConversationMessage


class OpenAIChatStatus(StrEnum):
    """Possible outcomes of an OpenAI chat request."""

    SUCCESS = "success"
    MISSING_API_KEY = "missing_api_key"
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMITED = "rate_limited"
    NETWORK_ERROR = "network_error"
    API_ERROR = "api_error"


@dataclass(frozen=True, slots=True)
class OpenAIChatResult:
    """Result returned by the OpenAI client."""

    status: OpenAIChatStatus
    content: str
    error: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class OpenAIClient:
    """Small boundary around the OpenAI Responses API."""

    def __init__(self, api_key: str | None, model: str) -> None:
        """Initialize the client with credentials and model selection."""
        self.api_key = api_key
        self.model = model
        self.logger = logging.getLogger(__name__)

    @property
    def is_configured(self) -> bool:
        """Return whether an OpenAI API key is available."""
        return bool(self.api_key)

    def chat(
        self,
        *,
        system_prompt: str,
        memory_context: str,
        knowledge_context: str,
        conversation: list[ConversationMessage],
    ) -> OpenAIChatResult:
        """Create a chat response, returning structured failure states."""
        if not self.api_key:
            return OpenAIChatResult(
                status=OpenAIChatStatus.MISSING_API_KEY,
                content="",
                error="OPENAI_API_KEY is not configured.",
            )

        try:
            from openai import (  # type: ignore[import-not-found]
                APIConnectionError,
                APIError,
                AuthenticationError,
                OpenAI,
                RateLimitError,
            )
        except ImportError as exc:
            self.logger.warning("OpenAI SDK is not installed: %s", exc)
            return OpenAIChatResult(
                status=OpenAIChatStatus.API_ERROR,
                content="",
                error="OpenAI SDK is not installed.",
            )

        try:
            client = OpenAI(api_key=self.api_key)
            response = client.responses.create(
                model=self.model,
                input=self._build_input(
                    system_prompt=system_prompt,
                    memory_context=memory_context,
                    knowledge_context=knowledge_context,
                    conversation=conversation,
                ),
            )
            return OpenAIChatResult(
                status=OpenAIChatStatus.SUCCESS,
                content=response.output_text.strip(),
                input_tokens=self._usage_value(response, "input_tokens"),
                output_tokens=self._usage_value(response, "output_tokens"),
                total_tokens=self._usage_value(response, "total_tokens"),
            )
        except AuthenticationError as exc:
            self.logger.warning("OpenAI authentication failed: %s", exc)
            return OpenAIChatResult(
                status=OpenAIChatStatus.AUTHENTICATION_ERROR,
                content="",
                error="OpenAI API key was rejected.",
            )
        except RateLimitError as exc:
            self.logger.warning("OpenAI rate limit reached: %s", exc)
            return OpenAIChatResult(
                status=OpenAIChatStatus.RATE_LIMITED,
                content="",
                error="OpenAI rate limit reached.",
            )
        except APIConnectionError as exc:
            self.logger.warning("OpenAI network error: %s", exc)
            return OpenAIChatResult(
                status=OpenAIChatStatus.NETWORK_ERROR,
                content="",
                error="OpenAI network error.",
            )
        except APIError as exc:
            self.logger.warning("OpenAI API error: %s", exc)
            return OpenAIChatResult(
                status=OpenAIChatStatus.API_ERROR,
                content="",
                error="OpenAI API error.",
            )

    def _build_input(
        self,
        *,
        system_prompt: str,
        memory_context: str,
        knowledge_context: str,
        conversation: list[ConversationMessage],
    ) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": self._build_system_content(
                    system_prompt=system_prompt,
                    memory_context=memory_context,
                    knowledge_context=knowledge_context,
                ),
            }
        ]
        messages.extend(
            {"role": message.role, "content": message.content}
            for message in conversation
        )
        return messages

    def _build_system_content(
        self,
        *,
        system_prompt: str,
        memory_context: str,
        knowledge_context: str,
    ) -> str:
        sections = [system_prompt]
        if memory_context:
            sections.append(f"Lokale Erinnerungen:\n{memory_context}")
        if knowledge_context:
            sections.append(f"Lokales Projektwissen:\n{knowledge_context}")
        return "\n\n".join(sections)

    def _usage_value(self, response: object, name: str) -> int | None:
        usage = getattr(response, "usage", None)
        value = getattr(usage, name, None)
        return value if isinstance(value, int) else None
