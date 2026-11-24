from datetime import timedelta
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from espacios.models import Espacio
from reservas.models import Reserva

from .models import Perfil

CLAVE = "Cancha-Segura-2026"


class RegistroEIngresoTests(TestCase):
    def test_registro_crea_usuario_y_perfil(self):
        r = self.client.post(reverse("usuarios:registro"), {
            "nombre": "Ana", "apellido": "Pérez", "correo": "Ana@Ejemplo.com",
            "tipo": "docente",  # se ignora: quien se registra siempre es externo
            "password1": CLAVE, "password2": CLAVE, "acepta_politica": "on",
        })
        self.assertRedirects(r, reverse("espacios:lista"))
        u = User.objects.get(email="ana@ejemplo.com")
        self.assertEqual(u.perfil.tipo, Perfil.Tipo.EXTERNO)
        self.assertIsNotNone(u.perfil.acepto_politica_en)

    def test_registro_exige_politica(self):
        r = self.client.post(reverse("usuarios:registro"), {
            "nombre": "Ana", "apellido": "Pérez", "correo": "ana@x.co",
            "password1": CLAVE, "password2": CLAVE,
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_ingreso_con_correo_guarda_politica(self):
        u = User.objects.create_user("ana@x.co", email="ana@x.co", password=CLAVE)
        Perfil.objects.create(usuario=u, tipo=Perfil.Tipo.ESTUDIANTE)
        r = self.client.post(reverse("usuarios:ingresar"),
                             {"username": "ANA@x.co", "password": CLAVE, "acepta_politica": "on"})
        self.assertRedirects(r, reverse("espacios:lista"))
        u.perfil.refresh_from_db()
        self.assertIsNotNone(u.perfil.acepto_politica_en)

    def test_ingreso_exige_politica(self):
        User.objects.create_user("ana@x.co", email="ana@x.co", password=CLAVE)
        r = self.client.post(reverse("usuarios:ingresar"), {"username": "ana@x.co", "password": CLAVE})
        self.assertContains(r, "Debes aceptar la política")

    def test_ingreso_con_clave_mala(self):
        User.objects.create_user("ana@x.co", email="ana@x.co", password=CLAVE)
        r = self.client.post(reverse("usuarios:ingresar"),
                             {"username": "ana@x.co", "password": "otra", "acepta_politica": "on"})
        self.assertContains(r, "Correo o contraseña incorrectos.")

    def test_comando_usuarios_prueba(self):
        call_command("crear_usuarios_prueba", stdout=StringIO())
        call_command("crear_usuarios_prueba", stdout=StringIO())  # dos veces no duplica
        self.assertEqual(User.objects.count(), 4)
        self.assertTrue(User.objects.get(email="admin@prueba.test").is_staff)
        self.assertEqual(User.objects.get(email="docente@prueba.test").perfil.tipo, Perfil.Tipo.DOCENTE)


class PantallasTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("ana@x.co", email="ana@x.co", password=CLAVE)
        self.espacio = Espacio.objects.get(nombre="Gimnasio")

    def test_pide_iniciar_sesion(self):
        r = self.client.get(reverse("espacios:lista"))
        self.assertRedirects(r, reverse("usuarios:ingresar") + "?next=/espacios/")

    def test_lista_y_filtro(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("espacios:lista"))
        self.assertContains(r, "Cancha múltiple")
        r = self.client.get(reverse("espacios:lista") + "?tipo=gimnasio")
        self.assertContains(r, "Gimnasio")
        self.assertNotContains(r, "Cancha múltiple")

    def test_franjas_y_reservar(self):
        self.client.force_login(self.usuario)
        manana = timezone.localdate() + timedelta(days=1)
        url = reverse("reservas:franjas", args=[self.espacio.pk])
        r = self.client.get(url, {"fecha": manana.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["franjas"]), 16)

        r = self.client.post(
            reverse("reservas:reservar", args=[self.espacio.pk]),
            {"fecha": manana.isoformat(), "hora": "18:00"}, follow=True,
        )
        self.assertContains(r, "Reserva confirmada")
        self.assertTrue(Reserva.objects.filter(usuario=self.usuario, fecha=manana).exists())
        estados = {str(f["inicio"]): f["estado"] for f in r.context["franjas"]}
        self.assertEqual(estados["18:00:00"], "tuya")

        # Reservar la misma franja otra vez muestra el error.
        r = self.client.post(
            reverse("reservas:reservar", args=[self.espacio.pk]),
            {"fecha": manana.isoformat(), "hora": "18:00"}, follow=True,
        )
        self.assertContains(r, "ya está ocupada")

    def test_reservar_sin_elegir_franja(self):
        self.client.force_login(self.usuario)
        r = self.client.post(
            reverse("reservas:reservar", args=[self.espacio.pk]),
            {"fecha": timezone.localdate().isoformat()}, follow=True,
        )
        self.assertContains(r, "Elige una franja")

    def test_fecha_invalida_usa_hoy(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("reservas:franjas", args=[self.espacio.pk]), {"fecha": "basura"})
        self.assertEqual(r.context["fecha"], timezone.localdate())
