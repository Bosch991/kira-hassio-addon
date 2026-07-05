"""Prompt loading helpers kept as a compatibility boundary."""

from __future__ import annotations

from kira.core.config import Settings
from kira.personality.personality import PersonalityProfile
from kira.personality.prompt_builder import PromptBuilder

DEFAULT_SYSTEM_PROMPT = ""


def load_system_prompt(settings: Settings) -> str:
    """Load Kira's composed personality prompt."""
    profile = PersonalityProfile.load(settings.prompts_dir)
    return PromptBuilder(profile).build()
