from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^index/$', views.index, name='index'),
    url(r'^game/add/', views.add_game, name='add_game'),
    url(r'^game/store/', views.store_game, name='store_game'),
    url(r'^game/(?P<game_id>\d+)/', views.show_game, name='show_game'),
    url(r'^json/authors/', views.authors, name='authors'),
    url(r'^json/tags/', views.tags, name='tags'),
    url(r'^json/linktypes/', views.linktypes, name='linktypes'),
    url(r'^json/upload/', views.upload, name='upload'),
    url(r'^json/import/', views.doImport, name='import'),
]
