"""Reglas del negocio de las reservas.

Toda la lógica (horarios, festivos, quién puede reservar qué) vive aquí,
no en las vistas, para que las pantallas y las pruebas usen las mismas reglas.
"""

from datetime import time, timedelta
from functools import lru_cache

import logging

import holidays
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone

from usuarios.servicios import dominio_institucional, es_correo_institucional

from .models import Bloqueo, Reserva

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuración (cambia aquí y se aplica en todo el sistema)
# ---------------------------------------------------------------------------

# Horario por día de la semana (0 = lunes ... 6 = domingo).
# (hora de apertura, hora de cierre): la última franja termina a la hora de cierre.
# None = ese día no se abre.
HORARIO_SEMANAL = {
    0: (8, 21),   # lunes: 8:00 am a 9:00 pm
    1: (8, 21),   # martes
    2: (8, 21),   # miércoles
    3: (8, 21),   # jueves
    4: (8, 21),   # viernes
    5: (8, 16),   # sábado: 8:00 am a 4:00 pm
    6: None,      # domingo: cerrado
}

# Cuántos días después de hoy se puede reservar, según el rol.
# Ej.: 7 => un estudiante puede reservar desde hoy hasta el mismo día de la próxima semana.
DIAS_ANTICIPACION = {
    "estudiante": 7,
    "docente": 30,
    "administrador": 365,
}

# País de los festivos que se cierran automáticamente.
PAIS_FESTIVOS = "CO"

# Deportes que se pueden elegir según el tipo de espacio.
# Un tipo que no aparece aquí (p. ej. gimnasio) no pide deporte al reservar.
DEPORTES_POR_TIPO_DE_ESPACIO = {
    "cancha": [
        Reserva.Deporte.MICROFUTBOL,
        Reserva.Deporte.BALONCESTO,
        Reserva.Deporte.VOLEIBOL,
    ],
}

# Recordatorios que se muestran en el formulario, en la confirmación y en el correo.
MINUTOS_ANTES = 10

DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


# ---------------------------------------------------------------------------
# Fecha y hora actuales (en una función, para poder fijarlas en las pruebas)
# ---------------------------------------------------------------------------

def ahora():
    return timezone.localtime()


def hoy():
    return ahora().date()


# ---------------------------------------------------------------------------
# Roles y anticipación
# ---------------------------------------------------------------------------

def rol_de(usuario):
    """'administrador', 'docente' o 'estudiante'.

    Un usuario sin perfil (por ejemplo, uno creado con createsuperuser que no
    sea administrador) se trata como estudiante.
    """
    if usuario.is_staff:
        return "administrador"
    perfil = getattr(usuario, "perfil", None)
    if perfil is not None and perfil.tipo in DIAS_ANTICIPACION:
        return perfil.tipo
    return "estudiante"


def dias_anticipacion(usuario):
    return DIAS_ANTICIPACION[rol_de(usuario)]


def fecha_maxima(usuario):
    """El último día que este usuario puede reservar."""
    return hoy() + timedelta(days=dias_anticipacion(usuario))


def fechas_reservables(usuario):
    """Todos los días entre hoy y la fecha máxima del usuario (incluye los cerrados)."""
    inicio, fin = hoy(), fecha_maxima(usuario)
    return [inicio + timedelta(days=i) for i in range((fin - inicio).days + 1)]


# ---------------------------------------------------------------------------
# Horario de cada día
# ---------------------------------------------------------------------------

@lru_cache(maxsize=16)
def _festivos_del_anio(anio):
    return holidays.country_holidays(PAIS_FESTIVOS, years=anio, language="es")


def festivo(fecha):
    """El nombre del festivo de esa fecha, o None si no es festivo."""
    return _festivos_del_anio(fecha.year).get(fecha)


def cierre_del_dia(fecha):
    """Por qué está cerrado ese día, o None si abre.

    Devuelve un diccionario {"estado": "festivo" | "cerrado", "motivo": texto}.
    """
    nombre = festivo(fecha)
    if nombre:
        return {"estado": "festivo", "motivo": f"Festivo: {nombre}"}
    if HORARIO_SEMANAL.get(fecha.weekday()) is None:
        return {"estado": "cerrado", "motivo": f"Los {DIAS_SEMANA[fecha.weekday()]}s no hay servicio"}
    return None


def horario_del_dia(fecha):
    """(apertura, cierre) de ese día, o None si está cerrado."""
    if cierre_del_dia(fecha):
        return None
    return HORARIO_SEMANAL[fecha.weekday()]


def horas_del_dia(fecha=None):
    """Horas de inicio de las franjas.

    Con una fecha: solo las de ese día (lista vacía si está cerrado).
    Sin fecha: todas las que pueden existir en la semana (para formularios).
    """
    if fecha is None:
        horarios = [h for h in HORARIO_SEMANAL.values() if h]
        apertura = min(h[0] for h in horarios)
        cierre = max(h[1] for h in horarios)
    else:
        horario = horario_del_dia(fecha)
        if horario is None:
            return []
        apertura, cierre = horario
    return [time(hora, 0) for hora in range(apertura, cierre)]


def _ya_empezo(fecha, hora_inicio):
    momento = ahora()
    return (fecha, hora_inicio) <= (momento.date(), momento.time())


def franjas_del_dia(espacio, fecha):
    """Las franjas del día con su estado.

    Estados: libre, ocupada, mantenimiento, pasada, cerrado y festivo.
    Un día cerrado muestra las horas de un día normal marcadas como cerradas,
    para que la persona vea que ese día no hay servicio.
    """
    cierre = cierre_del_dia(fecha)
    if cierre:
        horario = HORARIO_SEMANAL.get(fecha.weekday()) or HORARIO_SEMANAL[0]
        return [
            {"inicio": time(h, 0), "fin": time(h + 1, 0), "estado": cierre["estado"]}
            for h in range(*horario)
        ]

    ocupadas = set(
        Reserva.objects.filter(
            espacio=espacio, fecha=fecha, estado=Reserva.Estado.CONFIRMADA
        ).values_list("hora_inicio", flat=True)
    )
    bloqueadas = set(
        Bloqueo.objects.filter(espacio=espacio, fecha=fecha).values_list("hora_inicio", flat=True)
    )

    franjas = []
    for inicio in horas_del_dia(fecha):
        if _ya_empezo(fecha, inicio):
            estado = "pasada"
        elif inicio in bloqueadas:
            estado = "mantenimiento"
        elif inicio in ocupadas:
            estado = "ocupada"
        else:
            estado = "libre"
        franjas.append({"inicio": inicio, "fin": time(inicio.hour + 1, 0), "estado": estado})
    return franjas


def primer_dia_disponible(usuario):
    """El primer día de la ventana del usuario que abre y aún tiene franjas por empezar."""
    for fecha in fechas_reservables(usuario):
        if any(not _ya_empezo(fecha, hora) for hora in horas_del_dia(fecha)):
            return fecha
    return hoy()


def validar_fecha_para(usuario, fecha):
    """Revisa que el usuario pueda reservar ese día (sin mirar la hora)."""
    if fecha < hoy():
        raise ValidationError("Esa fecha ya pasó.")

    limite = fecha_maxima(usuario)
    if fecha > limite:
        raise ValidationError(
            f"Como {rol_de(usuario)} puedes reservar hasta {dias_anticipacion(usuario)} días "
            f"después de hoy (hasta el {limite:%d/%m/%Y})."
        )

    cierre = cierre_del_dia(fecha)
    if cierre:
        raise ValidationError(f"Ese día no se puede reservar. {cierre['motivo']}.")


# ---------------------------------------------------------------------------
# Reservas
# ---------------------------------------------------------------------------

def deportes_de(espacio):
    """Lista de (valor, texto) de los deportes que se juegan en ese espacio."""
    return [(d.value, d.label) for d in DEPORTES_POR_TIPO_DE_ESPACIO.get(espacio.tipo, [])]


def recordatorios(usuario):
    """Lo que la persona debe tener en cuenta el día de la reserva."""
    lista = [
        "Quien recibe el espacio debe presentar su carnet de UNIMINUTO.",
        f"Llega {MINUTOS_ANTES} minutos antes de la hora de tu reserva.",
    ]
    perfil = getattr(usuario, "perfil", None)
    if perfil is not None and perfil.es_menor:
        lista.append("Como eres menor de edad, debes asistir con tu adulto responsable.")
    return lista


def validar_franja(usuario, espacio, fecha, hora_inicio):
    """Revisa que el usuario pueda reservar esa franja ahora mismo."""
    if not espacio.activo:
        raise ValidationError("Este espacio no está disponible.")

    validar_fecha_para(usuario, fecha)

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


def validar_datos_reserva(espacio, datos):
    """Revisa los datos del formulario de la reserva. Devuelve los datos limpios.

    Si algo está mal lanza ValidationError con un error por campo, para que el
    formulario lo muestre junto al campo correspondiente.
    """
    errores = {}
    limpios = {}

    deportes = [valor for valor, _ in deportes_de(espacio)]
    deporte = (datos.get("deporte") or "").strip()
    if deportes:
        if deporte not in deportes:
            errores["deporte"] = "Elige el deporte que vas a practicar."
        limpios["deporte"] = deporte
    else:
        limpios["deporte"] = ""

    try:
        participantes = int(datos.get("participantes"))
    except (TypeError, ValueError):
        errores["participantes"] = "Escribe cuántas personas van a participar."
        participantes = None
    else:
        minimo, maximo = espacio.aforo_minimo, espacio.aforo_maximo
        if participantes < 1:
            errores["participantes"] = "Debe haber al menos 1 participante."
        elif minimo and participantes < minimo:
            errores["participantes"] = f"Se necesitan al menos {minimo} participantes ({espacio.aforo_texto})."
        elif maximo and participantes > maximo:
            errores["participantes"] = f"Pueden ser máximo {maximo} participantes ({espacio.aforo_texto})."
    limpios["participantes"] = participantes

    arl = (datos.get("arl_nombre") or "").strip()
    if not arl:
        errores["arl_nombre"] = "Escribe el nombre de tu ARL."
    limpios["arl_nombre"] = arl[:100]

    if not datos.get("arl_confirmada"):
        errores["arl_confirmada"] = "Debes confirmar que todos los participantes están afiliados a una ARL."
    limpios["arl_confirmada"] = True

    nombre = (datos.get("recibe_nombre") or "").strip()
    if not nombre:
        errores["recibe_nombre"] = "Escribe el nombre de quien recibe el espacio."
    limpios["recibe_nombre"] = nombre[:150]

    correo = (datos.get("recibe_correo") or "").strip().lower()
    if not correo:
        errores["recibe_correo"] = "Escribe el correo de quien recibe el espacio."
    elif not es_correo_institucional(correo):
        errores["recibe_correo"] = f"Debe ser un correo @{dominio_institucional()}."
    limpios["recibe_correo"] = correo

    if errores:
        raise ValidationError(errores)
    return limpios


def crear_reserva(usuario, espacio, fecha, hora_inicio, datos):
    """Crea una reserva si la franja está libre y los datos están completos.

    `datos` trae: deporte, participantes, arl_nombre, arl_confirmada,
    recibe_nombre y recibe_correo. Si algo falla, explica por qué.
    """
    validar_franja(usuario, espacio, fecha, hora_inicio)
    limpios = validar_datos_reserva(espacio, datos)

    try:
        with transaction.atomic():
            reserva = Reserva.objects.create(
                usuario=usuario, espacio=espacio, fecha=fecha, hora_inicio=hora_inicio, **limpios
            )
    except IntegrityError:
        raise ValidationError("Alguien acaba de reservar esa franja. Elige otra.")

    notificar(reserva, "confirmada")
    return reserva


def cancelar_reserva(reserva, usuario):
    """Cancela una reserva confirmada que todavía no ha empezado."""
    if reserva.usuario != usuario and not usuario.is_staff:
        raise ValidationError("No puedes cancelar la reserva de otra persona.")

    if reserva.estado != Reserva.Estado.CONFIRMADA:
        raise ValidationError("Esta reserva ya estaba cancelada.")

    if _ya_empezo(reserva.fecha, reserva.hora_inicio):
        raise ValidationError("No puedes cancelar una reserva que ya comenzó.")

    reserva.estado = Reserva.Estado.CANCELADA
    reserva.save(update_fields=["estado"])
    notificar(reserva, "cancelada", por_administrador=usuario != reserva.usuario)
    return reserva


# ---------------------------------------------------------------------------
# Correos
# ---------------------------------------------------------------------------

ASUNTOS = {
    "confirmada": "Reserva confirmada: {espacio}, {fecha:%d/%m/%Y} a las {hora}",
    "cancelada": "Reserva cancelada: {espacio}, {fecha:%d/%m/%Y} a las {hora}",
}


def notificar(reserva, evento, por_administrador=False):
    """Envía el correo de reserva confirmada o cancelada (consola en desarrollo).

    Va a quien reservó y, si es otra persona, también a quien recibe el espacio.
    Si el correo falla, la reserva no se pierde: solo se deja constancia en el log.
    """
    from .templatetags.horas import ampm, hora_fin

    destinatarios = [reserva.usuario.email]
    if reserva.recibe_correo and reserva.recibe_correo.lower() != reserva.usuario.email.lower():
        destinatarios.append(reserva.recibe_correo)
    destinatarios = [d for d in destinatarios if d]
    if not destinatarios:
        return

    contexto = {
        "reserva": reserva,
        "hora": ampm(reserva.hora_inicio),
        "hora_fin": ampm(hora_fin(reserva.hora_inicio)),
        "recordatorios": recordatorios(reserva.usuario),
        "por_administrador": por_administrador,
    }
    asunto = ASUNTOS[evento].format(espacio=reserva.espacio.nombre, fecha=reserva.fecha, hora=contexto["hora"])
    try:
        send_mail(
            subject=asunto,
            message=render_to_string(f"reservas/correos/{evento}.txt", contexto),
            from_email=None,
            recipient_list=destinatarios,
        )
    except Exception:
        logger.exception("No se pudo enviar el correo de reserva %s (%s)", reserva.pk, evento)


def proxima_reserva(usuario):
    """La reserva confirmada más cercana del usuario que aún no ha terminado.

    Incluye la que está en curso: si son las 5:20 pm, la de 5:00 pm cuenta.
    """
    momento = ahora()
    hora_actual = time(momento.hour, 0)
    return (
        Reserva.objects.filter(usuario=usuario, estado=Reserva.Estado.CONFIRMADA)
        .filter(
            Q(fecha__gt=momento.date())
            | Q(fecha=momento.date(), hora_inicio__gte=hora_actual)
        )
        .select_related("espacio")
        .order_by("fecha", "hora_inicio")
        .first()
    )


# ---------------------------------------------------------------------------
# Mis reservas
# ---------------------------------------------------------------------------

FILTROS_MIS_RESERVAS = [
    ("todas", "Todas"),
    ("proximas", "Próximas"),
    ("historial", "Historial"),
]


def _q_proximas():
    """Reservas confirmadas que aún no terminan (incluye la que está en curso)."""
    momento = ahora()
    return Q(estado=Reserva.Estado.CONFIRMADA) & (
        Q(fecha__gt=momento.date())
        | Q(fecha=momento.date(), hora_inicio__gte=time(momento.hour, 0))
    )


def reservas_del_usuario(usuario, filtro="todas"):
    """Las reservas de una persona para la pantalla "Mis reservas".

    - proximas: confirmadas que aún no terminan, de la más cercana a la más lejana.
    - historial: las que ya pasaron y las canceladas, de la más reciente a la más vieja.
    - todas: primero las próximas y luego el historial.
    """
    base = Reserva.objects.filter(usuario=usuario).select_related("espacio")
    proximas = list(base.filter(_q_proximas()).order_by("fecha", "hora_inicio"))
    if filtro == "proximas":
        return proximas
    historial = list(base.exclude(_q_proximas()).order_by("-fecha", "-hora_inicio"))
    if filtro == "historial":
        return historial
    return proximas + historial


def puede_cancelar(reserva):
    """True si la reserva está confirmada y todavía no empieza."""
    return (
        reserva.estado == Reserva.Estado.CONFIRMADA
        and not _ya_empezo(reserva.fecha, reserva.hora_inicio)
    )


def ya_paso(reserva):
    return _ya_empezo(reserva.fecha, reserva.hora_inicio)


# ---------------------------------------------------------------------------
# Bloqueos
# ---------------------------------------------------------------------------

def crear_bloqueo(espacio, fecha, hora_inicio, motivo, usuario):
    """Bloquea una franja (por ejemplo, por mantenimiento).

    No deja bloquear una franja que ya tiene una reserva confirmada:
    primero hay que cancelar esa reserva, para que la persona no se
    quede con una reserva en un espacio cerrado sin saberlo.
    """
    cierre = cierre_del_dia(fecha)
    if cierre:
        raise ValidationError(f"Ese día ya está cerrado. {cierre['motivo']}.")

    if hora_inicio not in horas_del_dia(fecha):
        raise ValidationError("Esa franja no existe ese día.")

    if _ya_empezo(fecha, hora_inicio):
        raise ValidationError("No puedes bloquear una franja que ya pasó o ya empezó.")

    reserva = Reserva.objects.filter(
        espacio=espacio, fecha=fecha, hora_inicio=hora_inicio,
        estado=Reserva.Estado.CONFIRMADA,
    ).select_related("usuario").first()
    if reserva:
        nombre = reserva.usuario.get_full_name() or reserva.usuario.username
        raise ValidationError(
            f"Esa franja tiene una reserva confirmada de {nombre}. Cancélala primero."
        )

    if Bloqueo.objects.filter(espacio=espacio, fecha=fecha, hora_inicio=hora_inicio).exists():
        raise ValidationError("Esa franja ya está bloqueada.")

    return Bloqueo.objects.create(
        espacio=espacio, fecha=fecha, hora_inicio=hora_inicio,
        motivo=motivo or "Mantenimiento", creado_por=usuario,
    )


# ---------------------------------------------------------------------------
# Datos para el panel
# ---------------------------------------------------------------------------

def franjas_abiertas_del_dia(fecha, espacios_activos):
    """Cuántas franjas se podían reservar ese día en todos los espacios activos."""
    return len(horas_del_dia(fecha)) * espacios_activos
