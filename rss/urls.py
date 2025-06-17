from django.urls import path

from . import views

urlpatterns = [
    path("comments/", views.comments),
    path("comments/<str:jam_id>/", views.comments),
]
