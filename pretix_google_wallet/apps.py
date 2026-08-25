from django.utils.translation import gettext_lazy as _
from pretix.base.plugins import PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID, PluginConfig

from . import __version__


class PluginApp(PluginConfig):
    name = "pretix_google_wallet"
    verbose_name = _("Google Wallet")

    class PretixPluginMeta:
        name = _("Google Wallet")
        author = "Jan Pohanka"
        description = _("Add native Google Wallet event tickets to pretix orders.")
        category = "FEATURE"
        visible = True
        version = __version__
        compatibility = "pretix>=2026.7.0.dev0"
        level = PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID

    def ready(self):
        from . import signals  # noqa: F401
