"""Prompt builder for Kira OpenArt generations."""

from __future__ import annotations

from pathlib import Path

DEFAULT_KIRA_STYLE = """blue/cyan tech aesthetic
anime realism
Home Assistant / workshop / smart home mood
dark hoodie, glasses, glowing headphones
cozy nerdy tech atmosphere
"""


class OpenArtPromptBuilder:
    """Build OpenArt prompts with Kira's fixed visual identity."""

    def __init__(self, style_path: Path) -> None:
        """Initialize the builder with a style prompt file."""
        self.style_path = style_path

    def build(self, prompt: str) -> str:
        """Combine the user prompt with Kira's fixed style."""
        style = self.load_style()
        return (
            f"{prompt.strip()}\n\n" "Kira fixed style:\n" f"{style.strip()}"
        ).strip()

    def load_style(self) -> str:
        """Load the Kira style prompt, creating the default file if needed."""
        if not self.style_path.exists():
            self.style_path.parent.mkdir(parents=True, exist_ok=True)
            self.style_path.write_text(DEFAULT_KIRA_STYLE, encoding="utf-8")
        return self.style_path.read_text(encoding="utf-8")
