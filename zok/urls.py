from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from contest.views import show_competition

urlpatterns = [
    path("rss/", include("rss.urls"), name="rss"),
    path("adminz/", admin.site.urls, name="admin"),
    re_path(r"^", include("games.urls"), name="games"),
    re_path(r"^", include("moder.urls"), name="moder"),
    re_path(
        r"^2025/(?P<doc>.*?)/?$",
        show_competition,
        {"slug": "zok-2025"},
        name="show_competition",
    ),
    re_path(
        r"^(?P<doc>.*?)/?$",
        show_competition,
        {"slug": "zok-2026"},
        name="show_competition",
    ),
]

if settings.DEBUG:
    urlpatterns = (
        static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
        + urlpatterns
    )
