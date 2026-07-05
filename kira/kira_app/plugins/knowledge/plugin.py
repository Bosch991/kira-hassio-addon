"""Knowledge plugin adapter."""

from kira.plugins.base_plugin import BasePlugin, PluginHealth


class Plugin(BasePlugin):
    """Expose existing Markdown knowledge base as a plugin."""

    def healthcheck(self) -> PluginHealth:
        """Return knowledge plugin health."""
        return PluginHealth(
            ok=True,
            message="ready",
            details={"documents": len(self.context.knowledge.documents)},
        )
