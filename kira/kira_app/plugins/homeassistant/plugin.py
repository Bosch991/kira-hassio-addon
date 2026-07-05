"""Home Assistant plugin adapter."""

from kira.plugins.base_plugin import BasePlugin, PluginHealth


class Plugin(BasePlugin):
    """Expose existing Home Assistant services as a plugin."""

    def healthcheck(self) -> PluginHealth:
        """Return Home Assistant plugin health."""
        configured = self.context.homeassistant.is_configured
        return PluginHealth(
            ok=True,
            message="configured" if configured else "not configured",
            details={"configured": configured},
        )
