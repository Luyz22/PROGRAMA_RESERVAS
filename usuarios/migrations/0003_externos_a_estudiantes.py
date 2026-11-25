"""Se elimina el rol "externo": esos perfiles pasan a "estudiante".

Además, las cuentas que ya existían antes de la verificación por correo
se marcan como verificadas, para que sigan funcionando igual.
"""

from django.db import migrations
from django.utils import timezone


def aplicar(apps, schema_editor):
    Perfil = apps.get_model("usuarios", "Perfil")
    Perfil.objects.filter(tipo="externo").update(tipo="estudiante")
    Perfil.objects.filter(
        correo_verificado_en__isnull=True, usuario__is_active=True
    ).update(correo_verificado_en=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ("usuarios", "0002_perfil_ampliado_sin_externo"),
    ]

    operations = [
        # Al revertir no se puede saber quién era externo: se deja como está.
        migrations.RunPython(aplicar, migrations.RunPython.noop),
    ]
