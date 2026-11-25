"""Reglas de las cuentas de usuario: dominio institucional, verificación por
correo y lista de docentes autorizados."""

import csv
import io
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import DocenteAutorizado, Perfil

User = get_user_model()

SAL_ACTIVACION = "usuarios.activar-cuenta"


# ---------------------------------------------------------------------------
# Correo institucional y rol
# ---------------------------------------------------------------------------

def dominio_institucional():
    return settings.DOMINIO_INSTITUCIONAL.lower()


def es_correo_institucional(correo):
    return correo.strip().lower().endswith("@" + dominio_institucional())


def validar_correo_institucional(correo):
    if not es_correo_institucional(correo):
        raise ValidationError(f"Usa tu correo institucional @{dominio_institucional()}.")


def tipo_para_correo(correo):
    """Docente si el correo está en la lista de docentes autorizados; si no, estudiante."""
    if DocenteAutorizado.objects.filter(correo__iexact=correo.strip()).exists():
        return Perfil.Tipo.DOCENTE
    return Perfil.Tipo.ESTUDIANTE


# ---------------------------------------------------------------------------
# Registro y verificación por correo
# ---------------------------------------------------------------------------

@transaction.atomic
def registrar_usuario(datos):
    """Crea la cuenta y su perfil.

    Si VERIFICACION_CORREO_ACTIVA es True, la cuenta nace INACTIVA y se activa
    con el enlace del correo. Si es False, queda activa de una vez.

    `datos` son los datos limpios del formulario de registro.
    """
    correo = datos["correo"].strip().lower()
    validar_correo_institucional(correo)
    usuario = User.objects.create_user(
        username=correo,
        email=correo,
        password=datos["password1"],
        first_name=datos["nombre"],
        last_name=datos["apellido"],
        is_active=not settings.VERIFICACION_CORREO_ACTIVA,
    )
    Perfil.objects.create(
        usuario=usuario,
        tipo=tipo_para_correo(correo),
        acepto_politica_en=timezone.now(),
        fecha_nacimiento=datos["fecha_nacimiento"],
        telefono=datos["telefono"],
        responsable_nombre=datos.get("responsable_nombre", ""),
        responsable_documento=datos.get("responsable_documento", ""),
        responsable_telefono=datos.get("responsable_telefono", ""),
    )
    return usuario


def token_de_activacion(usuario):
    return signing.dumps({"id": usuario.pk, "correo": usuario.email}, salt=SAL_ACTIVACION)


def enviar_verificacion(request, usuario):
    """Envía el enlace para activar la cuenta (en desarrollo sale por consola)."""
    enlace = request.build_absolute_uri(
        reverse("usuarios:activar", args=[token_de_activacion(usuario)])
    )
    contexto = {
        "usuario": usuario,
        "enlace": enlace,
        "horas": settings.VERIFICACION_CORREO_HORAS,
    }
    send_mail(
        subject="Activa tu cuenta de Reservas deportivas UNIMINUTO",
        message=render_to_string("usuarios/correos/verificacion.txt", contexto),
        from_email=None,
        recipient_list=[usuario.email],
    )
    if settings.DEBUG:
        # En la consola el correo parte el enlace en varias líneas; aquí sale completo.
        print(f"\n>>> Enlace de activación para {usuario.email} (solo desarrollo):\n{enlace}\n", flush=True)


def activar_cuenta(token):
    """Activa la cuenta del enlace. Devuelve el usuario.

    Lanza ValidationError si el enlace está vencido, es inválido o ya se usó
    para una cuenta que el administrador desactivó después.
    """
    try:
        datos = signing.loads(
            token, salt=SAL_ACTIVACION, max_age=settings.VERIFICACION_CORREO_HORAS * 3600
        )
    except signing.SignatureExpired:
        raise ValidationError("El enlace venció. Pide uno nuevo.", code="vencido")
    except signing.BadSignature:
        raise ValidationError("El enlace no es válido.", code="invalido")

    usuario = User.objects.filter(pk=datos.get("id"), email=datos.get("correo")).first()
    if usuario is None:
        raise ValidationError("El enlace no es válido.", code="invalido")

    perfil = getattr(usuario, "perfil", None)
    if perfil is not None and perfil.correo_verificado_en is not None:
        if usuario.is_active:
            return usuario   # ya estaba activa: no pasa nada
        raise ValidationError(
            "Esta cuenta está desactivada. Comunícate con el administrador.", code="desactivada"
        )

    usuario.is_active = True
    usuario.save(update_fields=["is_active"])
    if perfil is not None:
        perfil.correo_verificado_en = timezone.now()
        perfil.save(update_fields=["correo_verificado_en"])
    return usuario


def pendiente_de_verificar(usuario):
    """True si la cuenta nunca se activó con el enlace del correo."""
    perfil = getattr(usuario, "perfil", None)
    return (
        not usuario.is_active
        and perfil is not None
        and perfil.correo_verificado_en is None
    )


def reenviar_verificacion(request, correo):
    """Vuelve a enviar el enlace si hay una cuenta pendiente con ese correo.

    No dice si el correo existe o no, para no revelar quién tiene cuenta.
    """
    usuario = User.objects.filter(email__iexact=correo.strip()).select_related("perfil").first()
    if usuario is not None and pendiente_de_verificar(usuario):
        enviar_verificacion(request, usuario)


# ---------------------------------------------------------------------------
# Lista de docentes autorizados
# ---------------------------------------------------------------------------

_PATRON_CORREO = re.compile(r"[^\s,;<>\"']+@[^\s,;<>\"']+")


def extraer_correos(texto):
    """Saca los correos de un texto pegado o de un CSV (en cualquier columna)."""
    encontrados = []
    for fila in csv.reader(io.StringIO(texto)):
        for celda in fila:
            encontrados.extend(_PATRON_CORREO.findall(celda))
    # Sin repetidos, en minúsculas, conservando el orden.
    vistos, resultado = set(), []
    for correo in encontrados:
        correo = correo.strip().lower()
        if correo not in vistos:
            vistos.add(correo)
            resultado.append(correo)
    return resultado


@transaction.atomic
def agregar_docentes_autorizados(correos, administrador):
    """Agrega correos a la lista y pasa a docente las cuentas que ya existían.

    Devuelve un resumen: {"agregados", "ya_estaban", "invalidos", "promovidos"}.
    """
    resumen = {"agregados": [], "ya_estaban": [], "invalidos": [], "promovidos": []}
    for correo in correos:
        try:
            validate_email(correo)
            validar_correo_institucional(correo)
        except ValidationError:
            resumen["invalidos"].append(correo)
            continue

        _, creado = DocenteAutorizado.objects.get_or_create(
            correo=correo, defaults={"agregado_por": administrador}
        )
        resumen["agregados" if creado else "ya_estaban"].append(correo)

        cambiados = Perfil.objects.filter(
            usuario__email__iexact=correo, tipo=Perfil.Tipo.ESTUDIANTE, usuario__is_staff=False
        ).update(tipo=Perfil.Tipo.DOCENTE)
        if cambiados:
            resumen["promovidos"].append(correo)
    return resumen


def quitar_docente_autorizado(docente_autorizado):
    """Quita el correo de la lista.

    No cambia el rol de una cuenta que ya era docente: eso lo decide el
    administrador desde la ficha del usuario.
    """
    docente_autorizado.delete()
