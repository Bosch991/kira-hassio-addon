"""OpenArt plugin adapter."""

from kira.plugins.base_plugin import BasePlugin, PluginHealth


class Plugin(BasePlugin):
    """Expose OpenArt image generation as a plugin."""

    def healthcheck(self) -> PluginHealth:
        """Return OpenArt plugin health."""
        missing = self.context.openart.kira_config.missing_ids
        configured = self.context.openart.is_configured and not missing
        message = "configured" if configured else "missing configuration"
        return PluginHealth(
            ok=True,
            message=message,
            details={
                "api_key_configured": self.context.openart.is_configured,
                "missing": missing,
            },
        )
