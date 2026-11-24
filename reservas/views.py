from datetime import date, time
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from espacios.models import Espacio

from .models import Bloqueo, Reserva
from .servicios import (
    HORA_CIERRE,
    HORA_APERTURA,
    cancelar_reserva,
    crear_bloqueo,
    crear_reserva,
    fechas_reservables,
    franjas_del_dia,
    horas_del_dia,
)
from .templatetags.horas import ampm


def solo_administrador(vista):
    """Deja entrar solo a usuarios con permiso de administrador (is_staff)."""

    @login_required
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, "Solo el administrador puede entrar al panel.")
            return redirect("espacios:lista")
        return vista(request, *args, **kwargs)

    return envoltura


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


# ---------------------------------------------------------------------------
# Panel de administración
# ---------------------------------------------------------------------------

@solo_administrador
def panel(request):
    hoy = timezone.localdate()
    espacios = Espacio.objects.filter(activo=True).order_by("nombre")

    reservas_hoy = (
        Reserva.objects.filter(fecha=hoy)
        .select_related("espacio", "usuario", "usuario__perfil")
        .order_by("hora_inicio", "espacio__nombre")
    )
    confirmadas_hoy = sum(1 for r in reservas_hoy if r.estado == Reserva.Estado.CONFIRMADA)
    bloqueos_hoy = Bloqueo.objects.filter(fecha=hoy, espacio__activo=True).count()

    # Ocupación: franjas reservadas / franjas que se podían reservar hoy.
    franjas_totales = espacios.count() * (HORA_CIERRE - HORA_APERTURA) - bloqueos_hoy
    ocupacion = round(100 * confirmadas_hoy / franjas_totales) if franjas_totales > 0 else 0

    proximos_bloqueos = (
        Bloqueo.objects.filter(fecha__gte=hoy)
        .select_related("espacio", "creado_por")
        .order_by("fecha", "hora_inicio")[:20]
    )

    return render(
        request,
        "reservas/panel.html",
        {
            "hoy": hoy,
            "reservas_hoy": reservas_hoy,
            "confirmadas_hoy": confirmadas_hoy,
            "ocupacion": ocupacion,
            "bloqueos_hoy": bloqueos_hoy,
            "proximas_reservas": Reserva.objects.filter(
                fecha__gt=hoy, estado=Reserva.Estado.CONFIRMADA
            ).count(),
            "proximos_bloqueos": proximos_bloqueos,
            "espacios": espacios,
            "horas": horas_del_dia(),
            "datos_bloqueo": request.session.pop("datos_bloqueo", {}),
        },
    )


@solo_administrador
@require_POST
def bloquear(request):
    datos = {
        "espacio": request.POST.get("espacio", ""),
        "fecha": request.POST.get("fecha", ""),
        "hora": request.POST.get("hora", ""),
        "motivo": request.POST.get("motivo", "").strip()[:200],
    }
    espacio = Espacio.objects.filter(pk=datos["espacio"]).first() if datos["espacio"].isdigit() else None
    fecha = _leer_fecha(datos["fecha"])
    try:
        hora_inicio = time.fromisoformat(datos["hora"])
    except ValueError:
        hora_inicio = None

    try:
        if espacio is None or fecha is None or hora_inicio is None:
            raise ValidationError("Completa el espacio, la fecha y la franja.")
        bloqueo = crear_bloqueo(espacio, fecha, hora_inicio, datos["motivo"], request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        request.session["datos_bloqueo"] = datos  # para no perder lo que escribió
    else:
        messages.success(
            request,
            f"Bloqueaste {espacio.nombre} el {bloqueo.fecha:%d/%m/%Y} a las "
            f"{ampm(bloqueo.hora_inicio)} ({bloqueo.motivo}).",
        )
    return redirect("reservas:panel")


@solo_administrador
@require_POST
def quitar_bloqueo(request, bloqueo_id):
    bloqueo = get_object_or_404(Bloqueo, pk=bloqueo_id)
    bloqueo.delete()
    messages.success(
        request,
        f"Quitaste el bloqueo de {bloqueo.espacio.nombre} del {bloqueo.fecha:%d/%m/%Y} "
        f"a las {ampm(bloqueo.hora_inicio)}. La franja quedó libre.",
    )
    return redirect("reservas:panel")
