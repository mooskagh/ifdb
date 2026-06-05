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
    path("models/", views.llm_models, name="curation_llm_models"),
    path("tasks/", views.tasks, name="curation_tasks"),
    path(
        "trajectories/",
        views.llm_trajectories,
        name="curation_llm_trajectories",
    ),
    path(
        "trajectories/<int:trajectory_id>/",
        views.llm_trajectory_detail,
        name="curation_llm_trajectory_detail",
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
        "<int:history_id>/sources/add/",
        views.history_source_add,
        name="curation_history_source_add",
    ),
    path(
        "<int:history_id>/sources/<int:source_id>/delete/",
        views.history_source_detach,
        name="curation_history_source_detach",
    ),
    path("edits/<int:edit_id>/", views.edit_diff, name="curation_edit_diff"),
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
