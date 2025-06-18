from django.urls import path

from moder.actions.tools import HandleAction

urlpatterns = [
    path("json/action/", HandleAction, name="handle_action"),
]
