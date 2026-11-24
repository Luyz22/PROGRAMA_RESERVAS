from django.urls import path

from . import views

app_name = "reservas"

urlpatterns = [
    path("espacio/<int:espacio_id>/", views.franjas, name="franjas"),
    path("espacio/<int:espacio_id>/reservar/", views.reservar, name="reservar"),
    path("<int:reserva_id>/cancelar/", views.cancelar, name="cancelar"),
    path("panel/", views.panel, name="panel"),
    path("panel/bloquear/", views.bloquear, name="bloquear"),
    path("panel/bloqueo/<int:bloqueo_id>/quitar/", views.quitar_bloqueo, name="quitar_bloqueo"),
]
