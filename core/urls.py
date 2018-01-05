from django.conf.urls import url
from . import views, snippets

urlpatterns = [
    url(r'^api/v0/fetchpackage$', views.fetchpackage, name='fetchpackage'),
    url(r'^api/v0/logtime$', views.logtime, name='logtime'),
    url(r'^json/snippet/$', snippets.AsyncSnippet, name='async_snippet'),
    url(r'^json/snippet/pin/(?P<id>[0-9]+)',
        snippets.PinSnippet,
        name='pin_snippet'),
    url(r'^json/snippet/hide/(?P<id>[0-9]+)',
        snippets.HideSnippet,
        name='hide_snippet'),
    url(r'^json/snippet/forget/(?P<id>[0-9]+)',
        snippets.ForgetSnippet,
        name='forget_snippet'),
    url(r'^docs/(?P<slug>[-\w]+)', views.showdoc, name='showdoc'),
]
