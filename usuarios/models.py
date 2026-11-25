from django.conf import settings
from django.db import models
from django.utils import timezone

MAYORIA_DE_EDAD = 18


def calcular_edad(fecha_nacimiento, hoy=None):
    """Años cumplidos a la fecha de hoy."""
    hoy = hoy or timezone.localdate()
    cumplio_este_anio = (hoy.month, hoy.day) >= (fecha_nacimiento.month, fecha_nacimiento.day)
    return hoy.year - fecha_nacimiento.year - (0 if cumplio_este_anio else 1)


class Perfil(models.Model):
    """Datos extra de cada persona que usa el sistema.

    El administrador no se guarda aquí: es quien tiene is_staff=True.
    """

    class Tipo(models.TextChoices):
        ESTUDIANTE = "estudiante", "Estudiante"
        DOCENTE = "docente", "Docente"

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil"
    )
    tipo = models.CharField(max_length=20, choices=Tipo.choices, default=Tipo.ESTUDIANTE)
    acepto_politica_en = models.DateTimeField(
        null=True, blank=True, help_text="Cuándo aceptó la política de datos (Ley 1581)."
    )
    correo_verificado_en = models.DateTimeField(
        null=True, blank=True, help_text="Cuándo abrió el enlace de verificación de su correo."
    )
    fecha_nacimiento = models.DateField(null=True, blank=True)
    telefono = models.CharField(max_length=20, blank=True)

    # Adulto responsable: obligatorio solo si la persona es menor de edad.
    responsable_nombre = models.CharField("nombre del adulto responsable", max_length=150, blank=True)
    responsable_documento = models.CharField("documento del adulto responsable", max_length=30, blank=True)
    responsable_telefono = models.CharField("teléfono del adulto responsable", max_length=20, blank=True)

    def __str__(self):
        return f"{self.usuario.get_full_name() or self.usuario.username} ({self.get_tipo_display()})"

    @property
    def edad(self):
        if self.fecha_nacimiento is None:
            return None
        return calcular_edad(self.fecha_nacimiento)

    @property
    def es_menor(self):
        return self.edad is not None and self.edad < MAYORIA_DE_EDAD


class DocenteAutorizado(models.Model):
    """Correos institucionales que reciben el rol docente al registrarse."""

    correo = models.EmailField(unique=True)
    agregado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    agregado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["correo"]
        verbose_name = "docente autorizado"
        verbose_name_plural = "docentes autorizados"

    def save(self, *args, **kwargs):
        self.correo = self.correo.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.correo
