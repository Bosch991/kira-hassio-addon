"""Voice plugin adapter."""

from kira.plugins.base_plugin import BasePlugin, PluginHealth


class Plugin(BasePlugin):
    """Expose existing voice and audio services as a plugin."""

    def healthcheck(self) -> PluginHealth:
        """Return voice plugin health."""
        return PluginHealth(
            ok=True,
            message=(
                "configured" if self.context.voice.is_configured else "not configured"
            ),
            details={
                "voice_configured": self.context.voice.is_configured,
                "stt_provider": self.context.settings.stt_provider,
            },
        )
