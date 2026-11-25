from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("ingresar/", views.IngresoView.as_view(), name="ingresar"),
    path("registro/", views.registro, name="registro"),
    path("registro/enviado/", views.registro_enviado, name="registro_enviado"),
    path("activar/<str:token>/", views.activar, name="activar"),
    path("activar-reenviar/", views.reenviar, name="reenviar"),
    path("salir/", LogoutView.as_view(), name="salir"),
]
