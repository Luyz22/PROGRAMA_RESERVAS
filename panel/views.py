from datetime import date, time
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from espacios.models import Espacio
from reservas.models import Bloqueo, Reserva
from reservas.servicios import cierre_del_dia, crear_bloqueo, franjas_abiertas_del_dia, horas_del_dia, hoy as hoy_local
from reservas.templatetags.horas import ampm
from usuarios.models import DocenteAutorizado, Perfil
from usuarios.servicios import (
    agregar_docentes_autorizados,
    dominio_institucional,
    extraer_correos,
    quitar_docente_autorizado,
)

from .servicios import escribir_csv, filtrar_reservas, leer_filtros, mes_actual, resumen
from .forms import ROL_ADMINISTRADOR, ROLES, DocentesAutorizadosForm, EspacioForm, UsuarioForm

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
    hoy = hoy_local()
    espacios = Espacio.objects.filter(activo=True).order_by("nombre")

    reservas_hoy = (
        Reserva.objects.filter(fecha=hoy)
        .select_related("espacio", "usuario", "usuario__perfil")
        .order_by("hora_inicio", "espacio__nombre")
    )
    confirmadas_hoy = sum(1 for r in reservas_hoy if r.estado == Reserva.Estado.CONFIRMADA)
    bloqueos_hoy = Bloqueo.objects.filter(fecha=hoy, espacio__activo=True).count()

    # Ocupación: franjas reservadas / franjas que se podían reservar hoy
    # (según el horario de hoy; un domingo o festivo da 0).
    franjas_totales = franjas_abiertas_del_dia(hoy, espacios.count()) - bloqueos_hoy
    ocupacion = round(100 * confirmadas_hoy / franjas_totales) if franjas_totales > 0 else 0

    proximos_bloqueos = (
        Bloqueo.objects.filter(fecha__gte=hoy)
        .select_related("espacio", "creado_por")
        .order_by("fecha", "hora_inicio")[:20]
    )

    return render(request, "panel/inicio.html", {
        "seccion": "inicio",
        "hoy": hoy,
        "cierre_hoy": cierre_del_dia(hoy),
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
    filtros = leer_filtros(request.GET, desde_por_defecto=hoy_local().isoformat())
    lista = filtrar_reservas(filtros)

    pagina = Paginator(lista, POR_PAGINA).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)

    return render(request, "panel/reservas.html", {
        "seccion": "reservas",
        "pagina": pagina,
        "filtros": filtros,
        "espacios": Espacio.objects.order_by("nombre"),
        "deportes": Reserva.Deporte.choices,
        "estados": Reserva.Estado.choices,
        "parametros": parametros.urlencode(),
    })


# ---------------------------------------------------------------------------
# Reportes
# ---------------------------------------------------------------------------

@solo_administrador
def reportes(request):
    inicio_mes, fin_mes = mes_actual(hoy_local())
    filtros = leer_filtros(
        request.GET, desde_por_defecto=inicio_mes.isoformat(), hasta_por_defecto=fin_mes.isoformat()
    )
    lista = filtrar_reservas(filtros)

    if request.GET.get("formato") == "csv":
        respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
        nombre = f"reservas_{filtros['desde'] or 'inicio'}_a_{filtros['hasta'] or 'hoy'}.csv"
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
        escribir_csv(lista, respuesta)
        return respuesta

    pagina = Paginator(lista, POR_PAGINA).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)
    parametros.pop("formato", None)

    return render(request, "panel/reportes.html", {
        "seccion": "reportes",
        "pagina": pagina,
        "filtros": filtros,
        "resumen": resumen(lista),
        "espacios": Espacio.objects.order_by("nombre"),
        "deportes": Reserva.Deporte.choices,
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


# ---------------------------------------------------------------------------
# Docentes autorizados
# ---------------------------------------------------------------------------

@solo_administrador
def docentes_autorizados(request):
    form = DocentesAutorizadosForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        correos = extraer_correos(form.texto())
        if not correos:
            messages.error(request, "No encontré correos en lo que pegaste o subiste.")
        else:
            resumen = agregar_docentes_autorizados(correos, request.user)
            partes = [f"{len(resumen['agregados'])} agregados"]
            if resumen["ya_estaban"]:
                partes.append(f"{len(resumen['ya_estaban'])} ya estaban")
            if resumen["promovidos"]:
                partes.append(f"{len(resumen['promovidos'])} cuentas pasaron a docente")
            messages.success(request, "Lista actualizada: " + ", ".join(partes) + ".")
            if resumen["invalidos"]:
                messages.warning(
                    request,
                    f"No se agregaron {len(resumen['invalidos'])} correos porque no son "
                    f"@{dominio_institucional()} o están mal escritos: "
                    + ", ".join(resumen["invalidos"][:10])
                    + ("…" if len(resumen["invalidos"]) > 10 else ""),
                )
            return redirect("panel:docentes")

    q = request.GET.get("q", "").strip()
    lista = DocenteAutorizado.objects.select_related("agregado_por")
    if q:
        lista = lista.filter(correo__icontains=q)
    pagina = Paginator(lista, POR_PAGINA).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)

    # Qué correos de la lista ya tienen cuenta.
    con_cuenta = set(
        User.objects.filter(email__in=[d.correo for d in pagina.object_list]).values_list("email", flat=True)
    )
    return render(request, "panel/docentes.html", {
        "seccion": "docentes",
        "form": form,
        "pagina": pagina,
        "q": q,
        "con_cuenta": con_cuenta,
        "parametros": parametros.urlencode(),
        "dominio": dominio_institucional(),
    })


@solo_administrador
@require_POST
def quitar_docente(request, docente_id):
    docente = get_object_or_404(DocenteAutorizado, pk=docente_id)
    quitar_docente_autorizado(docente)
    messages.success(
        request,
        f"Quitaste {docente.correo} de la lista. Si ya tenía cuenta de docente, sigue siéndolo "
        "hasta que le cambies el rol en Usuarios.",
    )
    return redirect("panel:docentes")
