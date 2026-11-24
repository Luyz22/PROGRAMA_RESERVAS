from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="espacios:lista"), name="inicio"),
    path("admin/", admin.site.urls),
    path("cuenta/", include("usuarios.urls")),
    path("espacios/", include("espacios.urls")),
    path("reservas/", include("reservas.urls")),
    path("panel/", include("panel.urls")),
]
