"""Crea usuarios de prueba para desarrollar y probar el sistema.

Uso (con el venv activo):
    python manage.py crear_usuarios_prueba

Se puede ejecutar varias veces: si el usuario ya existe, lo deja activo,
verificado y con la contraseña de prueba. SOLO PARA DESARROLLO: no usar en producción.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from usuarios.models import DocenteAutorizado, Perfil

CLAVE_PRUEBA = "Reservas-2026"


def hace_anios(anios):
    hoy = timezone.localdate()
    try:
        return hoy.replace(year=hoy.year - anios)
    except ValueError:   # 29 de febrero
        return hoy.replace(year=hoy.year - anios, day=28)


def usuarios_de_prueba():
    # (correo, nombre, apellido, tipo de perfil o None si es administrador, fecha de nacimiento, responsable)
    return [
        ("prueba.estudiante@uniminuto.edu.co", "Estela", "Estudiante", Perfil.Tipo.ESTUDIANTE, date(2003, 4, 12), None),
        ("prueba.menor@uniminuto.edu.co", "Mateo", "Menor", Perfil.Tipo.ESTUDIANTE, hace_anios(16),
         ("Marta Menor (acudiente)", "52123456", "3001234567")),
        ("prueba.docente@uniminuto.edu.co", "Daniel", "Docente", Perfil.Tipo.DOCENTE, date(1985, 9, 3), None),
        ("prueba.admin@uniminuto.edu.co", "Ana", "Administradora", None, None, None),
    ]


class Command(BaseCommand):
    help = "Crea usuarios de prueba (estudiante, estudiante menor de edad, docente y administrador)."

    def handle(self, *args, **options):
        User = get_user_model()
        ahora = timezone.now()
        for correo, nombre, apellido, tipo, nacimiento, responsable in usuarios_de_prueba():
            usuario, creado = User.objects.get_or_create(
                username=correo,
                defaults={"email": correo, "first_name": nombre, "last_name": apellido},
            )
            usuario.set_password(CLAVE_PRUEBA)
            usuario.is_active = True
            usuario.is_staff = tipo is None
            usuario.is_superuser = tipo is None
            usuario.save()

            if tipo:
                if tipo == Perfil.Tipo.DOCENTE:
                    DocenteAutorizado.objects.get_or_create(correo=correo)
                responsable = responsable or ("", "", "")
                Perfil.objects.update_or_create(
                    usuario=usuario,
                    defaults={
                        "tipo": tipo,
                        "acepto_politica_en": ahora,
                        "correo_verificado_en": ahora,
                        "fecha_nacimiento": nacimiento,
                        "telefono": "3000000000",
                        "responsable_nombre": responsable[0],
                        "responsable_documento": responsable[1],
                        "responsable_telefono": responsable[2],
                    },
                )

            accion = "Creado" if creado else "Actualizado"
            self.stdout.write(f"{accion}: {correo}")

        self.stdout.write(self.style.SUCCESS(f"Listo. Contraseña de todos: {CLAVE_PRUEBA}"))
