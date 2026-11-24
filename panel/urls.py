from django.urls import path

from . import views

app_name = "panel"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("bloquear/", views.bloquear, name="bloquear"),
    path("bloqueo/<int:bloqueo_id>/quitar/", views.quitar_bloqueo, name="quitar_bloqueo"),
    path("espacios/", views.espacios, name="espacios"),
    path("espacios/nuevo/", views.espacio_form, name="espacio_nuevo"),
    path("espacios/<int:espacio_id>/", views.espacio_form, name="espacio_editar"),
    path("reservas/", views.reservas, name="reservas"),
    path("usuarios/", views.usuarios, name="usuarios"),
    path("usuarios/nuevo/", views.usuario_form, name="usuario_nuevo"),
    path("usuarios/<int:usuario_id>/", views.usuario_form, name="usuario_editar"),
]
