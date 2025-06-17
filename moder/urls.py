from django.conf.urls import url

from moder.actions.tools import HandleAction

urlpatterns = [
    url(r"^json/action/$", HandleAction, name="handle_action"),
]
