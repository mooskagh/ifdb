from django.conf.urls import url, include
from django.conf import settings
from . import views

urlpatterns = [
    url(r'^index/$', views.index, name='index'),
    # TODO Make it game/add
    url(r'^gameadd/', views.add_game, name='add_game'),
    url(r'^game/edit/(?P<game_id>\d+)/', views.edit_game, name='edit_game'),
    url(r'^game/vote/', views.vote_game, name='vote_game'),
    url(r'^game/store/', views.store_game, name='store_game'),
    url(r'^game/comment/', views.comment_game, name='comment_game'),
    url(r'^game/$', views.list_games, name='list_games'),
    url(r'^game/(?P<game_id>\d+)/', views.show_game, name='show_game'),
    url(r'^json/gameinfo/', views.json_gameinfo, name='json_gameinfo'),
    url(r'^json/upload/', views.upload, name='upload'),
    url(r'^json/import/', views.doImport, name='import'),
    url(r'^json/search/', views.json_search, name='json_search'),
    url(r'^accounts/',
        include('registration.backends.hmac.urls'
                if settings.REQUIRE_ACCOUNT_ACTIVATION else
                'registration.backends.simple.urls')),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        url(r'^__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns