from django.contrib import admin

from .models import Bloqueo, Reserva


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ("espacio", "fecha", "hora_inicio", "usuario", "estado", "creada_en")
    list_filter = ("estado", "espacio", "fecha")
    search_fields = ("usuario__username", "usuario__email")
    date_hierarchy = "fecha"


@admin.register(Bloqueo)
class BloqueoAdmin(admin.ModelAdmin):
    list_display = ("espacio", "fecha", "hora_inicio", "motivo", "creado_por")
    list_filter = ("espacio", "fecha")
