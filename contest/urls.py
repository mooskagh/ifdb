from django.conf.urls import url
from . import views
from . import editor

urlpatterns = [
    url(r'^$', views.list_competitions, name='list_competitions'),
    url(r'^edit/(?P<id>\d+)/$',
        editor.edit_competition,
        name='edit_competition'),
    url(r'^editlist/(?P<id>\d+)/$', editor.edit_complist,
        name='edit_complist'),
    url(r'^editdoc/(?P<id>\d+)/$', editor.edit_compdoc, name='edit_compdoc'),
    url(r'^(?P<slug>[-\w\d]+)/(?P<doc>.*)$',
        views.show_competition,
        name='show_competition'),
]
