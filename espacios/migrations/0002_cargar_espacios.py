from django.db import migrations


def crear_espacios(apps, schema_editor):
    Espacio = apps.get_model("espacios", "Espacio")
    datos = [
        ("Cancha de fútbol", "cancha"),
        ("Cancha múltiple", "cancha"),
        ("Gimnasio", "gimnasio"),
    ]
    for nombre, tipo in datos:
        Espacio.objects.get_or_create(nombre=nombre, defaults={"tipo": tipo})


def borrar_espacios(apps, schema_editor):
    Espacio = apps.get_model("espacios", "Espacio")
    Espacio.objects.filter(
        nombre__in=["Cancha de fútbol", "Cancha múltiple", "Gimnasio"]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("espacios", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(crear_espacios, borrar_espacios),
    ]