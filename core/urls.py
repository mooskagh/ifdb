from django.urls import path

from . import snippets

urlpatterns = [
    path("json/snippet/", snippets.AsyncSnippet, name="async_snippet"),
    path(
        "json/snippet/pin/<int:id>/",
        snippets.PinSnippet,
        name="pin_snippet",
    ),
    path(
        "json/snippet/hide/<int:id>/",
        snippets.HideSnippet,
        name="hide_snippet",
    ),
    path(
        "json/snippet/forget/<int:id>/",
        snippets.ForgetSnippet,
        name="forget_snippet",
    ),
]
