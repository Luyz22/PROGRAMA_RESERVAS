from django.db import models


class Espacio(models.Model):
    class Tipo(models.TextChoices):
        CANCHA = "cancha", "Cancha"
        GIMNASIO = "gimnasio", "Gimnasio"
        OTRO = "otro", "Otro"

    nombre = models.CharField(max_length=100)
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.CANCHA)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    def __str__(self):
        return self.nombre