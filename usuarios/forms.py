from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from .models import Perfil

User = get_user_model()


class IngresoForm(AuthenticationForm):
    """Formulario de inicio de sesión con correo y contraseña."""

    username = forms.CharField(
        label="Correo electrónico",
        widget=forms.TextInput(
            attrs={"autofocus": True, "autocomplete": "email", "class": "form-control",
                   "placeholder": "correo@ejemplo.com"}
        ),
    )
    password = forms.CharField(
        label="Contraseña",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"autocomplete": "current-password", "class": "form-control",
                   "placeholder": "Escribe tu contraseña"}
        ),
    )
    acepta_politica = forms.BooleanField(
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        error_messages={"required": "Debes aceptar la política de datos para ingresar."},
    )

    error_messages = {
        "invalid_login": "Correo o contraseña incorrectos.",
        "inactive": "Esta cuenta está desactivada.",
    }


class RegistroForm(forms.Form):
    """Formulario para que un usuario externo cree su cuenta.

    Estudiantes y docentes no se registran aquí: sus cuentas las crea
    el administrador (en /admin) con el tipo de usuario que corresponda.
    """

    nombre = forms.CharField(max_length=150)
    apellido = forms.CharField(max_length=150)
    correo = forms.EmailField(label="Correo electrónico")
    password1 = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repite la contraseña", strip=False, widget=forms.PasswordInput)
    acepta_politica = forms.BooleanField(
        label="Acepto la política de tratamiento de datos personales (Ley 1581 de 2012)",
        error_messages={"required": "Debes aceptar la política de datos para crear la cuenta."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Clases de Bootstrap para que los campos se vean bien.
        for nombre, campo in self.fields.items():
            if nombre == "acepta_politica":
                campo.widget.attrs["class"] = "form-check-input"
            else:
                campo.widget.attrs["class"] = "form-control"

    def clean_correo(self):
        correo = self.cleaned_data["correo"].strip().lower()
        if User.objects.filter(email__iexact=correo).exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return correo

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get("password1"), datos.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif p1:
            temporal = User(
                username=datos.get("correo", ""),
                email=datos.get("correo", ""),
                first_name=datos.get("nombre", ""),
                last_name=datos.get("apellido", ""),
            )
            try:
                validate_password(p1, temporal)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return datos

    def save(self):
        datos = self.cleaned_data
        usuario = User.objects.create_user(
            username=datos["correo"],
            email=datos["correo"],
            password=datos["password1"],
            first_name=datos["nombre"],
            last_name=datos["apellido"],
        )
        Perfil.objects.create(
            usuario=usuario, tipo=Perfil.Tipo.EXTERNO, acepto_politica_en=timezone.now()
        )
        return usuario
