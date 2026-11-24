from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class CorreoOUsuarioBackend(ModelBackend):
    """Permite iniciar sesión con el correo o con el nombre de usuario.

    Las personas que se registran entran con su correo. El superusuario
    creado con createsuperuser puede seguir entrando con su usuario.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None

        User = get_user_model()
        usuario = (
            User.objects.filter(email__iexact=username).order_by("id").first()
            or User.objects.filter(username=username).first()
        )
        if usuario is None:
            # Calcula una contraseña igual, para que no se note por el tiempo
            # de respuesta si el correo existe o no.
            User().set_password(password)
            return None

        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None
