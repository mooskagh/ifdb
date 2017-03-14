from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^index/$', views.index, name='index'),
    url(r'^add/', views.add_game, name='add_game'),
    url(r'^store_game/', views.store_game, name='store_game'),
    url(r'^json/authors/', views.authors, name='authors'),
    url(r'^json/tags/', views.tags, name='tags'),
]
