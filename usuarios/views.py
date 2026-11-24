from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import IngresoForm, RegistroForm
from .models import Perfil


class IngresoView(LoginView):
    template_name = "usuarios/ingresar.html"
    authentication_form = IngresoForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        # El administrador entra directo a su panel; los demás, a Espacios.
        if self.request.user.is_staff:
            return reverse("panel:inicio")
        return super().get_default_redirect_url()

    def form_valid(self, form):
        respuesta = super().form_valid(form)
        # Guarda cuándo aceptó la política de datos, si aún no estaba registrado.
        Perfil.objects.filter(
            usuario=form.get_user(), acepto_politica_en__isnull=True
        ).update(acepto_politica_en=timezone.now())
        return respuesta


def registro(request):
    if request.user.is_authenticated:
        return redirect("espacios:lista")

    if request.method == "POST":
        form = RegistroForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            login(request, usuario, backend="usuarios.backends.CorreoOUsuarioBackend")
            messages.success(request, f"¡Bienvenido, {usuario.first_name}! Tu cuenta quedó creada.")
            return redirect("espacios:lista")
    else:
        form = RegistroForm()

    return render(request, "usuarios/registro.html", {"form": form})
