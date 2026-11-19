from datetime import time, timedelta

from django.utils import timezone

from django.core.exceptions import ValidationError

from django.db import IntegrityError, transaction

from .models import Bloqueo, Reserva

HORA_APERTURA = 6    # 6:00 am
HORA_CIERRE = 22     # 10:00 pm (la última franja termina a esta hora)
DIAS_ADELANTE = 7    # cuántos días se muestran, contando hoy


def fechas_reservables():
    """Devuelve la lista de días que se pueden elegir, empezando por hoy."""
    hoy = timezone.localdate()
    return [hoy + timedelta(days=i) for i in range(DIAS_ADELANTE)]


def franjas_del_dia(espacio, fecha):
    """Devuelve las franjas del día con su estado."""
    ocupadas = set(
        Reserva.objects.filter(
            espacio=espacio, fecha=fecha, estado=Reserva.Estado.CONFIRMADA
        ).values_list("hora_inicio", flat=True)
    )
    bloqueadas = set(
        Bloqueo.objects.filter(espacio=espacio, fecha=fecha).values_list(
            "hora_inicio", flat=True
        )
    )
    ahora = timezone.localtime()

    franjas = []
    for hora in range(HORA_APERTURA, HORA_CIERRE):
        inicio = time(hora, 0)
        fin = time(hora + 1, 0)

        if (fecha, inicio) <= (ahora.date(), ahora.time()):
            estado = "pasada"
        elif inicio in bloqueadas:
            estado = "mantenimiento"
        elif inicio in ocupadas:
            estado = "ocupada"
        else:
            estado = "libre"

        franjas.append({"inicio": inicio, "fin": fin, "estado": estado})
    return franjas

def crear_reserva(usuario, espacio, fecha, hora_inicio):
    """Crea una reserva si la franja está libre. Si no, explica por qué no."""
    if not espacio.activo:
        raise ValidationError("Este espacio no está disponible.")

    if fecha not in fechas_reservables():
        raise ValidationError("Solo puedes reservar en los próximos 7 días.")

    estado = None
    for franja in franjas_del_dia(espacio, fecha):
        if franja["inicio"] == hora_inicio:
            estado = franja["estado"]

    if estado is None:
        raise ValidationError("Esa franja no existe.")
    if estado == "pasada":
        raise ValidationError("Esa franja ya pasó.")
    if estado == "mantenimiento":
        raise ValidationError("Esa franja está en mantenimiento.")
    if estado == "ocupada":
        raise ValidationError("Esa franja ya está ocupada.")

    ya_tiene = Reserva.objects.filter(
        usuario=usuario,
        fecha=fecha,
        hora_inicio=hora_inicio,
        estado=Reserva.Estado.CONFIRMADA,
    ).exists()
    if ya_tiene:
        raise ValidationError("Ya tienes otra reserva en ese mismo horario.")

    try:
        with transaction.atomic():
            return Reserva.objects.create(
                usuario=usuario, espacio=espacio, fecha=fecha, hora_inicio=hora_inicio
            )
    except IntegrityError:
        raise ValidationError("Alguien acaba de reservar esa franja. Elige otra.")


def cancelar_reserva(reserva, usuario):
    """Cancela una reserva confirmada que todavía no ha empezado."""
    if reserva.usuario != usuario and not usuario.is_staff:
        raise ValidationError("No puedes cancelar la reserva de otra persona.")

    if reserva.estado != Reserva.Estado.CONFIRMADA:
        raise ValidationError("Esta reserva ya estaba cancelada.")

    ahora = timezone.localtime()
    if (reserva.fecha, reserva.hora_inicio) <= (ahora.date(), ahora.time()):
        raise ValidationError("No puedes cancelar una reserva que ya comenzó.")

    reserva.estado = Reserva.Estado.CANCELADA
    reserva.save(update_fields=["estado"])
    return reserva