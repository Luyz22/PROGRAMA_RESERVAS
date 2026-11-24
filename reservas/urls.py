from django.urls import path

from . import views

app_name = "reservas"

urlpatterns = [
    path("espacio/<int:espacio_id>/", views.franjas, name="franjas"),
    path("espacio/<int:espacio_id>/reservar/", views.reservar, name="reservar"),
]
