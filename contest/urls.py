from django.urls import path, re_path

from . import editor, views

urlpatterns = [
    path("", views.list_competitions, name="list_competitions"),
    path("showvotes/<int:id>/", views.list_votes, name="view_compvotes"),
    path(
        "edit/<int:id>/",
        editor.edit_competition,
        name="edit_competition",
    ),
    path("editlist/<int:id>/", editor.edit_complist, name="edit_complist"),
    path("editdoc/<int:id>/", editor.edit_compdoc, name="edit_compdoc"),
    re_path(
        r"^(?P<slug>[-\w\d]+)/(?P<doc>.*)$",
        views.show_competition,
        name="show_competition",
    ),
]
