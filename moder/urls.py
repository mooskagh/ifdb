from django.conf.urls import url
from . import actions

urlpatterns = [
    url(r'^json/action/$', actions.HandleAction, name='handle_action'),
]
