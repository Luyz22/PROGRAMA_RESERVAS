"""Crea usuarios de prueba para desarrollar y probar el sistema.

Uso (con el venv activo):
    python manage.py crear_usuarios_prueba

Se puede ejecutar varias veces: si el usuario ya existe, solo le
restablece la contraseña. SOLO PARA DESARROLLO: no usar en producción.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from usuarios.models import Perfil

CLAVE_PRUEBA = "Reservas-2026"

USUARIOS = [
    # (correo, nombre, apellido, tipo de perfil o None, es administrador)
    ("estudiante@prueba.test", "Estela", "Estudiante", Perfil.Tipo.ESTUDIANTE, False),
    ("docente@prueba.test", "Daniel", "Docente", Perfil.Tipo.DOCENTE, False),
    ("externo@prueba.test", "Ximena", "Externa", Perfil.Tipo.EXTERNO, False),
    ("admin@prueba.test", "Ana", "Administradora", None, True),
]


class Command(BaseCommand):
    help = "Crea usuarios de prueba (estudiante, docente, externo y administrador)."

    def handle(self, *args, **options):
        User = get_user_model()
        for correo, nombre, apellido, tipo, es_admin in USUARIOS:
            usuario, creado = User.objects.get_or_create(
                username=correo,
                defaults={"email": correo, "first_name": nombre, "last_name": apellido},
            )
            usuario.set_password(CLAVE_PRUEBA)
            usuario.is_staff = es_admin
            usuario.is_superuser = es_admin
            usuario.save()

            if tipo:
                Perfil.objects.update_or_create(
                    usuario=usuario,
                    defaults={"tipo": tipo, "acepto_politica_en": timezone.now()},
                )

            accion = "Creado" if creado else "Actualizado"
            self.stdout.write(f"{accion}: {correo}")

        self.stdout.write(self.style.SUCCESS(f"Listo. Contraseña de todos: {CLAVE_PRUEBA}"))
