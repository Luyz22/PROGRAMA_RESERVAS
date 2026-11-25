from django.conf import settings
from django.db import models
from django.db.models import Q

from espacios.models import Espacio


class Reserva(models.Model):
    class Estado(models.TextChoices):
        CONFIRMADA = "confirmada", "Confirmada"
        CANCELADA = "cancelada", "Cancelada"

    class Deporte(models.TextChoices):
        MICROFUTBOL = "microfutbol", "Fútbol (microfútbol)"
        BALONCESTO = "baloncesto", "Baloncesto"
        VOLEIBOL = "voleibol", "Voleibol"

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reservas"
    )
    espacio = models.ForeignKey(
        Espacio, on_delete=models.PROTECT, related_name="reservas"
    )
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.CONFIRMADA
    )
    creada_en = models.DateTimeField(auto_now_add=True)

    # Datos que se piden al reservar. Las reservas anteriores a este formulario
    # los tienen vacíos.
    deporte = models.CharField(max_length=20, choices=Deporte.choices, blank=True)
    participantes = models.PositiveSmallIntegerField(null=True, blank=True)
    arl_nombre = models.CharField("ARL", max_length=100, blank=True)
    arl_confirmada = models.BooleanField(
        "todos los participantes están afiliados a ARL", default=False
    )
    recibe_nombre = models.CharField("quién recibe el espacio", max_length=150, blank=True)
    recibe_correo = models.EmailField("correo de quien recibe el espacio", blank=True)

    class Meta:
        ordering = ["fecha", "hora_inicio"]
        constraints = [
            models.UniqueConstraint(
                fields=["espacio", "fecha", "hora_inicio"],
                condition=Q(estado="confirmada"),
                name="una_reserva_confirmada_por_franja",
            )
        ]

    def __str__(self):
        return f"{self.espacio} · {self.fecha} {self.hora_inicio:%H:%M} ({self.estado})"


class Bloqueo(models.Model):
    espacio = models.ForeignKey(
        Espacio, on_delete=models.CASCADE, related_name="bloqueos"
    )
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    motivo = models.CharField(max_length=200, default="Mantenimiento")
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["fecha", "hora_inicio"]
        constraints = [
            models.UniqueConstraint(
                fields=["espacio", "fecha", "hora_inicio"],
                name="un_bloqueo_por_franja",
            )
        ]

    def __str__(self):
        return f"Bloqueo {self.espacio} · {self.fecha} {self.hora_inicio:%H:%M}"