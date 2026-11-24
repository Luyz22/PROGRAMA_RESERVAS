from datetime import date, time
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from espacios.models import Espacio
from reservas.models import Bloqueo, Reserva
from reservas.servicios import HORA_APERTURA, HORA_CIERRE, crear_bloqueo, horas_del_dia
from reservas.templatetags.horas import ampm
from usuarios.models import Perfil

from .forms import ROL_ADMINISTRADOR, ROLES, EspacioForm, UsuarioForm

User = get_user_model()
POR_PAGINA = 20


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


def _leer_fecha(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Inicio del panel y bloqueos
# ---------------------------------------------------------------------------

@solo_administrador
def inicio(request):
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

    return render(request, "panel/inicio.html", {
        "seccion": "inicio",
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
    })


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
    return redirect("panel:inicio")


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
    return redirect("panel:inicio")


# ---------------------------------------------------------------------------
# Espacios
# ---------------------------------------------------------------------------

@solo_administrador
def espacios(request):
    lista = Espacio.objects.order_by("-activo", "nombre")
    return render(request, "panel/espacios.html", {"seccion": "espacios", "espacios": lista})


@solo_administrador
def espacio_form(request, espacio_id=None):
    espacio = get_object_or_404(Espacio, pk=espacio_id) if espacio_id else None
    form = EspacioForm(request.POST or None, instance=espacio)
    if request.method == "POST" and form.is_valid():
        guardado = form.save()
        accion = "actualizado" if espacio else "creado"
        messages.success(request, f"Espacio «{guardado.nombre}» {accion}.")
        return redirect("panel:espacios")
    return render(request, "panel/espacio_form.html", {
        "seccion": "espacios", "form": form, "espacio": espacio,
    })


# ---------------------------------------------------------------------------
# Reservas
# ---------------------------------------------------------------------------

@solo_administrador
def reservas(request):
    hoy = timezone.localdate()
    filtros = {
        "desde": request.GET.get("desde", hoy.isoformat()),
        "hasta": request.GET.get("hasta", ""),
        "espacio": request.GET.get("espacio", ""),
        "estado": request.GET.get("estado", ""),
        "q": request.GET.get("q", "").strip(),
    }

    lista = Reserva.objects.select_related("espacio", "usuario", "usuario__perfil")
    desde, hasta = _leer_fecha(filtros["desde"]), _leer_fecha(filtros["hasta"])
    if desde:
        lista = lista.filter(fecha__gte=desde)
    if hasta:
        lista = lista.filter(fecha__lte=hasta)
    if filtros["espacio"].isdigit():
        lista = lista.filter(espacio_id=filtros["espacio"])
    if filtros["estado"] in Reserva.Estado.values:
        lista = lista.filter(estado=filtros["estado"])
    if filtros["q"]:
        q = filtros["q"]
        lista = lista.filter(
            Q(usuario__first_name__icontains=q) | Q(usuario__last_name__icontains=q)
            | Q(usuario__email__icontains=q) | Q(usuario__username__icontains=q)
        )
    lista = lista.order_by("fecha", "hora_inicio", "espacio__nombre")

    pagina = Paginator(lista, POR_PAGINA).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)

    return render(request, "panel/reservas.html", {
        "seccion": "reservas",
        "pagina": pagina,
        "filtros": filtros,
        "espacios": Espacio.objects.order_by("nombre"),
        "estados": Reserva.Estado.choices,
        "parametros": parametros.urlencode(),
    })


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------

@solo_administrador
def usuarios(request):
    filtros = {"q": request.GET.get("q", "").strip(), "rol": request.GET.get("rol", "")}
    lista = User.objects.select_related("perfil")
    if filtros["q"]:
        q = filtros["q"]
        lista = lista.filter(
            Q(first_name__icontains=q) | Q(last_name__icontains=q)
            | Q(email__icontains=q) | Q(username__icontains=q)
        )
    if filtros["rol"] == ROL_ADMINISTRADOR:
        lista = lista.filter(is_staff=True)
    elif filtros["rol"] in Perfil.Tipo.values:
        lista = lista.filter(is_staff=False, perfil__tipo=filtros["rol"])
    lista = lista.order_by("first_name", "last_name", "username")

    pagina = Paginator(lista, POR_PAGINA).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)

    return render(request, "panel/usuarios.html", {
        "seccion": "usuarios",
        "pagina": pagina,
        "filtros": filtros,
        "roles": ROLES,
        "parametros": parametros.urlencode(),
    })


@solo_administrador
def usuario_form(request, usuario_id=None):
    usuario = get_object_or_404(User, pk=usuario_id) if usuario_id else None
    form = UsuarioForm(request.POST or None, usuario=usuario, editor=request.user)
    if request.method == "POST" and form.is_valid():
        guardado = form.save()
        nombre = guardado.get_full_name() or guardado.username
        messages.success(request, f"Usuario «{nombre}» {'actualizado' if usuario else 'creado'}.")
        return redirect("panel:usuarios")

    reservas_usuario = []
    if usuario:
        reservas_usuario = (
            Reserva.objects.filter(usuario=usuario).select_related("espacio")
            .order_by("-fecha", "-hora_inicio")[:10]
        )
    return render(request, "panel/usuario_form.html", {
        "seccion": "usuarios", "form": form, "usuario_editado": usuario,
        "reservas_usuario": reservas_usuario,
    })
