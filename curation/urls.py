from django.urls import path

from . import views

urlpatterns = [
    path("", views.ticket_list, name="curation_ticket_list"),
    path(
        "<int:ticket_id>/",
        views.ticket_detail,
        name="curation_ticket_detail",
    ),
    path(
        "<int:ticket_id>/edit/",
        views.ticket_edit,
        name="curation_ticket_edit",
    ),
]
