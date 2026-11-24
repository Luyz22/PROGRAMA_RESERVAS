from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("ingresar/", views.IngresoView.as_view(), name="ingresar"),
    path("registro/", views.registro, name="registro"),
    path("salir/", LogoutView.as_view(), name="salir"),
]
