from datetime import time

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from espacios.models import Espacio
from reservas.utilidades_pruebas import MANANA, HoraFijaMixin, reservar
from usuarios.models import DocenteAutorizado, Perfil

CLAVE = "Cancha-Segura-2026"


class PanelBase(HoraFijaMixin, TestCase):
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
        manana = MANANA
        gimnasio = Espacio.objects.get(nombre="Gimnasio")
        gimnasio.activo = True  # desactivado por defecto; lo activamos para la prueba
        gimnasio.save()
        reservar(self.usuario, gimnasio, manana, time(9, 0))
        reservar(self.admin, Espacio.objects.get(nombre="Cancha múltiple"), manana, time(9, 0))

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
            "nombre": "Daniel", "apellido": "Ruiz", "correo": "Daniel@Uniminuto.edu.co",
            "rol": "docente", "activo": "on", "password": CLAVE,
        })
        self.assertRedirects(r, reverse("panel:usuarios"))
        u = User.objects.get(email="daniel@uniminuto.edu.co")
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
            "rol": "estudiante", "activo": "on", "password": CLAVE,
        })
        self.assertContains(r, "Ya existe una cuenta con este correo.")

    def test_admin_no_se_quita_a_si_mismo(self):
        r = self.client.post(reverse("panel:usuario_editar", args=[self.admin.pk]), {
            "nombre": "Jefe", "apellido": "X", "correo": "jefe@x.co", "rol": "estudiante", "password": "",
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
                             {"username": "jefe@x.co", "password": CLAVE})
        self.assertRedirects(r, reverse("panel:inicio"))


class AforoTests(PanelBase):
    def test_cancha_multiple_con_aforo_y_otros_desactivados(self):
        cancha = Espacio.objects.get(nombre="Cancha múltiple")
        self.assertEqual((cancha.aforo_minimo, cancha.aforo_maximo), (10, 12))
        self.assertTrue(cancha.activo)
        self.assertFalse(Espacio.objects.get(nombre="Cancha de fútbol").activo)
        self.assertFalse(Espacio.objects.get(nombre="Gimnasio").activo)

    def test_editar_aforo(self):
        cancha = Espacio.objects.get(nombre="Cancha múltiple")
        self.client.post(reverse("panel:espacio_editar", args=[cancha.pk]), {
            "nombre": "Cancha múltiple", "tipo": "cancha", "descripcion": "",
            "aforo_minimo": "8", "aforo_maximo": "14", "activo": "on",
        })
        cancha.refresh_from_db()
        self.assertEqual((cancha.aforo_minimo, cancha.aforo_maximo), (8, 14))

    def test_minimo_mayor_que_maximo(self):
        r = self.client.post(reverse("panel:espacio_nuevo"), {
            "nombre": "Coliseo", "tipo": "otro", "aforo_minimo": "20", "aforo_maximo": "5", "activo": "on",
        })
        self.assertContains(r, "El máximo no puede ser menor que el mínimo.")
        self.assertFalse(Espacio.objects.filter(nombre="Coliseo").exists())

    def test_aforo_vacio_es_sin_limite(self):
        self.client.post(reverse("panel:espacio_nuevo"), {"nombre": "Coliseo", "tipo": "otro", "activo": "on"})
        coliseo = Espacio.objects.get(nombre="Coliseo")
        self.assertIsNone(coliseo.aforo_maximo)
        self.assertEqual(coliseo.aforo_texto, "sin límite")


class DominioEnPanelTests(PanelBase):
    def test_estudiante_y_docente_con_correo_institucional(self):
        for rol in ("estudiante", "docente"):
            r = self.client.post(reverse("panel:usuario_nuevo"), {
                "nombre": "Leo", "apellido": "R", "correo": f"leo.{rol}@gmail.com",
                "rol": rol, "activo": "on", "password": CLAVE,
            })
            self.assertContains(r, "deben usar un correo @uniminuto.edu.co")
        self.assertFalse(User.objects.filter(first_name="Leo").exists())

    def test_administrador_puede_usar_otro_correo(self):
        r = self.client.post(reverse("panel:usuario_nuevo"), {
            "nombre": "Leo", "apellido": "R", "correo": "leo@gmail.com",
            "rol": "administrador", "activo": "on", "password": CLAVE,
        })
        self.assertRedirects(r, reverse("panel:usuarios"))

    def test_cuenta_creada_por_admin_queda_verificada(self):
        self.client.post(reverse("panel:usuario_nuevo"), {
            "nombre": "Leo", "apellido": "R", "correo": "leo@uniminuto.edu.co",
            "rol": "estudiante", "activo": "on", "password": CLAVE,
        })
        perfil = User.objects.get(email="leo@uniminuto.edu.co").perfil
        self.assertIsNotNone(perfil.correo_verificado_en)

    def test_sin_rol_externo(self):
        r = self.client.get(reverse("panel:usuario_nuevo"))
        self.assertNotContains(r, 'value="externo"')


class DocentesAutorizadosTests(PanelBase):
    def test_pegar_correos(self):
        r = self.client.post(reverse("panel:docentes"), {
            "correos": "Uno@uniminuto.edu.co, dos@uniminuto.edu.co\nuno@uniminuto.edu.co; malo@gmail.com",
        }, follow=True)
        self.assertContains(r, "2 agregados")
        self.assertContains(r, "malo@gmail.com")
        self.assertEqual(
            sorted(DocenteAutorizado.objects.values_list("correo", flat=True)),
            ["dos@uniminuto.edu.co", "uno@uniminuto.edu.co"],
        )

    def test_subir_csv(self):
        archivo = SimpleUploadedFile(
            "docentes.csv",
            "nombre,correo\nPedro,pedro@uniminuto.edu.co\nLuz,\"luz@uniminuto.edu.co\"\n".encode("utf-8-sig"),
            content_type="text/csv",
        )
        r = self.client.post(reverse("panel:docentes"), {"archivo": archivo}, follow=True)
        self.assertContains(r, "2 agregados")
        self.assertTrue(DocenteAutorizado.objects.filter(correo="luz@uniminuto.edu.co").exists())

    def test_vacio(self):
        r = self.client.post(reverse("panel:docentes"), {"correos": ""})
        self.assertContains(r, "Pega al menos un correo o sube un archivo.")

    def test_pasa_a_docente_una_cuenta_existente(self):
        u = User.objects.create_user("ana@uniminuto.edu.co", email="ana@uniminuto.edu.co", password=CLAVE)
        Perfil.objects.create(usuario=u, tipo=Perfil.Tipo.ESTUDIANTE)
        r = self.client.post(reverse("panel:docentes"), {"correos": "ana@uniminuto.edu.co"}, follow=True)
        self.assertContains(r, "1 cuentas pasaron a docente")
        u.perfil.refresh_from_db()
        self.assertEqual(u.perfil.tipo, Perfil.Tipo.DOCENTE)

    def test_quitar_no_cambia_el_rol(self):
        u = User.objects.create_user("ana@uniminuto.edu.co", email="ana@uniminuto.edu.co", password=CLAVE)
        Perfil.objects.create(usuario=u, tipo=Perfil.Tipo.DOCENTE)
        d = DocenteAutorizado.objects.create(correo="ana@uniminuto.edu.co")
        r = self.client.post(reverse("panel:quitar_docente", args=[d.pk]), follow=True)
        self.assertContains(r, "Quitaste ana@uniminuto.edu.co")
        self.assertFalse(DocenteAutorizado.objects.exists())
        u.perfil.refresh_from_db()
        self.assertEqual(u.perfil.tipo, Perfil.Tipo.DOCENTE)

    def test_solo_admin(self):
        self.client.force_login(self.usuario)
        self.assertRedirects(self.client.get(reverse("panel:docentes")), reverse("espacios:lista"))


# ---------------------------------------------------------------------------
# Fase 6: datos nuevos en reservas, usuarios con perfil ampliado y reportes
# ---------------------------------------------------------------------------

class ReservasConDatosTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.cancha = Espacio.objects.get(nombre="Cancha múltiple")
        reservar(self.usuario, self.cancha, MANANA, time(9, 0), deporte="voleibol", participantes=11, arl_nombre="Sura")
        reservar(self.admin, self.cancha, MANANA, time(10, 0), deporte="baloncesto")

    def test_tabla_muestra_deporte_participantes_y_arl(self):
        r = self.client.get(reverse("panel:reservas"))
        self.assertContains(r, "Voleibol")
        self.assertContains(r, "Sura")
        self.assertContains(r, "<td>11</td>", html=True)
        self.assertContains(r, "Recibe: Quien Recibe")

    def test_filtro_por_deporte(self):
        r = self.client.get(reverse("panel:reservas"), {"deporte": "voleibol"})
        self.assertEqual(r.context["pagina"].paginator.count, 1)


class UsuarioConPerfilTests(PanelBase):
    def datos(self, **cambios):
        datos = {
            "nombre": "Leo", "apellido": "R", "correo": "leo@uniminuto.edu.co", "rol": "estudiante",
            "activo": "on", "password": CLAVE, "fecha_nacimiento": "2001-01-15", "telefono": "3001234567",
        }
        datos.update(cambios)
        return datos

    def test_guarda_nacimiento_y_telefono(self):
        r = self.client.post(reverse("panel:usuario_nuevo"), self.datos())
        self.assertRedirects(r, reverse("panel:usuarios"))
        perfil = User.objects.get(email="leo@uniminuto.edu.co").perfil
        self.assertEqual(str(perfil.fecha_nacimiento), "2001-01-15")
        self.assertEqual(perfil.telefono, "3001234567")

    def test_menor_necesita_adulto_responsable(self):
        hoy = timezone.localdate()
        menor = hoy.replace(year=hoy.year - 15).isoformat() if (hoy.month, hoy.day) != (2, 29) else f"{hoy.year - 15}-02-28"
        r = self.client.post(reverse("panel:usuario_nuevo"), self.datos(fecha_nacimiento=menor))
        self.assertContains(r, "Obligatorio para menores de edad.", count=3)
        self.assertFalse(User.objects.filter(email="leo@uniminuto.edu.co").exists())

        r = self.client.post(reverse("panel:usuario_nuevo"), self.datos(
            fecha_nacimiento=menor, responsable_nombre="Marta", responsable_documento="123",
            responsable_telefono="3007654321",
        ))
        self.assertRedirects(r, reverse("panel:usuarios"))
        u = User.objects.get(email="leo@uniminuto.edu.co")
        self.assertTrue(u.perfil.es_menor)
        self.assertContains(self.client.get(reverse("panel:usuarios")), "Menor de edad")
        self.assertContains(self.client.get(reverse("panel:usuario_editar", args=[u.pk])), "15 años")

    def test_telefono_invalido(self):
        r = self.client.post(reverse("panel:usuario_nuevo"), self.datos(telefono="abc"))
        self.assertContains(r, "teléfono válido")

    def test_editar_conserva_datos_del_perfil(self):
        self.usuario.perfil.fecha_nacimiento = timezone.localdate().replace(year=2000, month=3, day=3)
        self.usuario.perfil.telefono = "3110000000"
        self.usuario.perfil.save()
        r = self.client.get(reverse("panel:usuario_editar", args=[self.usuario.pk]))
        self.assertContains(r, 'value="2000-03-03"')
        self.assertContains(r, 'value="3110000000"')


class ReportesTests(PanelBase):
    def setUp(self):
        super().setUp()
        self.cancha = Espacio.objects.get(nombre="Cancha múltiple")
        reservar(self.usuario, self.cancha, MANANA, time(9, 0), deporte="voleibol", participantes=11)
        reservar(self.admin, self.cancha, MANANA, time(10, 0), deporte="voleibol", participantes=10)
        cancelada = reservar(self.usuario, self.cancha, MANANA, time(11, 0), deporte="microfutbol", participantes=12)
        cancelada.estado = "cancelada"
        cancelada.save()
        self.url = reverse("panel:reportes")
        self.filtros = {"desde": MANANA.isoformat(), "hasta": MANANA.isoformat()}

    def test_resumen(self):
        r = self.client.get(self.url, self.filtros)
        resumen = r.context["resumen"]
        self.assertEqual((resumen["total"], resumen["confirmadas"], resumen["canceladas"]), (3, 2, 1))
        self.assertEqual(resumen["participantes"], 21)   # solo confirmadas
        self.assertEqual(resumen["porcentaje_canceladas"], 33)
        self.assertEqual(resumen["por_deporte"], [{"nombre": "Voleibol", "total": 2}])
        self.assertEqual(resumen["por_espacio"][0]["total"], 2)
        self.assertEqual(len(resumen["horas_mas_pedidas"]), 2)

    def test_filtros(self):
        r = self.client.get(self.url, {**self.filtros, "deporte": "microfutbol"})
        self.assertEqual(r.context["resumen"]["total"], 1)
        r = self.client.get(self.url, {"desde": "2030-01-01", "hasta": "2030-01-31"})
        self.assertEqual(r.context["resumen"]["total"], 0)
        self.assertContains(r, "No hay reservas con estos filtros.")

    def test_por_defecto_el_mes_actual(self):
        r = self.client.get(self.url)   # "hoy" en las pruebas es 2/12/2026
        self.assertEqual(r.context["filtros"]["desde"], "2026-12-01")
        self.assertEqual(r.context["filtros"]["hasta"], "2026-12-31")

    def test_csv(self):
        r = self.client.get(self.url, {**self.filtros, "formato": "csv"})
        self.assertEqual(r["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment", r["Content-Disposition"])
        texto = r.content.decode("utf-8")
        self.assertTrue(texto.startswith("\ufeff"))
        lineas = texto.lstrip("\ufeff").strip().splitlines()
        self.assertEqual(len(lineas), 4)   # encabezado + 3 reservas
        self.assertTrue(lineas[0].startswith("Fecha;Hora inicio;Hora fin;Espacio;Deporte"))
        self.assertIn("Voleibol", lineas[1])
        self.assertIn("Cancelada", texto)

    def test_csv_evita_formulas(self):
        reservar(self.usuario, self.cancha, MANANA, time(12, 0), arl_nombre="=HYPERLINK(\"x\")")
        r = self.client.get(self.url, {**self.filtros, "formato": "csv"})
        self.assertIn("'=HYPERLINK", r.content.decode("utf-8"))

    def test_solo_admin(self):
        self.client.force_login(self.usuario)
        self.assertRedirects(self.client.get(self.url), reverse("espacios:lista"))
        self.assertRedirects(self.client.get(self.url, {"formato": "csv"}), reverse("espacios:lista"))

    def test_menu_tiene_reportes(self):
        r = self.client.get(reverse("panel:inicio"))
        self.assertContains(r, self.url)
        self.assertNotContains(r, "(pronto)")

    def test_csv_hora_de_creacion_en_hora_local(self):
        from reservas.models import Reserva
        from datetime import datetime, timezone as tz
        Reserva.objects.update(creada_en=datetime(2026, 12, 2, 3, 9, tzinfo=tz.utc))   # 10:09 pm del 1/12 en Bogotá
        r = self.client.get(self.url, {**self.filtros, "formato": "csv"})
        self.assertIn("01/12/2026 22:09", r.content.decode("utf-8"))
