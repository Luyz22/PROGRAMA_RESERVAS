"""Ayudas para las pruebas: fijan "hoy" para que no dependan del día en que se corren.

Fecha fija: miércoles 2 de diciembre de 2026, 10:30 am (hora de Bogotá).
Cerca de ella hay un sábado (5/12), un domingo (6/12) y un festivo
(martes 8/12, Inmaculada Concepción).
"""

from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

AHORA_FIJA = datetime(2026, 12, 2, 10, 30, tzinfo=ZoneInfo("America/Bogota"))
HOY = AHORA_FIJA.date()               # miércoles 2/12/2026
MANANA = date(2026, 12, 3)            # jueves
SABADO = date(2026, 12, 5)
DOMINGO = date(2026, 12, 6)
LUNES = date(2026, 12, 7)
FESTIVO = date(2026, 12, 8)           # martes festivo


class HoraFijaMixin:
    """Ponlo antes de TestCase: class MisPruebas(HoraFijaMixin, TestCase)."""

    ahora_fija = AHORA_FIJA

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._parche_ahora = patch("reservas.servicios.ahora", return_value=cls.ahora_fija)
        cls._parche_ahora.start()

    @classmethod
    def tearDownClass(cls):
        cls._parche_ahora.stop()
        super().tearDownClass()


DATOS_VALIDOS = {
    "deporte": "microfutbol",
    "participantes": 10,
    "arl_nombre": "Positiva",
    "arl_confirmada": True,
    "recibe_nombre": "Quien Recibe",
    "recibe_correo": "recibe@uniminuto.edu.co",
}


def reservar(usuario, espacio, fecha, hora_inicio, **cambios):
    """crear_reserva con datos válidos; `cambios` reemplaza los que quieras probar."""
    from reservas.servicios import crear_reserva

    return crear_reserva(usuario, espacio, fecha, hora_inicio, {**DATOS_VALIDOS, **cambios})
