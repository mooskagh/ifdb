from django.contrib.auth.decorators import user_passes_test
from django.urls import path

from . import views


def superuser_required(view):
    return user_passes_test(lambda user: user.is_active and user.is_superuser)(
        view
    )


urlpatterns = [
    path(
        "",
        superuser_required(views.history_list),
        name="curation_history_list",
    ),
    path(
        "discovery/",
        superuser_required(views.discovery_status),
        name="curation_discovery_status",
    ),
    path(
        "discovery/<int:status_id>/",
        superuser_required(views.discovery_detail),
        name="curation_discovery_detail",
    ),
    path(
        "models/",
        superuser_required(views.llm_models),
        name="curation_llm_models",
    ),
    path("tasks/", superuser_required(views.tasks), name="curation_tasks"),
    path(
        "trajectories/",
        superuser_required(views.llm_trajectories),
        name="curation_llm_trajectories",
    ),
    path(
        "trajectories/<int:trajectory_id>/",
        superuser_required(views.llm_trajectory_detail),
        name="curation_llm_trajectory_detail",
    ),
    path(
        "sources/",
        superuser_required(views.source_list),
        name="curation_source_list",
    ),
    path(
        "sources/<int:source_id>/",
        superuser_required(views.source_detail),
        name="curation_source_detail",
    ),
    path(
        "sources/<int:source_id>/fetch/",
        superuser_required(views.source_fetch_now),
        name="curation_source_fetch_now",
    ),
    path(
        "sources/fetches/<int:fetch_id>/<str:kind>/",
        superuser_required(views.source_fetch_content),
        name="curation_source_fetch_content",
    ),
    path(
        "<int:history_id>/sources/add/",
        superuser_required(views.history_source_add),
        name="curation_history_source_add",
    ),
    path(
        "<int:history_id>/sources/fetch/",
        superuser_required(views.history_sources_fetch_now),
        name="curation_history_sources_fetch_now",
    ),
    path(
        "<int:history_id>/sources/<int:source_id>/delete/",
        superuser_required(views.history_source_detach),
        name="curation_history_source_detach",
    ),
    path(
        "edits/<int:edit_id>/",
        superuser_required(views.edit_diff),
        name="curation_edit_diff",
    ),
    path(
        "<int:history_id>/",
        superuser_required(views.history_detail),
        name="curation_history_detail",
    ),
    path(
        "<int:history_id>/edit/",
        superuser_required(views.history_edit),
        name="curation_history_edit",
    ),
    path(
        "<int:history_id>/merge/",
        superuser_required(views.history_merge),
        name="curation_history_merge",
    ),
    path(
        "<int:history_id>/run-edit/",
        superuser_required(views.history_run_edit),
        name="curation_history_run_edit",
    ),
]
