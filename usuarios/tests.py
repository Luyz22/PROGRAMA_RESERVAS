import time as time_module
from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from espacios.models import Espacio
from reservas.models import Reserva
from reservas.utilidades_pruebas import DATOS_VALIDOS, HOY, MANANA, HoraFijaMixin

from .models import DocenteAutorizado, Perfil

CLAVE = "Cancha-Segura-2026"


def hace_anios(anios):
    hoy = timezone.localdate()
    if (hoy.month, hoy.day) == (2, 29):
        return date(hoy.year - anios, 2, 28)
    return hoy.replace(year=hoy.year - anios)


def datos_registro(**cambios):
    datos = {
        "nombre": "Ana", "apellido": "Pérez", "correo": "Ana.Perez@UNIMINUTO.edu.co",
        "fecha_nacimiento": "2000-05-20", "telefono": "300 123 4567",
        "password1": CLAVE, "password2": CLAVE, "acepta_politica": "on",
    }
    datos.update(cambios)
    return datos


def enlace_del_correo(correo):
    """Saca la ruta /cuenta/activar/<token>/ del correo enviado."""
    texto = correo.body
    inicio = texto.index("/cuenta/activar/")
    return texto[inicio:texto.index("\n", inicio)].strip()


@override_settings(VERIFICACION_CORREO_ACTIVA=True)
class RegistroTests(TestCase):
    def test_registro_crea_cuenta_inactiva_y_envia_correo(self):
        r = self.client.post(reverse("usuarios:registro"), datos_registro())
        self.assertRedirects(r, reverse("usuarios:registro_enviado"))
        u = User.objects.get(email="ana.perez@uniminuto.edu.co")
        self.assertFalse(u.is_active)
        self.assertEqual(u.perfil.tipo, Perfil.Tipo.ESTUDIANTE)
        self.assertEqual(u.perfil.fecha_nacimiento, date(2000, 5, 20))
        self.assertEqual(u.perfil.telefono, "300 123 4567")
        self.assertIsNotNone(u.perfil.acepto_politica_en)
        self.assertIsNone(u.perfil.correo_verificado_en)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["ana.perez@uniminuto.edu.co"])
        self.assertIn("/cuenta/activar/", mail.outbox[0].body)
        # No inicia sesión automáticamente.
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(self.client.get(reverse("usuarios:registro_enviado")), "ana.perez@uniminuto.edu.co")

    def test_solo_correo_institucional(self):
        r = self.client.post(reverse("usuarios:registro"), datos_registro(correo="ana@gmail.com"))
        self.assertContains(r, "Usa tu correo institucional @uniminuto.edu.co")
        r = self.client.post(reverse("usuarios:registro"), datos_registro(correo="ana@uniminuto.edu.co.falso.com"))
        self.assertContains(r, "Usa tu correo institucional")
        self.assertFalse(User.objects.exists())

    def test_registro_exige_politica(self):
        datos = datos_registro()
        del datos["acepta_politica"]
        r = self.client.post(reverse("usuarios:registro"), datos)
        self.assertContains(r, "Debes aceptar la política")
        self.assertFalse(User.objects.exists())

    def test_correo_repetido(self):
        self.client.post(reverse("usuarios:registro"), datos_registro())
        r = self.client.post(reverse("usuarios:registro"), datos_registro())
        self.assertContains(r, "falta activarla")
        self.assertEqual(User.objects.count(), 1)

    def test_fecha_futura_y_telefono(self):
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = self.client.post(reverse("usuarios:registro"), datos_registro(fecha_nacimiento=manana, telefono="abc"))
        self.assertContains(r, "no puede ser futura")
        self.assertContains(r, "teléfono válido")

    def test_menor_necesita_adulto_responsable(self):
        menor = hace_anios(17).isoformat()
        r = self.client.post(reverse("usuarios:registro"), datos_registro(fecha_nacimiento=menor))
        self.assertContains(r, "Obligatorio para menores de edad.", count=3)
        self.assertFalse(User.objects.exists())

        r = self.client.post(reverse("usuarios:registro"), datos_registro(
            fecha_nacimiento=menor, responsable_nombre="Marta Pérez",
            responsable_documento="52123456", responsable_telefono="3001234567",
        ))
        self.assertRedirects(r, reverse("usuarios:registro_enviado"))
        perfil = User.objects.get().perfil
        self.assertTrue(perfil.es_menor)
        self.assertEqual(perfil.responsable_nombre, "Marta Pérez")

    def test_mayor_de_edad_no_guarda_responsable(self):
        self.client.post(reverse("usuarios:registro"), datos_registro(
            fecha_nacimiento=hace_anios(18).isoformat(), responsable_nombre="Alguien",
        ))
        perfil = User.objects.get().perfil
        self.assertFalse(perfil.es_menor)   # cumple 18 hoy
        self.assertEqual(perfil.responsable_nombre, "")

    def test_docente_autorizado_queda_como_docente(self):
        DocenteAutorizado.objects.create(correo="ana.perez@uniminuto.edu.co")
        self.client.post(reverse("usuarios:registro"), datos_registro())
        self.assertEqual(User.objects.get().perfil.tipo, Perfil.Tipo.DOCENTE)

    def test_no_existe_rol_externo(self):
        self.assertNotIn("externo", Perfil.Tipo.values)
        self.assertEqual(Perfil._meta.get_field("tipo").default, Perfil.Tipo.ESTUDIANTE)


@override_settings(VERIFICACION_CORREO_ACTIVA=True)
class VerificacionTests(TestCase):
    def registrar(self):
        self.client.post(reverse("usuarios:registro"), datos_registro())
        return User.objects.get(), enlace_del_correo(mail.outbox[-1])

    def ingresar(self):
        return self.client.post(reverse("usuarios:ingresar"),
                                {"username": "ana.perez@uniminuto.edu.co", "password": CLAVE})

    def test_no_entra_sin_verificar(self):
        self.registrar()
        r = self.ingresar()
        self.assertContains(r, "Tu cuenta aún no está activada")
        self.assertContains(r, reverse("usuarios:reenviar"))

    def test_enlace_activa_la_cuenta(self):
        usuario, enlace = self.registrar()
        r = self.client.get(enlace)
        self.assertRedirects(r, reverse("usuarios:ingresar"))
        usuario.refresh_from_db()
        self.assertTrue(usuario.is_active)
        self.assertIsNotNone(usuario.perfil.correo_verificado_en)
        self.assertRedirects(self.ingresar(), reverse("espacios:lista"))
        # Abrir el enlace otra vez no da error.
        self.client.logout()
        self.assertRedirects(self.client.get(enlace), reverse("usuarios:ingresar"))

    def test_enlace_alterado(self):
        _, enlace = self.registrar()
        r = self.client.get(enlace[:-4] + "xyz/")
        self.assertContains(r, "El enlace no es válido.", status_code=400)
        self.assertFalse(User.objects.get().is_active)

    def test_enlace_vencido(self):
        _, enlace = self.registrar()
        horas = settings.VERIFICACION_CORREO_HORAS
        despues = time_module.time() + horas * 3600 + 60
        with patch("django.core.signing.time.time", return_value=despues):
            r = self.client.get(enlace)
        self.assertContains(r, "El enlace venció", status_code=400)
        self.assertFalse(User.objects.get().is_active)

    def test_cuenta_desactivada_por_el_admin(self):
        usuario, enlace = self.registrar()
        self.client.get(enlace)
        usuario.refresh_from_db()
        usuario.is_active = False
        usuario.save()
        r = self.client.get(enlace)
        self.assertContains(r, "desactivada", status_code=400)
        self.assertContains(self.ingresar(), "Esta cuenta está desactivada")

    def test_reenviar_enlace(self):
        self.registrar()
        r = self.client.post(reverse("usuarios:reenviar"), {"correo": "ANA.perez@uniminuto.edu.co"}, follow=True)
        self.assertContains(r, "te enviamos un enlace nuevo")
        self.assertEqual(len(mail.outbox), 2)
        # A un correo que no existe no se envía nada, pero el mensaje es el mismo.
        r = self.client.post(reverse("usuarios:reenviar"), {"correo": "nadie@uniminuto.edu.co"}, follow=True)
        self.assertContains(r, "te enviamos un enlace nuevo")
        self.assertEqual(len(mail.outbox), 2)


@override_settings(VERIFICACION_CORREO_ACTIVA=False)
class SinVerificacionTests(TestCase):
    """Con la verificación apagada la cuenta queda activa de inmediato."""

    def test_cuenta_activa_sin_correo(self):
        r = self.client.post(reverse("usuarios:registro"), datos_registro(), follow=True)
        self.assertRedirects(r, reverse("usuarios:ingresar"))
        self.assertContains(r, "Tu cuenta quedó creada")
        u = User.objects.get()
        self.assertTrue(u.is_active)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn("_auth_user_id", self.client.session)   # no inicia sesión sola

        r = self.client.post(reverse("usuarios:ingresar"),
                             {"username": "ana.perez@uniminuto.edu.co", "password": CLAVE})
        self.assertRedirects(r, reverse("espacios:lista"))

    def test_sigue_exigiendo_dominio_y_politica(self):
        r = self.client.post(reverse("usuarios:registro"), datos_registro(correo="ana@gmail.com"))
        self.assertContains(r, "Usa tu correo institucional")
        datos = datos_registro()
        del datos["acepta_politica"]
        r = self.client.post(reverse("usuarios:registro"), datos)
        self.assertContains(r, "Debes aceptar la política")
        self.assertFalse(User.objects.exists())

    def test_texto_sin_enlace(self):
        r = self.client.get(reverse("usuarios:registro"))
        self.assertNotContains(r, "te enviaremos un enlace")


class IngresoTests(TestCase):
    def test_ingreso_sin_casilla_de_politica(self):
        u = User.objects.create_user("ana@uniminuto.edu.co", email="ana@uniminuto.edu.co", password=CLAVE)
        Perfil.objects.create(usuario=u)
        r = self.client.get(reverse("usuarios:ingresar"))
        self.assertNotContains(r, "acepta_politica")
        self.assertContains(r, "Crear cuenta")
        r = self.client.post(reverse("usuarios:ingresar"), {"username": "ANA@uniminuto.edu.co", "password": CLAVE})
        self.assertRedirects(r, reverse("espacios:lista"))

    def test_ingreso_con_clave_mala(self):
        User.objects.create_user("ana@uniminuto.edu.co", email="ana@uniminuto.edu.co", password=CLAVE)
        r = self.client.post(reverse("usuarios:ingresar"), {"username": "ana@uniminuto.edu.co", "password": "otra"})
        self.assertContains(r, "Correo o contraseña incorrectos.")

    def test_crear_cuenta_solo_en_iniciar_sesion(self):
        u = User.objects.create_user("ana@uniminuto.edu.co", email="ana@uniminuto.edu.co", password=CLAVE)
        self.client.force_login(u)
        self.assertNotContains(self.client.get(reverse("espacios:lista")), reverse("usuarios:registro"))

    def test_comando_usuarios_prueba(self):
        call_command("crear_usuarios_prueba", stdout=StringIO())
        call_command("crear_usuarios_prueba", stdout=StringIO())  # dos veces no duplica
        self.assertEqual(User.objects.count(), 4)
        self.assertFalse(Perfil.objects.exclude(tipo__in=["estudiante", "docente"]).exists())
        self.assertTrue(all(u.email.endswith("@uniminuto.edu.co") for u in User.objects.all()))
        self.assertTrue(User.objects.get(email="prueba.admin@uniminuto.edu.co").is_staff)
        self.assertEqual(User.objects.get(email="prueba.docente@uniminuto.edu.co").perfil.tipo, Perfil.Tipo.DOCENTE)
        self.assertTrue(User.objects.get(email="prueba.menor@uniminuto.edu.co").perfil.es_menor)
        self.assertTrue(all(u.is_active for u in User.objects.all()))


class PantallasTests(HoraFijaMixin, TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("ana@x.co", email="ana@x.co", password=CLAVE)
        self.espacio = Espacio.objects.get(nombre="Cancha múltiple")

    def test_pide_iniciar_sesion(self):
        r = self.client.get(reverse("espacios:lista"))
        self.assertRedirects(r, reverse("usuarios:ingresar") + "?next=/espacios/")

    def test_lista_y_filtro(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("espacios:lista"))
        self.assertContains(r, "Cancha múltiple")
        self.assertContains(r, "10 a 12 personas")
        # Cancha de fútbol y Gimnasio están desactivados: no se muestran.
        self.assertNotContains(r, "Cancha de fútbol")
        r = self.client.get(reverse("espacios:lista") + "?tipo=gimnasio")
        self.assertContains(r, "No hay espacios disponibles con este filtro.")
        r = self.client.get(reverse("espacios:lista") + "?tipo=cancha")
        self.assertContains(r, "Cancha múltiple")

    def test_franjas_y_reservar(self):
        self.client.force_login(self.usuario)
        url = reverse("reservas:franjas", args=[self.espacio.pk])
        r = self.client.get(url, {"fecha": MANANA.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.context["franjas"]), 13)  # jueves: 8 am a 9 pm

        datos = {**DATOS_VALIDOS, "arl_confirmada": "on", "fecha": MANANA.isoformat(), "hora": "18:00"}
        r = self.client.post(reverse("reservas:datos", args=[self.espacio.pk]), datos, follow=True)
        self.assertContains(r, "¡Reserva confirmada!")
        self.assertTrue(Reserva.objects.filter(usuario=self.usuario, fecha=MANANA).exists())

        r = self.client.get(url, {"fecha": MANANA.isoformat()})
        estados = {str(f["inicio"]): f["estado"] for f in r.context["franjas"]}
        self.assertEqual(estados["18:00:00"], "tuya")

        # Intentar la misma franja otra vez devuelve a las franjas con el error.
        r = self.client.post(reverse("reservas:datos", args=[self.espacio.pk]), datos, follow=True)
        self.assertContains(r, "Esa franja ya está ocupada.")

    def test_fecha_invalida_usa_hoy(self):
        self.client.force_login(self.usuario)
        r = self.client.get(reverse("reservas:franjas", args=[self.espacio.pk]), {"fecha": "basura"})
        self.assertEqual(r.context["fecha"], HOY)
