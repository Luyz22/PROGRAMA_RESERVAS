from django.core.exceptions import ValidationError
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
    # Cuántas personas pueden usar el espacio en una reserva.
    # Vacío significa "sin límite" por ese lado.
    aforo_minimo = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Mínimo de personas por reserva. Vacío: sin mínimo."
    )
    aforo_maximo = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Máximo de personas por reserva. Vacío: sin máximo."
    )

    def __str__(self):
        return self.nombre

    def clean(self):
        super().clean()
        if self.aforo_minimo == 0:
            raise ValidationError({"aforo_minimo": "El mínimo debe ser al menos 1."})
        if self.aforo_maximo == 0:
            raise ValidationError({"aforo_maximo": "El máximo debe ser al menos 1."})
        if (
            self.aforo_minimo is not None
            and self.aforo_maximo is not None
            and self.aforo_minimo > self.aforo_maximo
        ):
            raise ValidationError({"aforo_maximo": "El máximo no puede ser menor que el mínimo."})

    @property
    def aforo_texto(self):
        """Ej.: '10 a 12 personas', 'hasta 12 personas', 'sin límite'."""
        minimo, maximo = self.aforo_minimo, self.aforo_maximo
        if minimo and maximo:
            return f"{minimo} a {maximo} personas" if minimo != maximo else f"{minimo} personas"
        if maximo:
            return f"hasta {maximo} personas"
        if minimo:
            return f"mínimo {minimo} personas"
        return "sin límite"
