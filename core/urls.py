from django.urls import re_path

from . import snippets

urlpatterns = [
    re_path(r"^json/snippet/$", snippets.AsyncSnippet, name="async_snippet"),
    re_path(
        r"^json/snippet/pin/(?P<id>[0-9]+)",
        snippets.PinSnippet,
        name="pin_snippet",
    ),
    re_path(
        r"^json/snippet/hide/(?P<id>[0-9]+)",
        snippets.HideSnippet,
        name="hide_snippet",
    ),
    re_path(
        r"^json/snippet/forget/(?P<id>[0-9]+)",
        snippets.ForgetSnippet,
        name="forget_snippet",
    ),
]
