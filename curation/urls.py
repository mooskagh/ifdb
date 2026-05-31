from django.urls import path

from . import views

urlpatterns = [
    path("", views.history_list, name="curation_history_list"),
    path(
        "discovery/",
        views.discovery_status,
        name="curation_discovery_status",
    ),
    path(
        "discovery/<int:status_id>/",
        views.discovery_detail,
        name="curation_discovery_detail",
    ),
    path("sources/", views.source_list, name="curation_source_list"),
    path(
        "sources/<int:source_id>/",
        views.source_detail,
        name="curation_source_detail",
    ),
    path(
        "sources/fetches/<int:fetch_id>/<str:kind>/",
        views.source_fetch_content,
        name="curation_source_fetch_content",
    ),
    path(
        "<int:history_id>/",
        views.history_detail,
        name="curation_history_detail",
    ),
    path(
        "<int:history_id>/edit/",
        views.history_edit,
        name="curation_history_edit",
    ),
]
