from django.conf.urls import include, url
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from contest.views import show_competition

urlpatterns = [
    url(r'^adminz/', admin.site.urls, name='admin'),
    url(r'^', include('games.urls'), name='games'),
    url(r'^', include('moder.urls'), name='moder'),
    url(
        r'^(?P<doc>.*)$',
        show_competition,
        {'slug': 'kontigr-2019'},
        name='show_competition',
    ),
    url(r'^rss/', include('rss.urls'), name='rss'),
]

if settings.DEBUG:
    urlpatterns = static(settings.MEDIA_URL,
                         document_root=settings.MEDIA_ROOT) + urlpatterns
