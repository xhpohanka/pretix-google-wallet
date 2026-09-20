__version__ = "1.0.0"

default_app_config = "pretix_google_wallet.apps.PluginApp"

from .apps import PluginApp  # noqa: E402

PretixPluginMeta = PluginApp.PretixPluginMeta
