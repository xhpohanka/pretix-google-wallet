from django.urls import path

from .views import (
    GoogleWalletSaveAllView,
    GoogleWalletSaveView,
    GoogleWalletSettingsView,
    GoogleWalletSubeventHeroView,
)

event_patterns = [
    path(
        "google-wallet/<str:order>/<str:secret>/all/",
        GoogleWalletSaveAllView.as_view(),
        name="save_all",
    ),
    path(
        "google-wallet/<str:order>/<str:secret>/<int:position>/",
        GoogleWalletSaveView.as_view(),
        name="save",
    ),
]

urlpatterns = [
    path(
        "control/event/<str:organizer>/<str:event>/google-wallet/hero/",
        GoogleWalletSubeventHeroView.as_view(),
        name="subevent_hero",
    ),
    path(
        "control/organizer/<str:organizer>/google-wallet/",
        GoogleWalletSettingsView.as_view(),
        name="settings",
    ),
]
