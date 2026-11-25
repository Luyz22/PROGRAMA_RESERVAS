from django.contrib import admin

from .models import DocenteAutorizado, Perfil


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("usuario", "tipo", "fecha_nacimiento", "acepto_politica_en", "correo_verificado_en")
    list_filter = ("tipo",)
    search_fields = ("usuario__username", "usuario__email", "usuario__first_name", "usuario__last_name")


@admin.register(DocenteAutorizado)
class DocenteAutorizadoAdmin(admin.ModelAdmin):
    list_display = ("correo", "agregado_por", "agregado_en")
    search_fields = ("correo",)
