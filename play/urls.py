from django.urls import path

from . import views

urlpatterns = [
    path("telemetry/", views.telemetry, name="play_telemetry"),
]
