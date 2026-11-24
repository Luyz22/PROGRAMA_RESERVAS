from datetime import time, timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
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
