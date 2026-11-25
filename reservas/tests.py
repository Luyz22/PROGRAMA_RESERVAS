from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from espacios.models import Espacio
from usuarios.models import Perfil

from . import servicios
from .models import Bloqueo, Reserva
from .servicios import (
    cancelar_reserva,
    crear_bloqueo,
    fechas_reservables,
    franjas_del_dia,
    proxima_reserva,
)
from .utilidades_pruebas import DATOS_VALIDOS, DOMINGO, FESTIVO, HOY, LUNES, MANANA, SABADO, HoraFijaMixin, reservar

BOGOTA = ZoneInfo("America/Bogota")
CLAVE = "clave-de-prueba-123"


def con_perfil(username, tipo):
    usuario = User.objects.create_user(username, password=CLAVE)
    Perfil.objects.create(usuario=usuario, tipo=tipo)
    return usuario


class Base(HoraFijaMixin, TestCase):
    def setUp(self):
        self.espacio = Espacio.objects.get(nombre="Cancha múltiple")
        self.usuario = User.objects.create_user("ana", password=CLAVE)  # sin perfil = estudiante
        self.admin = User.objects.create_user("jefe", password=CLAVE, is_staff=True)


# ---------------------------------------------------------------------------
# Horario: días de la semana, sábados, domingos y festivos
# ---------------------------------------------------------------------------

class HorarioTests(Base):
    def test_entre_semana_de_8_am_a_9_pm(self):
        franjas = franjas_del_dia(self.espacio, MANANA)
        self.assertEqual(len(franjas), 13)
        self.assertEqual(franjas[0]["inicio"], time(8, 0))
        self.assertEqual(franjas[-1]["inicio"], time(20, 0))
        self.assertEqual(franjas[-1]["fin"], time(21, 0))
        self.assertTrue(all(f["estado"] == "libre" for f in franjas))

    def test_sabado_de_8_am_a_4_pm(self):
        franjas = franjas_del_dia(self.espacio, SABADO)
        self.assertEqual([f["inicio"].hour for f in franjas], list(range(8, 16)))
        self.assertEqual(franjas[-1]["fin"], time(16, 0))
        reservar(self.usuario, self.espacio, SABADO, time(15, 0))
        with self.assertRaisesMessage(ValidationError, "no existe"):
            reservar(self.usuario, self.espacio, SABADO, time(16, 0))

    def test_domingo_cerrado(self):
        franjas = franjas_del_dia(self.espacio, DOMINGO)
        self.assertTrue(franjas)
        self.assertTrue(all(f["estado"] == "cerrado" for f in franjas))
        with self.assertRaisesMessage(ValidationError, "domingos"):
            reservar(self.usuario, self.espacio, DOMINGO, time(10, 0))

    def test_festivo_cerrado(self):
        self.assertEqual(servicios.festivo(FESTIVO), "La Inmaculada Concepción")
        franjas = franjas_del_dia(self.espacio, FESTIVO)
        self.assertTrue(all(f["estado"] == "festivo" for f in franjas))
        with self.assertRaisesMessage(ValidationError, "Festivo"):
            reservar(self.usuario, self.espacio, FESTIVO, time(10, 0))

    def test_festivos_de_colombia(self):
        from datetime import date
        self.assertIsNotNone(servicios.festivo(date(2026, 12, 25)))   # Navidad
        self.assertIsNotNone(servicios.festivo(date(2027, 1, 1)))     # Año Nuevo
        self.assertIsNone(servicios.festivo(MANANA))

    def test_horas_del_dia(self):
        self.assertEqual(len(servicios.horas_del_dia(MANANA)), 13)
        self.assertEqual(len(servicios.horas_del_dia(SABADO)), 8)
        self.assertEqual(servicios.horas_del_dia(DOMINGO), [])
        self.assertEqual(servicios.horas_del_dia(FESTIVO), [])
        # Sin fecha: todas las horas posibles de la semana (para formularios).
        todas = servicios.horas_del_dia()
        self.assertEqual((todas[0], todas[-1]), (time(8, 0), time(20, 0)))


class HorasPasadasTests(Base):
    """Hoy es miércoles 2/12/2026 a las 10:30 am."""

    def test_franjas_de_hoy(self):
        estados = {f["inicio"].hour: f["estado"] for f in franjas_del_dia(self.espacio, HOY)}
        self.assertEqual(estados[8], "pasada")
        self.assertEqual(estados[10], "pasada")   # ya empezó
        self.assertEqual(estados[11], "libre")

    def test_no_reservar_hora_pasada(self):
        with self.assertRaisesMessage(ValidationError, "ya pasó"):
            reservar(self.usuario, self.espacio, HOY, time(9, 0))
        reservar(self.usuario, self.espacio, HOY, time(11, 0))

    def test_no_reservar_fecha_pasada(self):
        with self.assertRaisesMessage(ValidationError, "Esa fecha ya pasó"):
            reservar(self.usuario, self.espacio, HOY - timedelta(days=1), time(11, 0))

    def test_no_cancelar_reserva_que_ya_empezo(self):
        r = Reserva.objects.create(usuario=self.usuario, espacio=self.espacio, fecha=HOY, hora_inicio=time(10, 0))
        with self.assertRaisesMessage(ValidationError, "ya comenzó"):
            cancelar_reserva(r, self.usuario)

    def test_primer_dia_disponible_salta_el_domingo(self):
        sabado_tarde = datetime(2026, 12, 5, 15, 30, tzinfo=BOGOTA)
        with patch("reservas.servicios.ahora", return_value=sabado_tarde):
            self.assertEqual(servicios.primer_dia_disponible(self.usuario), LUNES)


# ---------------------------------------------------------------------------
# Anticipación según el rol
# ---------------------------------------------------------------------------

class VentanaPorRolTests(Base):
    def test_roles(self):
        self.assertEqual(servicios.rol_de(self.usuario), "estudiante")   # sin perfil
        self.assertEqual(servicios.rol_de(self.admin), "administrador")
        self.assertEqual(servicios.rol_de(con_perfil("doc", "docente")), "docente")

    def test_estudiante_7_dias(self):
        dias = fechas_reservables(self.usuario)
        self.assertEqual((dias[0], dias[-1]), (HOY, HOY + timedelta(days=7)))
        reservar(self.usuario, self.espacio, HOY + timedelta(days=7), time(9, 0))
        with self.assertRaisesMessage(ValidationError, "7 días"):
            reservar(self.usuario, self.espacio, HOY + timedelta(days=8), time(9, 0))

    def test_docente_30_dias(self):
        docente = con_perfil("doc", "docente")
        self.assertEqual(servicios.fecha_maxima(docente), HOY + timedelta(days=30))
        reservar(docente, self.espacio, HOY + timedelta(days=29), time(9, 0))   # jueves 31/12
        with self.assertRaisesMessage(ValidationError, "30 días"):
            reservar(docente, self.espacio, HOY + timedelta(days=31), time(9, 0))

    def test_administrador_365_dias(self):
        self.assertEqual(servicios.fecha_maxima(self.admin), HOY + timedelta(days=365))
        reservar(self.admin, self.espacio, HOY + timedelta(days=365), time(9, 0))   # jueves 2/12/2027
        with self.assertRaisesMessage(ValidationError, "365 días"):
            reservar(self.admin, self.espacio, HOY + timedelta(days=366), time(9, 0))


# ---------------------------------------------------------------------------
# Crear, cancelar y bloquear
# ---------------------------------------------------------------------------

class ReservasTests(Base):
    def test_crear_ocupar_bloquear_y_cancelar(self):
        r = reservar(self.usuario, self.espacio, MANANA, time(17, 0))
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADA)

        with self.assertRaisesMessage(ValidationError, "ya está ocupada"):
            reservar(self.admin, self.espacio, MANANA, time(17, 0))

        Bloqueo.objects.create(espacio=self.espacio, fecha=MANANA, hora_inicio=time(20, 0))
        with self.assertRaisesMessage(ValidationError, "mantenimiento"):
            reservar(self.usuario, self.espacio, MANANA, time(20, 0))

        cancelar_reserva(r, self.usuario)
        self.assertEqual(r.estado, Reserva.Estado.CANCELADA)
        reservar(self.usuario, self.espacio, MANANA, time(17, 0))   # quedó libre

    def test_doble_reserva_misma_hora(self):
        otro = Espacio.objects.get(nombre="Gimnasio")
        otro.activo = True
        otro.save()
        reservar(self.usuario, self.espacio, MANANA, time(9, 0))
        with self.assertRaisesMessage(ValidationError, "mismo horario"):
            reservar(self.usuario, otro, MANANA, time(9, 0))

    def test_no_cancelar_reserva_ajena(self):
        r = reservar(self.usuario, self.espacio, MANANA, time(8, 0))
        with self.assertRaises(ValidationError):
            cancelar_reserva(r, User.objects.create_user("otro", password=CLAVE))

    def test_espacio_desactivado(self):
        gimnasio = Espacio.objects.get(nombre="Gimnasio")
        with self.assertRaisesMessage(ValidationError, "no está disponible"):
            reservar(self.usuario, gimnasio, MANANA, time(9, 0))

    def test_proxima_reserva_es_la_mas_cercana(self):
        self.assertIsNone(proxima_reserva(self.usuario))
        reservar(self.usuario, self.espacio, LUNES, time(8, 0))
        cerca = reservar(self.usuario, self.espacio, MANANA, time(19, 0))
        self.assertEqual(proxima_reserva(self.usuario), cerca)
        cancelar_reserva(cerca, self.usuario)
        self.assertNotEqual(proxima_reserva(self.usuario), cerca)


class BloqueosTests(Base):
    def test_bloqueo_no_pisa_reservas(self):
        reservar(self.usuario, self.espacio, MANANA, time(10, 0))
        with self.assertRaisesMessage(ValidationError, "Cancélala primero"):
            crear_bloqueo(self.espacio, MANANA, time(10, 0), "Pintura", self.admin)

        b = crear_bloqueo(self.espacio, MANANA, time(11, 0), "", self.admin)
        self.assertEqual(b.motivo, "Mantenimiento")
        with self.assertRaisesMessage(ValidationError, "ya está bloqueada"):
            crear_bloqueo(self.espacio, MANANA, time(11, 0), "", self.admin)

    def test_bloqueo_respeta_el_horario(self):
        with self.assertRaisesMessage(ValidationError, "no existe ese día"):
            crear_bloqueo(self.espacio, SABADO, time(17, 0), "", self.admin)
        with self.assertRaisesMessage(ValidationError, "ya está cerrado"):
            crear_bloqueo(self.espacio, DOMINGO, time(10, 0), "", self.admin)
        with self.assertRaisesMessage(ValidationError, "ya está cerrado"):
            crear_bloqueo(self.espacio, FESTIVO, time(10, 0), "", self.admin)
        with self.assertRaisesMessage(ValidationError, "ya pasó"):
            crear_bloqueo(self.espacio, HOY, time(9, 0), "", self.admin)


# ---------------------------------------------------------------------------
# Pantallas
# ---------------------------------------------------------------------------

class PantallaFranjasTests(Base):
    def url(self, **params):
        return reverse("reservas:franjas", args=[self.espacio.pk]), params

    def test_domingo_se_ve_cerrado(self):
        self.client.force_login(self.usuario)
        r = self.client.get(*self.url(fecha=DOMINGO.isoformat()))
        self.assertContains(r, "Los domingos no hay servicio")
        self.assertFalse(r.context["hay_libres"])

    def test_festivo_se_ve_festivo(self):
        self.client.force_login(self.usuario)
        r = self.client.get(*self.url(fecha=FESTIVO.isoformat()))
        self.assertContains(r, "Festivo: La Inmaculada Concepción")

    def test_fecha_fuera_de_la_ventana_usa_el_primer_dia_disponible(self):
        self.client.force_login(self.usuario)
        r = self.client.get(*self.url(fecha=(HOY + timedelta(days=20)).isoformat()))
        self.assertEqual(r.context["fecha"], HOY)
        r = self.client.get(*self.url(fecha="basura"))
        self.assertEqual(r.context["fecha"], HOY)

    def test_selector_de_semanas_para_docente(self):
        docente = con_perfil("doc", "docente")
        self.client.force_login(docente)
        r = self.client.get(*self.url(fecha=(HOY + timedelta(days=20)).isoformat()))
        self.assertEqual(r.context["fecha"], HOY + timedelta(days=20))
        self.assertTrue(r.context["ventana_larga"])
        self.assertContains(r, "Ir a una fecha")
        self.assertEqual(len(r.context["dias"]), 7)
        self.assertIsNotNone(r.context["anterior"])

    def test_estudiante_no_ve_ir_a_fecha(self):
        self.client.force_login(self.usuario)
        r = self.client.get(*self.url())
        self.assertNotContains(r, "Ir a una fecha")


class PanelTests(Base):
    def test_solo_admin_entra_al_panel(self):
        self.client.force_login(self.usuario)
        self.assertRedirects(self.client.get(reverse("panel:inicio")), reverse("espacios:lista"))
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("panel:inicio")), "Panel de administración")

    def test_ocupacion_segun_el_horario_de_hoy(self):
        reservar(self.usuario, self.espacio, HOY, time(11, 0))
        reservar(self.admin, self.espacio, HOY, time(12, 0))
        self.client.force_login(self.admin)
        r = self.client.get(reverse("panel:inicio"))
        # 2 de 13 franjas del miércoles en el único espacio activo.
        self.assertEqual(r.context["ocupacion"], round(100 * 2 / 13))

    def test_panel_en_domingo(self):
        domingo = datetime(2026, 12, 6, 9, 0, tzinfo=BOGOTA)
        self.client.force_login(self.admin)
        with patch("reservas.servicios.ahora", return_value=domingo):
            r = self.client.get(reverse("panel:inicio"))
        self.assertEqual(r.context["ocupacion"], 0)
        self.assertContains(r, "Hoy no hay servicio")

    def test_bloquear_y_quitar_desde_el_panel(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("panel:bloquear"), {
            "espacio": self.espacio.pk, "fecha": MANANA.isoformat(),
            "hora": "15:00", "motivo": "Arreglo de la malla",
        }, follow=True)
        self.assertContains(r, "Bloqueaste Cancha múltiple")
        b = Bloqueo.objects.get()
        estados = {f["inicio"]: f["estado"] for f in franjas_del_dia(self.espacio, MANANA)}
        self.assertEqual(estados[time(15, 0)], "mantenimiento")

        r = self.client.post(reverse("panel:quitar_bloqueo", args=[b.pk]), follow=True)
        self.assertContains(r, "La franja quedó libre")
        self.assertFalse(Bloqueo.objects.exists())

    def test_bloqueo_con_datos_incompletos(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("panel:bloquear"), {"espacio": self.espacio.pk}, follow=True)
        self.assertContains(r, "Completa el espacio, la fecha y la franja.")

    def test_usuario_normal_no_puede_bloquear(self):
        self.client.force_login(self.usuario)
        self.client.post(reverse("panel:bloquear"), {
            "espacio": self.espacio.pk, "fecha": MANANA.isoformat(), "hora": "15:00",
        })
        self.assertFalse(Bloqueo.objects.exists())

    def test_admin_cancela_reserva_ajena(self):
        r = reservar(self.usuario, self.espacio, MANANA, time(9, 0))
        self.client.force_login(self.admin)
        self.client.post(reverse("reservas:cancelar", args=[r.pk]), {"volver": reverse("panel:inicio")})
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CANCELADA)

    def test_usuario_no_cancela_reserva_ajena(self):
        r = reservar(self.admin, self.espacio, MANANA, time(9, 0))
        self.client.force_login(self.usuario)
        self.client.post(reverse("reservas:cancelar", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADA)

    def test_tarjeta_proxima_reserva(self):
        reservar(self.usuario, self.espacio, MANANA, time(18, 0))
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("espacios:lista"))
        self.assertContains(r, "Tu próxima reserva")
        self.assertContains(r, "6:00 pm – 7:00 pm")


# ---------------------------------------------------------------------------
# Datos de la reserva: deporte, aforo, ARL y quién recibe (Fase 4)
# ---------------------------------------------------------------------------

class DatosReservaTests(Base):
    def errores(self, **cambios):
        with self.assertRaises(ValidationError) as ctx:
            reservar(self.usuario, self.espacio, MANANA, time(9, 0), **cambios)
        return ctx.exception.message_dict

    def test_guarda_los_datos(self):
        r = reservar(self.usuario, self.espacio, MANANA, time(9, 0), deporte="voleibol", participantes="12")
        r.refresh_from_db()
        self.assertEqual(r.deporte, "voleibol")
        self.assertEqual(r.get_deporte_display(), "Voleibol")
        self.assertEqual(r.participantes, 12)
        self.assertEqual(r.arl_nombre, "Positiva")
        self.assertTrue(r.arl_confirmada)
        self.assertEqual((r.recibe_nombre, r.recibe_correo), ("Quien Recibe", "recibe@uniminuto.edu.co"))

    def test_deportes_de_la_cancha(self):
        self.assertEqual(
            [valor for valor, _ in servicios.deportes_de(self.espacio)],
            ["microfutbol", "baloncesto", "voleibol"],
        )
        self.assertEqual(dict(servicios.deportes_de(self.espacio))["microfutbol"], "Fútbol (microfútbol)")
        self.assertIn("deporte", self.errores(deporte=""))
        self.assertIn("deporte", self.errores(deporte="tenis"))

    def test_aforo(self):
        self.assertIn("al menos 10", self.errores(participantes=9)["participantes"][0])
        self.assertIn("máximo 12", self.errores(participantes=13)["participantes"][0])
        self.assertIn("participantes", self.errores(participantes="muchos"))
        reservar(self.usuario, self.espacio, MANANA, time(9, 0), participantes=10)
        reservar(self.usuario, self.espacio, MANANA, time(10, 0), participantes=12)

    def test_espacio_sin_aforo(self):
        otro = Espacio.objects.create(nombre="Sala", tipo="otro")
        reservar(self.usuario, otro, MANANA, time(9, 0), participantes=40, deporte="")

    def test_arl(self):
        self.assertIn("arl_nombre", self.errores(arl_nombre="  "))
        self.assertIn("arl_confirmada", self.errores(arl_confirmada=False))

    def test_quien_recibe(self):
        self.assertIn("recibe_nombre", self.errores(recibe_nombre=""))
        self.assertIn("recibe_correo", self.errores(recibe_correo=""))
        self.assertIn("@uniminuto.edu.co", self.errores(recibe_correo="otro@gmail.com")["recibe_correo"][0])

    def test_varios_errores_a_la_vez(self):
        errores = self.errores(participantes=3, arl_nombre="", arl_confirmada=False)
        self.assertEqual(set(errores), {"participantes", "arl_nombre", "arl_confirmada"})
        self.assertFalse(Reserva.objects.exists())

    def test_recordatorios(self):
        textos = " ".join(servicios.recordatorios(self.usuario))
        self.assertIn("carnet de UNIMINUTO", textos)
        self.assertIn("10 minutos antes", textos)
        self.assertNotIn("adulto responsable", textos)
        menor = con_perfil("menor", "estudiante")
        menor.perfil.fecha_nacimiento = HOY.replace(year=HOY.year - 15)
        menor.perfil.save()
        self.assertIn("adulto responsable", " ".join(servicios.recordatorios(menor)))


class CorreosReservaTests(Base):
    def setUp(self):
        super().setUp()
        self.usuario.email = "ana@uniminuto.edu.co"
        self.usuario.save()

    def test_correo_al_confirmar(self):
        reservar(self.usuario, self.espacio, MANANA, time(17, 0))
        self.assertEqual(len(mail.outbox), 1)
        correo = mail.outbox[0]
        self.assertEqual(correo.to, ["ana@uniminuto.edu.co", "recibe@uniminuto.edu.co"])
        self.assertIn("Reserva confirmada", correo.subject)
        self.assertIn("5:00 pm – 6:00 pm", correo.body)
        self.assertIn("Fútbol (microfútbol)", correo.body)
        self.assertIn("carnet de UNIMINUTO", correo.body)
        self.assertIn("10 minutos antes", correo.body)

    def test_un_solo_destinatario_si_recibe_quien_reserva(self):
        reservar(self.usuario, self.espacio, MANANA, time(17, 0), recibe_correo="ANA@uniminuto.edu.co")
        self.assertEqual(mail.outbox[0].to, ["ana@uniminuto.edu.co"])

    def test_correo_al_cancelar(self):
        r = reservar(self.usuario, self.espacio, MANANA, time(17, 0))
        cancelar_reserva(r, self.usuario)
        self.assertIn("Reserva cancelada", mail.outbox[-1].subject)
        self.assertIn("Cancelaste tu reserva", mail.outbox[-1].body)

        r2 = reservar(self.usuario, self.espacio, MANANA, time(18, 0))
        cancelar_reserva(r2, self.admin)
        self.assertIn("El administrador de espacios canceló", mail.outbox[-1].body)

    def test_correo_menor_de_edad(self):
        menor = con_perfil("menor", "estudiante")
        menor.email = "menor@uniminuto.edu.co"
        menor.save()
        menor.perfil.fecha_nacimiento = HOY.replace(year=HOY.year - 15)
        menor.perfil.save()
        reservar(menor, self.espacio, MANANA, time(17, 0))
        self.assertIn("adulto responsable", mail.outbox[-1].body)

    def test_si_el_correo_falla_la_reserva_queda(self):
        with patch("reservas.servicios.send_mail", side_effect=OSError("sin red")):
            with self.assertLogs("reservas.servicios", level="ERROR"):
                r = reservar(self.usuario, self.espacio, MANANA, time(17, 0))
        self.assertTrue(Reserva.objects.filter(pk=r.pk).exists())


class FlujoReservaTests(Base):
    """Franjas -> Continuar -> datos -> confirmación."""

    def setUp(self):
        super().setUp()
        self.usuario.first_name, self.usuario.last_name = "Ana", "Pérez"
        self.usuario.email = "ana@uniminuto.edu.co"
        self.usuario.save()
        self.client.force_login(self.usuario)
        self.url_datos = reverse("reservas:datos", args=[self.espacio.pk])

    def post_datos(self, **cambios):
        datos = {**DATOS_VALIDOS, "arl_confirmada": "on", "fecha": MANANA.isoformat(), "hora": "17:00"}
        datos.update(cambios)
        return self.client.post(self.url_datos, {k: v for k, v in datos.items() if v is not None})

    def test_franjas_tiene_boton_continuar(self):
        r = self.client.get(reverse("reservas:franjas", args=[self.espacio.pk]), {"fecha": MANANA.isoformat()})
        self.assertContains(r, "Continuar")
        self.assertContains(r, self.url_datos)

    def test_formulario_con_datos_por_defecto(self):
        r = self.client.get(self.url_datos, {"fecha": MANANA.isoformat(), "hora": "17:00"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Fútbol (microfútbol)")
        self.assertContains(r, 'value="Ana Pérez"')
        self.assertContains(r, 'value="ana@uniminuto.edu.co"')
        self.assertContains(r, "carnet de UNIMINUTO")
        self.assertContains(r, "10 minutos antes")
        self.assertContains(r, "10 a 12 personas")

    def test_franja_ocupada_vuelve_a_franjas(self):
        reservar(self.admin, self.espacio, MANANA, time(17, 0))
        r = self.client.get(self.url_datos, {"fecha": MANANA.isoformat(), "hora": "17:00"}, follow=True)
        self.assertContains(r, "ya está ocupada")
        self.assertEqual(r.request["PATH_INFO"], reverse("reservas:franjas", args=[self.espacio.pk]))

    def test_sin_franja(self):
        r = self.client.get(self.url_datos, {"fecha": MANANA.isoformat()}, follow=True)
        self.assertContains(r, "Elige una franja antes de continuar.")

    def test_confirmar_y_ver_confirmacion(self):
        r = self.post_datos()
        reserva = Reserva.objects.get()
        self.assertRedirects(r, reverse("reservas:confirmacion", args=[reserva.pk]))
        r = self.client.get(reverse("reservas:confirmacion", args=[reserva.pk]))
        self.assertContains(r, "¡Reserva confirmada!")
        self.assertContains(r, "Positiva")
        self.assertContains(r, "carnet de UNIMINUTO")
        self.assertEqual(len(mail.outbox), 1)

    def test_errores_se_muestran_en_el_formulario(self):
        r = self.post_datos(participantes="20", arl_confirmada=None)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "máximo 12")
        self.assertContains(r, "Debes confirmar que todos los participantes")
        self.assertFalse(Reserva.objects.exists())

    def test_otro_usuario_no_ve_la_confirmacion(self):
        reserva = reservar(self.admin, self.espacio, MANANA, time(9, 0))
        r = self.client.get(reverse("reservas:confirmacion", args=[reserva.pk]))
        self.assertEqual(r.status_code, 404)

    def test_menor_ve_recordatorio_del_adulto(self):
        Perfil.objects.create(usuario=self.usuario, fecha_nacimiento=HOY.replace(year=HOY.year - 16))
        r = self.client.get(self.url_datos, {"fecha": MANANA.isoformat(), "hora": "17:00"})
        self.assertContains(r, "debes asistir con tu adulto responsable")


# ---------------------------------------------------------------------------
# Mis reservas (Fase 5)
# ---------------------------------------------------------------------------

class MisReservasTests(Base):
    """Hoy es miércoles 2/12/2026 a las 10:30 am."""

    def setUp(self):
        super().setUp()
        # Próximas
        self.manana = reservar(self.usuario, self.espacio, MANANA, time(9, 0))
        self.lunes = reservar(self.usuario, self.espacio, LUNES, time(9, 0))
        # En curso: empezó a las 10:00 y termina a las 11:00
        self.en_curso = Reserva.objects.create(
            usuario=self.usuario, espacio=self.espacio, fecha=HOY, hora_inicio=time(10, 0), deporte="baloncesto",
        )
        # Historial: una pasada y una cancelada
        self.pasada = Reserva.objects.create(
            usuario=self.usuario, espacio=self.espacio, fecha=HOY - timedelta(days=3), hora_inicio=time(9, 0),
        )
        self.cancelada = reservar(self.usuario, self.espacio, MANANA, time(15, 0))
        cancelar_reserva(self.cancelada, self.usuario)
        # De otra persona: no debe aparecer
        self.ajena = reservar(self.admin, self.espacio, MANANA, time(12, 0))
        self.client.force_login(self.usuario)

    def lista(self, filtro=None):
        params = {"filtro": filtro} if filtro else {}
        return list(self.client.get(reverse("reservas:mis_reservas"), params).context["pagina"].object_list)

    def test_proximas(self):
        self.assertEqual(self.lista("proximas"), [self.en_curso, self.manana, self.lunes])

    def test_historial(self):
        self.assertEqual(self.lista("historial"), [self.cancelada, self.pasada])

    def test_todas(self):
        self.assertEqual(
            self.lista(),
            [self.en_curso, self.manana, self.lunes, self.cancelada, self.pasada],
        )
        self.assertNotIn(self.ajena, self.lista())

    def test_filtro_desconocido_usa_todas(self):
        self.assertEqual(len(self.lista("cualquiera")), 5)

    def test_boton_cancelar_solo_donde_corresponde(self):
        r = self.client.get(reverse("reservas:mis_reservas"))
        cancelables = {res.pk for res in r.context["pagina"].object_list if res.cancelable}
        self.assertEqual(cancelables, {self.manana.pk, self.lunes.pk})
        self.assertContains(r, reverse("reservas:cancelar", args=[self.manana.pk]))
        self.assertNotContains(r, reverse("reservas:cancelar", args=[self.en_curso.pk]))
        self.assertNotContains(r, reverse("reservas:cancelar", args=[self.pasada.pk]))

    def test_cancelar_desde_mis_reservas(self):
        url = reverse("reservas:mis_reservas") + "?filtro=proximas"
        r = self.client.post(reverse("reservas:cancelar", args=[self.manana.pk]), {"volver": url}, follow=True)
        self.assertRedirects(r, url)
        self.assertContains(r, "Cancelaste tu reserva")
        self.manana.refresh_from_db()
        self.assertEqual(self.manana.estado, Reserva.Estado.CANCELADA)
        self.assertNotIn(self.manana, self.lista("proximas"))
        self.assertIn(self.manana, self.lista("historial"))

    def test_estados_y_textos(self):
        r = self.client.get(reverse("reservas:mis_reservas"))
        self.assertContains(r, "Confirmada")
        self.assertContains(r, "Cancelada")
        self.assertContains(r, "Ya pasó")
        self.assertContains(r, "Baloncesto")

    def test_vacio(self):
        self.client.force_login(con_perfil("nuevo", "estudiante"))
        r = self.client.get(reverse("reservas:mis_reservas"), {"filtro": "proximas"})
        self.assertContains(r, "No tienes reservas próximas.")

    def test_menu_tiene_mis_reservas(self):
        r = self.client.get(reverse("espacios:lista"))
        self.assertContains(r, reverse("reservas:mis_reservas"))

    def test_pide_iniciar_sesion(self):
        self.client.logout()
        r = self.client.get(reverse("reservas:mis_reservas"))
        self.assertRedirects(r, reverse("usuarios:ingresar") + "?next=" + reverse("reservas:mis_reservas"))

    def test_confirmacion_de_reserva_pasada_sin_cancelar(self):
        r = self.client.get(reverse("reservas:confirmacion", args=[self.pasada.pk]))
        self.assertContains(r, "Reserva realizada")
        self.assertNotContains(r, reverse("reservas:cancelar", args=[self.pasada.pk]))

    def test_franja_propia_enlaza_al_detalle(self):
        r = self.client.get(reverse("reservas:franjas", args=[self.espacio.pk]), {"fecha": MANANA.isoformat()})
        self.assertContains(r, reverse("reservas:confirmacion", args=[self.manana.pk]))
        self.assertContains(r, "Ya pasó")
