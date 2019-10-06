from . import views
from django.urls import path

urlpatterns = [
    path(r'comments/', views.comments),
    path(r'comments/<str:jam_id>', views.comments),
]
