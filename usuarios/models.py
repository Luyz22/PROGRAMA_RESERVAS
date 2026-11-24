from django.conf import settings
from django.db import models


class Perfil(models.Model):
    """Datos extra de cada persona que usa el sistema."""

    class Tipo(models.TextChoices):
        ESTUDIANTE = "estudiante", "Estudiante"
        DOCENTE = "docente", "Docente"
        EXTERNO = "externo", "Externo"

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil"
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.EXTERNO)
    acepto_politica_en = models.DateTimeField(
        null=True, blank=True, help_text="Cuándo aceptó la política de datos (Ley 1581)."
    )

    def __str__(self):
        return f"{self.usuario.get_full_name() or self.usuario.username} ({self.get_tipo_display()})"
