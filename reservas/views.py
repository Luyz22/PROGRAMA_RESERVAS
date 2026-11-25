from datetime import date, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from espacios.models import Espacio
from usuarios.servicios import es_correo_institucional

from .forms import DatosReservaForm
from .models import Reserva
from .servicios import (
    cancelar_reserva,
    cierre_del_dia,
    crear_reserva,
    fecha_maxima,
    franjas_del_dia,
    hoy,
    FILTROS_MIS_RESERVAS,
    primer_dia_disponible,
    puede_cancelar,
    reservas_del_usuario,
    ya_paso,
    recordatorios,
    validar_franja,
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
    inicio, limite = hoy(), fecha_maxima(request.user)

    fecha = _leer_fecha(request.GET.get("fecha"))
    if fecha is None or not (inicio <= fecha <= limite):
        fecha = primer_dia_disponible(request.user)

    # El selector muestra los días de 7 en 7, con flechas para avanzar o volver.
    semana = (fecha - inicio).days // 7
    desde = inicio + timedelta(days=7 * semana)
    dias = [
        {"fecha": d, "cierre": cierre_del_dia(d)}
        for d in (desde + timedelta(days=i) for i in range(7))
        if d <= limite
    ]
    anterior = desde - timedelta(days=7) if semana > 0 else None
    siguiente = desde + timedelta(days=7) if desde + timedelta(days=7) <= limite else None

    # Las horas que este usuario ya reservó aquí ese día se muestran como "Tu reserva".
    mias = dict(
        Reserva.objects.filter(
            usuario=request.user,
            espacio=espacio,
            fecha=fecha,
            estado=Reserva.Estado.CONFIRMADA,
        ).values_list("hora_inicio", "pk")
    )
    lista = franjas_del_dia(espacio, fecha)
    for franja in lista:
        if franja["inicio"] in mias:
            franja["estado"] = "tuya"
            franja["reserva_id"] = mias[franja["inicio"]]

    return render(
        request,
        "reservas/franjas.html",
        {
            "espacio": espacio,
            "dias": dias,
            "fecha": fecha,
            "hoy": inicio,
            "limite": limite,
            "anterior": anterior,
            "siguiente": siguiente,
            "ventana_larga": (limite - inicio).days > 7,
            "cierre": cierre_del_dia(fecha),
            "franjas": lista,
            "hay_libres": any(f["estado"] == "libre" for f in lista),
        },
    )


def _franja_pedida(request, datos):
    """Lee la fecha y la hora de la franja. Devuelve (fecha, hora) o (None, None)."""
    fecha = _leer_fecha(datos.get("fecha"))
    try:
        hora_inicio = time.fromisoformat(datos.get("hora", ""))
    except ValueError:
        hora_inicio = None
    return fecha, hora_inicio


@login_required
def datos(request, espacio_id):
    """Paso 2: los datos de la reserva (deporte, participantes, ARL, quién recibe)."""
    espacio = get_object_or_404(Espacio, pk=espacio_id)
    origen = request.POST if request.method == "POST" else request.GET
    fecha, hora_inicio = _franja_pedida(request, origen)

    volver = reverse("reservas:franjas", args=[espacio.pk])
    if fecha:
        volver += f"?fecha={fecha.isoformat()}"
    if fecha is None or hora_inicio is None:
        messages.error(request, "Elige una franja antes de continuar.")
        return redirect(volver)

    # Antes de pedir datos, revisa que la franja siga disponible.
    try:
        validar_franja(request.user, espacio, fecha, hora_inicio)
    except ValidationError as error:
        messages.error(request, error.messages[0])
        return redirect(volver)

    if request.method == "POST":
        form = DatosReservaForm(request.POST, espacio=espacio)
        if form.is_valid():
            try:
                reserva = crear_reserva(request.user, espacio, fecha, hora_inicio, form.cleaned_data)
            except ValidationError as error:
                if hasattr(error, "error_dict"):
                    form.agregar_errores(error)
                else:   # la franja se ocupó mientras llenaba el formulario
                    messages.error(request, error.messages[0])
                    return redirect(volver)
            else:
                return redirect("reservas:confirmacion", reserva_id=reserva.pk)
    else:
        usuario = request.user
        form = DatosReservaForm(espacio=espacio, initial={
            "recibe_nombre": usuario.get_full_name(),
            "recibe_correo": usuario.email if es_correo_institucional(usuario.email or "") else "",
        })

    return render(request, "reservas/datos.html", {
        "espacio": espacio,
        "fecha": fecha,
        "hora_inicio": hora_inicio,
        "form": form,
        "recordatorios": recordatorios(request.user),
        "volver": volver,
    })


@login_required
def confirmacion(request, reserva_id):
    """Paso 3: la reserva quedó confirmada; muestra los datos y los recordatorios."""
    reserva = get_object_or_404(Reserva.objects.select_related("espacio"), pk=reserva_id)
    if reserva.usuario != request.user and not request.user.is_staff:
        raise Http404
    return render(request, "reservas/confirmacion.html", {
        "reserva": reserva,
        "recordatorios": recordatorios(reserva.usuario),
        "cancelable": puede_cancelar(reserva),
        "ya_paso": ya_paso(reserva),
    })


@login_required
@require_POST
def cancelar(request, reserva_id):
    reserva = get_object_or_404(Reserva, pk=reserva_id)
    try:
        cancelar_reserva(reserva, request.user)
    except ValidationError as error:
        messages.error(request, error.messages[0])
    else:
        de_quien = "tu reserva" if reserva.usuario == request.user else (
            f"la reserva de {reserva.usuario.get_full_name() or reserva.usuario.username}"
        )
        messages.success(
            request,
            f"Cancelaste {de_quien} de {reserva.espacio.nombre} del "
            f"{reserva.fecha:%d/%m/%Y} a las {ampm(reserva.hora_inicio)}. La franja quedó libre.",
        )
    return redirect(_volver(request, reverse("reservas:mis_reservas")))


@login_required
def mis_reservas(request):
    filtros = dict(FILTROS_MIS_RESERVAS)
    filtro = request.GET.get("filtro", "todas")
    if filtro not in filtros:
        filtro = "todas"

    lista = reservas_del_usuario(request.user, filtro)
    pagina = Paginator(lista, 20).get_page(request.GET.get("pagina"))
    for reserva in pagina.object_list:
        reserva.cancelable = puede_cancelar(reserva)
        reserva.ya_paso = ya_paso(reserva)

    return render(request, "reservas/mis_reservas.html", {
        "pagina": pagina,
        "filtro": filtro,
        "filtros": FILTROS_MIS_RESERVAS,
        "parametros": f"filtro={filtro}",
    })
