from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from reservas.servicios import hoy, proxima_reserva

from .models import Espacio

# Filtros que aparecen arriba de las tarjetas: (valor en la URL, texto del botón).
FILTROS = [
    ("", "Todos"),
    (Espacio.Tipo.CANCHA, "Canchas"),
    (Espacio.Tipo.GIMNASIO, "Gimnasio"),
    (Espacio.Tipo.OTRO, "Otros"),
]


@login_required
def lista(request):
    tipo = request.GET.get("tipo", "")
    espacios = Espacio.objects.filter(activo=True).order_by("nombre")
    if tipo in Espacio.Tipo.values:
        espacios = espacios.filter(tipo=tipo)
    else:
        tipo = ""

    return render(
        request,
        "espacios/lista.html",
        {
            "espacios": espacios,
            "filtros": FILTROS,
            "tipo_actual": tipo,
            "proxima": proxima_reserva(request.user),
            "hoy": hoy(),
        },
    )
