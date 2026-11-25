"""Por ahora solo se reserva la Cancha múltiple (10 a 12 personas).

"Cancha de fútbol" y "Gimnasio" se desactivan, no se borran: se pueden
reactivar desde el panel cuando haga falta.
"""

from django.db import migrations

DESACTIVAR = ["Cancha de fútbol", "Gimnasio"]


def aplicar(apps, schema_editor):
    Espacio = apps.get_model("espacios", "Espacio")
    cancha, _ = Espacio.objects.get_or_create(
        nombre="Cancha múltiple", defaults={"tipo": "cancha"}
    )
    cancha.activo = True
    cancha.aforo_minimo = 10
    cancha.aforo_maximo = 12
    cancha.save()
    Espacio.objects.filter(nombre__in=DESACTIVAR).update(activo=False)


def revertir(apps, schema_editor):
    Espacio = apps.get_model("espacios", "Espacio")
    Espacio.objects.filter(nombre__in=DESACTIVAR).update(activo=True)
    Espacio.objects.filter(nombre="Cancha múltiple").update(aforo_minimo=None, aforo_maximo=None)


class Migration(migrations.Migration):

    dependencies = [
        ("espacios", "0003_aforos"),
    ]

    operations = [
        migrations.RunPython(aplicar, revertir),
    ]
