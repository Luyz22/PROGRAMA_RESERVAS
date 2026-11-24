from datetime import date, time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from espacios.models import Espacio

from .models import Reserva
from .servicios import (
    cancelar_reserva,
    crear_reserva,
    fechas_reservables,
    franjas_del_dia,
)
from .templatetags.horas import ampm


def _volver(request, por_defecto):
    """A dónde volver después de un formulario: la página de origen, si es de este sitio."""
    destino = request.POST.get("volver", "")
    if url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return destino
    return por_defecto


def _leer_fecha(texto):
    """Convierte '2026-11-24' en una fecha. Si el texto no sirve, devuelve None."""
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


@login_required
def franjas(request, espacio_id):
    espacio = get_object_or_404(Espacio, pk=espacio_id, activo=True)
    dias = fechas_reservables()

    fecha = _leer_fecha(request.GET.get("fecha"))
    if fecha not in dias:
        fecha = dias[0]

    # Las horas que este usuario ya reservó aquí ese día se muestran como "Tu reserva".
    mias = set(
        Reserva.objects.filter(
            usuario=request.user,
            espacio=espacio,
            fecha=fecha,
            estado=Reserva.Estado.CONFIRMADA,
        ).values_list("hora_inicio", flat=True)
    )
    lista = franjas_del_dia(espacio, fecha)
    for franja in lista:
        if franja["inicio"] in mias:
            franja["estado"] = "tuya"

    return render(
        request,
        "reservas/franjas.html",
        {
            "espacio": espacio,
            "dias": dias,
            "fecha": fecha,
            "franjas": lista,
            "hay_libres": any(f["estado"] == "libre" for f in lista),
        },
    )


@login_required
@require_POST
def reservar(request, espacio_id):
    espacio = get_object_or_404(Espacio, pk=espacio_id)
    fecha = _leer_fecha(request.POST.get("fecha"))
    volver = reverse("reservas:franjas", args=[espacio.pk])
    if fecha:
        volver += f"?fecha={fecha.isoformat()}"

    try:
        hora_inicio = time.fromisoformat(request.POST.get("hora", ""))
    except ValueError:
        messages.error(request, "Elige una franja antes de confirmar.")
        return redirect(volver)

    if fecha is None:
        messages.error(request, "La fecha no es válida.")
        return redirect(volver)

    try:
        reserva = crear_reserva(request.user, espacio, fecha, hora_inicio)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(
            request,
            f"Reserva confirmada: {espacio.nombre}, {reserva.fecha:%d/%m/%Y} "
            f"de {ampm(reserva.hora_inicio)} a {ampm(time(hora_inicio.hour + 1))}.",
        )
    return redirect(volver)


@login_required
@require_POST
def cancelar(request, reserva_id):
    reserva = get_object_or_404(Reserva, pk=reserva_id)
    try:
        cancelar_reserva(reserva, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        messages.success(
            request,
            f"Cancelaste tu reserva de {reserva.espacio.nombre} del "
            f"{reserva.fecha:%d/%m/%Y} a las {ampm(reserva.hora_inicio)}.",
        )
    return redirect(_volver(request, reverse("espacios:lista")))
