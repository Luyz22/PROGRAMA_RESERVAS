from datetime import time, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from espacios.models import Espacio

from .models import Bloqueo, Reserva
from .servicios import (
    cancelar_reserva,
    crear_reserva,
    fechas_reservables,
    franjas_del_dia,
)


class ServiciosTests(TestCase):
    """Repite la prueba del Paso 4 de forma automática."""

    def setUp(self):
        self.espacio = Espacio.objects.get(nombre="Cancha de fútbol")
        self.usuario = User.objects.create_user("prueba", password="clave-de-prueba-123")
        self.manana = timezone.localdate() + timedelta(days=1)

    def test_siete_dias_desde_hoy(self):
        dias = fechas_reservables()
        self.assertEqual(len(dias), 7)
        self.assertEqual(dias[0], timezone.localdate())

    def test_dieciseis_franjas_libres(self):
        franjas = franjas_del_dia(self.espacio, self.manana)
        self.assertEqual(len(franjas), 16)
        self.assertEqual(franjas[0]["inicio"], time(6, 0))
        self.assertEqual(franjas[-1]["fin"], time(22, 0))
        self.assertTrue(all(f["estado"] == "libre" for f in franjas))

    def test_crear_ocupar_bloquear_y_cancelar(self):
        r = crear_reserva(self.usuario, self.espacio, self.manana, time(17, 0))
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADA)

        with self.assertRaisesMessage(ValidationError, "ya está ocupada"):
            crear_reserva(self.usuario, self.espacio, self.manana, time(17, 0))

        Bloqueo.objects.create(espacio=self.espacio, fecha=self.manana, hora_inicio=time(20, 0))
        with self.assertRaisesMessage(ValidationError, "mantenimiento"):
            crear_reserva(self.usuario, self.espacio, self.manana, time(20, 0))

        cancelar_reserva(r, self.usuario)
        self.assertEqual(r.estado, Reserva.Estado.CANCELADA)

        # La franja cancelada queda libre de nuevo.
        crear_reserva(self.usuario, self.espacio, self.manana, time(17, 0))

    def test_no_cancelar_reserva_ajena(self):
        r = crear_reserva(self.usuario, self.espacio, self.manana, time(8, 0))
        otro = User.objects.create_user("otro", password="clave-de-prueba-123")
        with self.assertRaises(ValidationError):
            cancelar_reserva(r, otro)

    def test_fuera_de_los_siete_dias(self):
        lejos = timezone.localdate() + timedelta(days=10)
        with self.assertRaisesMessage(ValidationError, "7 días"):
            crear_reserva(self.usuario, self.espacio, lejos, time(8, 0))


class ProximaReservaYBloqueoTests(TestCase):
    def setUp(self):
        self.espacio = Espacio.objects.get(nombre="Gimnasio")
        self.usuario = User.objects.create_user("ana", password="clave-de-prueba-123")
        self.admin = User.objects.create_user("jefe", password="clave-de-prueba-123", is_staff=True)
        self.manana = timezone.localdate() + timedelta(days=1)

    def test_proxima_reserva_es_la_mas_cercana(self):
        from .servicios import proxima_reserva

        self.assertIsNone(proxima_reserva(self.usuario))
        crear_reserva(self.usuario, self.espacio, self.manana + timedelta(days=1), time(8, 0))
        cerca = crear_reserva(self.usuario, self.espacio, self.manana, time(19, 0))
        self.assertEqual(proxima_reserva(self.usuario), cerca)

        cancelar_reserva(cerca, self.usuario)
        self.assertNotEqual(proxima_reserva(self.usuario), cerca)

    def test_bloqueo_no_pisa_reservas(self):
        from .servicios import crear_bloqueo

        crear_reserva(self.usuario, self.espacio, self.manana, time(10, 0))
        with self.assertRaisesMessage(ValidationError, "Cancélala primero"):
            crear_bloqueo(self.espacio, self.manana, time(10, 0), "Pintura", self.admin)

        b = crear_bloqueo(self.espacio, self.manana, time(11, 0), "", self.admin)
        self.assertEqual(b.motivo, "Mantenimiento")
        with self.assertRaisesMessage(ValidationError, "ya está bloqueada"):
            crear_bloqueo(self.espacio, self.manana, time(11, 0), "", self.admin)
        with self.assertRaisesMessage(ValidationError, "no existe"):
            crear_bloqueo(self.espacio, self.manana, time(23, 0), "", self.admin)


class PanelTests(TestCase):
    def setUp(self):
        self.espacio = Espacio.objects.get(nombre="Cancha múltiple")
        self.usuario = User.objects.create_user("ana", password="clave-de-prueba-123")
        self.admin = User.objects.create_user("jefe", password="clave-de-prueba-123", is_staff=True)
        self.manana = timezone.localdate() + timedelta(days=1)

    def test_solo_admin_entra_al_panel(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("reservas:panel"))
        self.assertRedirects(r, reverse("espacios:lista"))

        self.client.force_login(self.admin)
        r = self.client.get(reverse("reservas:panel"))
        self.assertContains(r, "Panel de administración")

    def test_bloquear_y_quitar_desde_el_panel(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("reservas:bloquear"), {
            "espacio": self.espacio.pk, "fecha": self.manana.isoformat(),
            "hora": "15:00", "motivo": "Arreglo de la malla",
        }, follow=True)
        self.assertContains(r, "Bloqueaste Cancha múltiple")
        b = Bloqueo.objects.get()
        estados = {f["inicio"]: f["estado"] for f in franjas_del_dia(self.espacio, self.manana)}
        self.assertEqual(estados[time(15, 0)], "mantenimiento")

        r = self.client.post(reverse("reservas:quitar_bloqueo", args=[b.pk]), follow=True)
        self.assertContains(r, "La franja quedó libre")
        self.assertFalse(Bloqueo.objects.exists())

    def test_bloqueo_con_datos_incompletos(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("reservas:bloquear"), {"espacio": self.espacio.pk}, follow=True)
        self.assertContains(r, "Completa el espacio, la fecha y la franja.")

    def test_usuario_normal_no_puede_bloquear(self):
        self.client.force_login(self.usuario)
        self.client.post(reverse("reservas:bloquear"), {
            "espacio": self.espacio.pk, "fecha": self.manana.isoformat(), "hora": "15:00",
        })
        self.assertFalse(Bloqueo.objects.exists())

    def test_admin_cancela_reserva_ajena(self):
        r = crear_reserva(self.usuario, self.espacio, self.manana, time(9, 0))
        self.client.force_login(self.admin)
        self.client.post(reverse("reservas:cancelar", args=[r.pk]), {"volver": reverse("reservas:panel")})
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CANCELADA)

    def test_usuario_no_cancela_reserva_ajena(self):
        r = crear_reserva(self.admin, self.espacio, self.manana, time(9, 0))
        self.client.force_login(self.usuario)
        self.client.post(reverse("reservas:cancelar", args=[r.pk]))
        r.refresh_from_db()
        self.assertEqual(r.estado, Reserva.Estado.CONFIRMADA)

    def test_tarjeta_proxima_reserva(self):
        crear_reserva(self.usuario, self.espacio, self.manana, time(18, 0))
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("espacios:lista"))
        self.assertContains(r, "Tu próxima reserva")
        self.assertContains(r, "6:00 pm – 7:00 pm")
