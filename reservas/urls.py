from django.urls import path

from . import views

app_name = "reservas"

urlpatterns = [
    path("espacio/<int:espacio_id>/", views.franjas, name="franjas"),
    path("espacio/<int:espacio_id>/datos/", views.datos, name="datos"),
    path("<int:reserva_id>/confirmacion/", views.confirmacion, name="confirmacion"),
    path("<int:reserva_id>/cancelar/", views.cancelar, name="cancelar"),
    path("mis-reservas/", views.mis_reservas, name="mis_reservas"),
]
