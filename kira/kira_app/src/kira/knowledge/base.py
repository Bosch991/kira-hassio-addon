"""Markdown-backed categorized knowledge base."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class KnowledgeDocument:
    """A single markdown knowledge document."""

    category: str
    path: Path
    content: str


class KnowledgeBase:
    """Load categorized project knowledge from local markdown files."""

    def __init__(self, knowledge_dir: Path) -> None:
        """Initialize the knowledge base with its markdown directory."""
        self.knowledge_dir = knowledge_dir
        self.documents: list[KnowledgeDocument] = []

    def reload(self) -> None:
        """Reload all markdown knowledge documents from disk."""
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)
        documents: list[KnowledgeDocument] = []
        for path in sorted(self.knowledge_dir.glob("*.md")):
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            documents.append(
                KnowledgeDocument(
                    category=self._category_from_content(content=content, path=path),
                    path=path,
                    content=content,
                )
            )
        self.documents = documents

    def list_categories(self) -> list[str]:
        """Return all loaded knowledge categories."""
        return [document.category for document in self.documents]

    def build_context(self) -> str:
        """Build a compact context block for the chat model."""
        if not self.documents:
            return ""

        sections = []
        for document in self.documents:
            sections.append(f"## {document.category}\n{document.content}")
        return "\n\n".join(sections)

    def _category_from_content(self, *, content: str, path: Path) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line.removeprefix("# ").strip()
        return path.stem.replace("_", " ").replace("-", " ").title()
