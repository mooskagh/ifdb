from django.urls import path

from . import views

urlpatterns = [
    path("docs/", views.api_docs, name="api_docs"),
    path("openapi.json", views.openapi_spec, name="api_openapi"),
    path("v1/games/", views.game_create, name="api_game_create"),
    path(
        "v1/games/<int:game_id>/",
        views.game_detail_router,
        name="api_game_detail",
    ),
    path(
        "v1/games/<int:game_id>/publish/",
        views.game_publish,
        name="api_game_publish",
    ),
    path(
        "v1/games/<int:game_id>/unpublish/",
        views.game_unpublish,
        name="api_game_unpublish",
    ),
    path("v1/files/", views.file_upload, name="api_file_upload"),
    path(
        "v1/games/<int:game_id>/files/",
        views.file_upload,
        name="api_game_file_upload",
    ),
]
