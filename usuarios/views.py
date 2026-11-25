from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import IngresoForm, ReenviarVerificacionForm, RegistroForm
from .servicios import activar_cuenta, enviar_verificacion, registrar_usuario, reenviar_verificacion


class IngresoView(LoginView):
    template_name = "usuarios/ingresar.html"
    authentication_form = IngresoForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        # El administrador entra directo a su panel; los demás, a Espacios.
        if self.request.user.is_staff:
            return reverse("panel:inicio")
        return super().get_default_redirect_url()


def registro(request):
    if request.user.is_authenticated:
        return redirect("espacios:lista")

    form = RegistroForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = registrar_usuario(form.cleaned_data)
        enviar_verificacion(request, usuario)
        request.session["correo_registrado"] = usuario.email
        return redirect("usuarios:registro_enviado")

    return render(request, "usuarios/registro.html", {"form": form})


def registro_enviado(request):
    correo = request.session.get("correo_registrado")
    if not correo:
        return redirect("usuarios:registro")
    return render(request, "usuarios/registro_enviado.html", {
        "correo": correo, "horas": settings.VERIFICACION_CORREO_HORAS,
    })


def activar(request, token):
    try:
        usuario = activar_cuenta(token)
    except ValidationError as error:
        return render(request, "usuarios/activar_error.html", {"mensaje": error.messages[0]}, status=400)
    messages.success(request, f"¡Listo, {usuario.first_name}! Tu cuenta está activa. Ya puedes iniciar sesión.")
    return redirect("usuarios:ingresar")


def reenviar(request):
    form = ReenviarVerificacionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        reenviar_verificacion(request, form.cleaned_data["correo"])
        messages.info(
            request,
            "Si hay una cuenta pendiente de activar con ese correo, te enviamos un enlace nuevo.",
        )
        return redirect("usuarios:ingresar")
    return render(request, "usuarios/reenviar.html", {"form": form})
