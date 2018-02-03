from django.conf.urls import url
from . import views

urlpatterns = [
    url(r'^$', views.list_competitions, name='list_competitions'),
    url(r'^(?P<slug>[-\w\d]+)/(?P<doc>.*)$',
        views.show_competition,
        name='show_competition'),
]
