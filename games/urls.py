from django.conf import settings
from django.urls import include, path, re_path
from django_registration.backends.activation.views import RegistrationView

from core.forms import RegistrationForm

from . import views

urlpatterns = [
    path("index/", views.index, name="index"),
    # Games
    path("game/add/", views.add_game, name="add_game"),
    path("game/edit/<int:game_id>/", views.edit_game, name="edit_game"),
    path("game/vote/", views.vote_game, name="vote_game"),
    path("game/store/", views.store_game, name="store_game"),
    path("game/comment/", views.comment_game, name="comment_game"),
    path("game/search/", views.search_game, name="search_game"),
    path("game/", views.list_games, name="list_games"),
    path("game/<int:game_id>/", views.show_game, name="show_game"),
    path(
        "game/interpreter/<int:gameurl_id>/store/",
        views.store_interpreter_params,
        name="store_interpreter_params",
    ),
    path(
        "game/interpreter/<int:gameurl_id>/",
        views.play_in_interpreter,
        name="play_in_interpreter",
    ),
    # Authors
    path("author/", views.list_authors, name="list_authors"),
    path("author/<int:author_id>/", views.show_author, name="show_author"),
    # API
    path("json/gameinfo/", views.json_gameinfo, name="json_gameinfo"),
    path("json/commentvote/", views.json_commentvote, name="json_commentvote"),
    path(
        "json/categorizeurl/",
        views.json_categorizeurl,
        name="json_categorizeurl",
    ),
    path("json/upload/", views.upload, name="upload"),
    path("json/import/", views.doImport, name="import"),
    path("json/search/", views.json_search, name="json_search"),
    path(
        "json/author-search/",
        views.json_author_search,
        name="json_author_search",
    ),
    path(
        "accounts/register/",
        RegistrationView.as_view(form_class=RegistrationForm),
        name="registration_register",
    ),
    re_path(
        r"^accounts/",
        include(
            "django_registration.backends.activation.urls"
            if settings.REQUIRE_ACCOUNT_ACTIVATION
            else "django_registration.backends.one_step.urls"
        ),
    ),
    re_path(r"^accounts/", include("django.contrib.auth.urls")),
]

if settings.DEBUG:
    import debug_toolbar

    urlpatterns = [
        re_path(r"^__debug__/", include(debug_toolbar.urls)),
    ] + urlpatterns
