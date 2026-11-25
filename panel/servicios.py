"""Consultas del panel: filtrar reservas, armar el reporte y exportarlo a CSV."""

import calendar
import csv
from datetime import date

from django.db.models import Count, Q, Sum
from django.utils import timezone

from reservas.models import Reserva
from reservas.templatetags.horas import ampm, hora_fin

# Separador del CSV. Con ";" Excel en español lo abre directo en columnas.
SEPARADOR_CSV = ";"


def _leer_fecha(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def leer_filtros(parametros, desde_por_defecto="", hasta_por_defecto=""):
    """Lee los filtros de la URL (?desde=&hasta=&espacio=&deporte=&estado=&q=)."""
    return {
        "desde": parametros.get("desde", desde_por_defecto),
        "hasta": parametros.get("hasta", hasta_por_defecto),
        "espacio": parametros.get("espacio", ""),
        "deporte": parametros.get("deporte", ""),
        "estado": parametros.get("estado", ""),
        "q": parametros.get("q", "").strip(),
    }


def filtrar_reservas(filtros):
    """Las reservas que cumplen los filtros, ordenadas por fecha y hora."""
    lista = Reserva.objects.select_related("espacio", "usuario", "usuario__perfil")
    desde, hasta = _leer_fecha(filtros.get("desde")), _leer_fecha(filtros.get("hasta"))
    if desde:
        lista = lista.filter(fecha__gte=desde)
    if hasta:
        lista = lista.filter(fecha__lte=hasta)
    if str(filtros.get("espacio", "")).isdigit():
        lista = lista.filter(espacio_id=filtros["espacio"])
    if filtros.get("deporte") in Reserva.Deporte.values:
        lista = lista.filter(deporte=filtros["deporte"])
    if filtros.get("estado") in Reserva.Estado.values:
        lista = lista.filter(estado=filtros["estado"])
    if filtros.get("q"):
        q = filtros["q"]
        lista = lista.filter(
            Q(usuario__first_name__icontains=q) | Q(usuario__last_name__icontains=q)
            | Q(usuario__email__icontains=q) | Q(usuario__username__icontains=q)
        )
    return lista.order_by("fecha", "hora_inicio", "espacio__nombre")


def mes_actual(hoy):
    """(primer día, último día) del mes de `hoy`."""
    ultimo = calendar.monthrange(hoy.year, hoy.month)[1]
    return hoy.replace(day=1), hoy.replace(day=ultimo)


# ---------------------------------------------------------------------------
# Reporte
# ---------------------------------------------------------------------------

def _rol(usuario):
    if usuario.is_staff:
        return "Administrador"
    perfil = getattr(usuario, "perfil", None)
    return perfil.get_tipo_display() if perfil else "Sin tipo"


def resumen(reservas):
    """Totales para la parte de arriba del reporte."""
    confirmadas = reservas.filter(estado=Reserva.Estado.CONFIRMADA)
    deportes = dict(Reserva.Deporte.choices)

    por_deporte = [
        {"nombre": deportes.get(f["deporte"], "Sin deporte"), "total": f["total"]}
        for f in confirmadas.values("deporte").annotate(total=Count("id")).order_by("-total")
    ]
    por_espacio = list(
        confirmadas.values("espacio__nombre").annotate(total=Count("id")).order_by("-total")
    )
    horas = [
        {"hora": f"{ampm(f['hora_inicio'])} – {ampm(hora_fin(f['hora_inicio']))}", "total": f["total"]}
        for f in confirmadas.values("hora_inicio").annotate(total=Count("id")).order_by("-total", "hora_inicio")[:5]
    ]
    total = reservas.count()
    canceladas = reservas.filter(estado=Reserva.Estado.CANCELADA).count()
    return {
        "total": total,
        "confirmadas": confirmadas.count(),
        "canceladas": canceladas,
        "porcentaje_canceladas": round(100 * canceladas / total) if total else 0,
        "participantes": confirmadas.aggregate(s=Sum("participantes"))["s"] or 0,
        "por_deporte": por_deporte,
        "por_espacio": por_espacio,
        "horas_mas_pedidas": horas,
    }


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

COLUMNAS_CSV = [
    "Fecha", "Hora inicio", "Hora fin", "Espacio", "Deporte", "Estado",
    "Usuario", "Correo", "Rol", "Participantes", "ARL", "ARL confirmada",
    "Recibe (nombre)", "Recibe (correo)", "Creada en",
]


def _celda_segura(valor):
    """Evita que Excel interprete un texto como fórmula (inyección en CSV)."""
    texto = "" if valor is None else str(valor)
    if texto[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + texto
    return texto


def escribir_csv(reservas, destino):
    """Escribe las reservas en `destino` (un archivo o una respuesta HTTP)."""
    destino.write("﻿")   # marca para que Excel reconozca las tildes (UTF-8)
    escritor = csv.writer(destino, delimiter=SEPARADOR_CSV)
    escritor.writerow(COLUMNAS_CSV)
    for r in reservas:
        u = r.usuario
        fila = [
            r.fecha.strftime("%d/%m/%Y"),
            r.hora_inicio.strftime("%H:%M"),
            hora_fin(r.hora_inicio).strftime("%H:%M"),
            r.espacio.nombre,
            r.get_deporte_display() if r.deporte else "",
            r.get_estado_display(),
            u.get_full_name() or u.username,
            u.email,
            _rol(u),
            r.participantes if r.participantes is not None else "",
            r.arl_nombre,
            "Sí" if r.arl_confirmada else "No",
            r.recibe_nombre,
            r.recibe_correo,
            timezone.localtime(r.creada_en).strftime("%d/%m/%Y %H:%M") if r.creada_en else "",
        ]
        escritor.writerow([_celda_segura(v) for v in fila])
