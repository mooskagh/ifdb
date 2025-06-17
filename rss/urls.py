from django.urls import path

from . import views

urlpatterns = [
    path(r"comments/", views.comments),
    path(r"comments/<str:jam_id>", views.comments),
]
