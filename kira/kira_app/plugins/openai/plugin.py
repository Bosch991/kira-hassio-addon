"""OpenAI plugin adapter."""

from kira.plugins.base_plugin import BasePlugin, PluginHealth


class Plugin(BasePlugin):
    """Expose existing OpenAI client settings as a plugin."""

    def healthcheck(self) -> PluginHealth:
        """Return OpenAI plugin health."""
        configured = bool(self.context.settings.openai_api_key)
        return PluginHealth(
            ok=True,
            message="configured" if configured else "fallback mode",
            details={"model": self.context.settings.openai_model},
        )
