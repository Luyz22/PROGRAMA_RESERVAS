from datetime import time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from espacios.models import Espacio
from reservas.servicios import crear_reserva
from usuarios.models import Perfil

CLAVE = "Cancha-Segura-2026"


class PanelBase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("jefe@x.co", email="jefe@x.co", password=CLAVE, is_staff=True)
        self.usuario = User.objects.create_user("ana@x.co", email="ana@x.co", password=CLAVE, first_name="Ana")
        Perfil.objects.create(usuario=self.usuario, tipo=Perfil.Tipo.ESTUDIANTE)
        self.client.force_login(self.admin)


class AccesoTests(PanelBase):
    def test_paginas_solo_para_admin(self):
        paginas = ["panel:inicio", "panel:espacios", "panel:espacio_nuevo",
                   "panel:reservas", "panel:usuarios", "panel:usuario_nuevo"]
        for nombre in paginas:
            self.assertEqual(self.client.get(reverse(nombre)).status_code, 200, nombre)

        self.client.force_login(self.usuario)
        for nombre in paginas:
            self.assertRedirects(self.client.get(reverse(nombre)), reverse("espacios:lista"))


class EspaciosTests(PanelBase):
    def test_crear_y_desactivar_espacio(self):
        r = self.client.post(reverse("panel:espacio_nuevo"), {
            "nombre": "Piscina", "tipo": "otro", "descripcion": "Semiolímpica", "activo": "on",
        })
        self.assertRedirects(r, reverse("panel:espacios"))
        piscina = Espacio.objects.get(nombre="Piscina")

        self.client.post(reverse("panel:espacio_editar", args=[piscina.pk]), {
            "nombre": "Piscina", "tipo": "otro", "descripcion": "",
        })
        piscina.refresh_from_db()
        self.assertFalse(piscina.activo)

    def test_nombre_repetido(self):
        r = self.client.post(reverse("panel:espacio_nuevo"), {"nombre": "gimnasio", "tipo": "gimnasio"})
        self.assertContains(r, "Ya existe un espacio con ese nombre.")


class ReservasTests(PanelBase):
    def test_filtros(self):
        manana = timezone.localdate() + timedelta(days=1)
        gimnasio = Espacio.objects.get(nombre="Gimnasio")
        crear_reserva(self.usuario, gimnasio, manana, time(9, 0))
        crear_reserva(self.admin, Espacio.objects.get(nombre="Cancha múltiple"), manana, time(9, 0))

        r = self.client.get(reverse("panel:reservas"))
        self.assertEqual(r.context["pagina"].paginator.count, 2)
        r = self.client.get(reverse("panel:reservas"), {"espacio": gimnasio.pk})
        self.assertEqual(r.context["pagina"].paginator.count, 1)
        r = self.client.get(reverse("panel:reservas"), {"q": "ana"})
        self.assertEqual(r.context["pagina"].paginator.count, 1)
        r = self.client.get(reverse("panel:reservas"), {"estado": "cancelada"})
        self.assertEqual(r.context["pagina"].paginator.count, 0)


class UsuariosTests(PanelBase):
    def test_crear_docente(self):
        r = self.client.post(reverse("panel:usuario_nuevo"), {
            "nombre": "Daniel", "apellido": "Ruiz", "correo": "Daniel@Uni.edu.co",
            "rol": "docente", "activo": "on", "password": CLAVE,
        })
        self.assertRedirects(r, reverse("panel:usuarios"))
        u = User.objects.get(email="daniel@uni.edu.co")
        self.assertEqual(u.perfil.tipo, Perfil.Tipo.DOCENTE)
        self.assertTrue(u.check_password(CLAVE))
        self.assertFalse(u.is_staff)

    def test_crear_exige_contrasena(self):
        r = self.client.post(reverse("panel:usuario_nuevo"), {
            "nombre": "D", "apellido": "R", "correo": "d@x.co", "rol": "docente", "activo": "on",
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="d@x.co").exists())

    def test_editar_sin_cambiar_contrasena_y_hacer_admin(self):
        self.client.post(reverse("panel:usuario_editar", args=[self.usuario.pk]), {
            "nombre": "Ana", "apellido": "Gómez", "correo": "ana@x.co",
            "rol": "administrador", "activo": "on", "password": "",
        })
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.is_staff)
        self.assertEqual(self.usuario.last_name, "Gómez")
        self.assertTrue(self.usuario.check_password(CLAVE))

    def test_correo_repetido(self):
        r = self.client.post(reverse("panel:usuario_nuevo"), {
            "nombre": "Otra", "apellido": "Ana", "correo": "ANA@x.co",
            "rol": "externo", "activo": "on", "password": CLAVE,
        })
        self.assertContains(r, "Ya existe una cuenta con este correo.")

    def test_admin_no_se_quita_a_si_mismo(self):
        r = self.client.post(reverse("panel:usuario_editar", args=[self.admin.pk]), {
            "nombre": "Jefe", "apellido": "X", "correo": "jefe@x.co", "rol": "externo", "password": "",
        })
        self.assertContains(r, "No puedes quitarte a ti mismo el rol de administrador.")
        self.assertContains(r, "No puedes desactivar tu propia cuenta.")
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_staff and self.admin.is_active)

    def test_buscar_y_filtrar_por_rol(self):
        r = self.client.get(reverse("panel:usuarios"), {"rol": "estudiante"})
        self.assertEqual(list(r.context["pagina"].object_list), [self.usuario])
        r = self.client.get(reverse("panel:usuarios"), {"rol": "administrador"})
        self.assertEqual(list(r.context["pagina"].object_list), [self.admin])


class IngresoAdminTests(TestCase):
    def test_admin_entra_al_panel(self):
        User.objects.create_user("jefe@x.co", email="jefe@x.co", password=CLAVE, is_staff=True)
        r = self.client.post(reverse("usuarios:ingresar"),
                             {"username": "jefe@x.co", "password": CLAVE, "acepta_politica": "on"})
        self.assertRedirects(r, reverse("panel:inicio"))
