"""Memory plugin adapter."""

from kira.plugins.base_plugin import BasePlugin, PluginHealth


class Plugin(BasePlugin):
    """Expose existing memory stores as a plugin."""

    def healthcheck(self) -> PluginHealth:
        """Return memory plugin health."""
        notes = self.context.memory.list_items(kind="conversation_note")
        return PluginHealth(
            ok=True,
            message="ready",
            details={
                "notes": len(notes),
                "conversation_items": self.context.conversation.count(),
            },
        )
