from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path, re_path

from contest.views import show_competition

urlpatterns = [
    path("rss/", include("rss.urls"), name="rss"),
    path("adminz/", admin.site.urls, name="admin"),
    path(
        "2019/<path:doc>",
        show_competition,
        {"slug": "kontigr-2019"},
        name="show_competition",
    ),
    path(
        "2020/<path:doc>",
        show_competition,
        {"slug": "kontigr-2020"},
        name="show_competition",
    ),
    path(
        "2021/<path:doc>",
        show_competition,
        {"slug": "kontigr-2021"},
        name="show_competition",
    ),
    re_path(r"^", include("games.urls"), name="games"),
    re_path(r"^", include("moder.urls"), name="moder"),
    path(
        "<path:doc>",
        show_competition,
        {"slug": "kontigr-2022"},
        name="show_competition",
    ),
]

if settings.DEBUG:
    urlpatterns = (
        static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
        + urlpatterns
    )
