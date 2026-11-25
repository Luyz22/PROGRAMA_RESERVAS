import re

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import MAYORIA_DE_EDAD, calcular_edad
from .servicios import dominio_institucional, pendiente_de_verificar, validar_correo_institucional

User = get_user_model()

EDAD_MAXIMA = 100
_PATRON_TELEFONO = re.compile(r"^\+?[\d\s\-()]{7,20}$")


def limpiar_telefono(valor, obligatorio=True):
    valor = (valor or "").strip()
    if not valor:
        if obligatorio:
            raise forms.ValidationError("Escribe un número de teléfono.")
        return ""
    if not _PATRON_TELEFONO.match(valor) or sum(c.isdigit() for c in valor) < 7:
        raise forms.ValidationError("Escribe un teléfono válido (solo números, mínimo 7 dígitos).")
    return valor


class IngresoForm(AuthenticationForm):
    """Inicio de sesión con correo y contraseña.

    La política de datos ya no se acepta aquí: se acepta al crear la cuenta.
    """

    username = forms.CharField(
        label="Correo electrónico",
        widget=forms.TextInput(
            attrs={"autofocus": True, "autocomplete": "email", "class": "form-control",
                   "placeholder": f"tucorreo@{dominio_institucional()}"}
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

    error_messages = {
        "invalid_login": "Correo o contraseña incorrectos.",
        "inactive": "Esta cuenta está desactivada. Comunícate con el administrador.",
    }

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError:
            # ¿La contraseña es correcta pero la cuenta no se ha activado?
            correo = (self.cleaned_data.get("username") or "").strip()
            clave = self.cleaned_data.get("password") or ""
            usuario = User.objects.filter(email__iexact=correo).select_related("perfil").first()
            if usuario is not None and not usuario.is_active and usuario.check_password(clave):
                if pendiente_de_verificar(usuario):
                    raise forms.ValidationError(
                        format_html(
                            'Tu cuenta aún no está activada. Abre el enlace que te enviamos a tu correo. '
                            '<a href="{}">¿No te llegó?</a>',
                            reverse("usuarios:reenviar"),
                        ),
                        code="sin_verificar",
                    )
                raise forms.ValidationError(self.error_messages["inactive"], code="inactive")
            raise


class RegistroForm(forms.Form):
    """Crear cuenta: estudiantes y docentes, solo con correo institucional.

    Todos nacen como estudiante; quien esté en la lista de docentes autorizados
    queda como docente automáticamente.
    """

    nombre = forms.CharField(max_length=150)
    apellido = forms.CharField(max_length=150)
    correo = forms.EmailField(label="Correo institucional")
    fecha_nacimiento = forms.DateField(
        label="Fecha de nacimiento", widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
    )
    telefono = forms.CharField(label="Teléfono", max_length=20)
    responsable_nombre = forms.CharField(label="Nombre completo", max_length=150, required=False)
    responsable_documento = forms.CharField(label="Documento de identidad", max_length=30, required=False)
    responsable_telefono = forms.CharField(label="Teléfono", max_length=20, required=False)
    password1 = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Repite la contraseña", strip=False, widget=forms.PasswordInput)
    acepta_politica = forms.BooleanField(
        label="Acepto la política de tratamiento de datos personales (Ley 1581 de 2012)",
        error_messages={"required": "Debes aceptar la política de datos para crear la cuenta."},
    )

    CAMPOS_RESPONSABLE = ("responsable_nombre", "responsable_documento", "responsable_telefono")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["correo"].widget.attrs["placeholder"] = f"tucorreo@{dominio_institucional()}"
        self.fields["fecha_nacimiento"].widget.attrs["max"] = timezone.localdate().isoformat()
        for nombre, campo in self.fields.items():
            campo.widget.attrs["class"] = "form-check-input" if nombre == "acepta_politica" else "form-control"

    def clean_correo(self):
        correo = self.cleaned_data["correo"].strip().lower()
        validar_correo_institucional(correo)
        existente = User.objects.filter(email__iexact=correo).select_related("perfil").first()
        if existente is not None:
            if pendiente_de_verificar(existente):
                raise forms.ValidationError(format_html(
                    'Ya creaste una cuenta con este correo y falta activarla. '
                    '<a href="{}">Pide otro enlace</a>.', reverse("usuarios:reenviar"),
                ))
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return correo

    def clean_fecha_nacimiento(self):
        fecha = self.cleaned_data["fecha_nacimiento"]
        if fecha > timezone.localdate():
            raise forms.ValidationError("La fecha de nacimiento no puede ser futura.")
        if calcular_edad(fecha) > EDAD_MAXIMA:
            raise forms.ValidationError("Revisa la fecha de nacimiento.")
        return fecha

    def clean_telefono(self):
        return limpiar_telefono(self.cleaned_data.get("telefono"))

    def clean_responsable_telefono(self):
        return limpiar_telefono(self.cleaned_data.get("responsable_telefono"), obligatorio=False)

    @property
    def es_menor(self):
        fecha = self.cleaned_data.get("fecha_nacimiento") if hasattr(self, "cleaned_data") else None
        return fecha is not None and calcular_edad(fecha) < MAYORIA_DE_EDAD

    def clean(self):
        datos = super().clean()

        if self.es_menor:
            for campo in self.CAMPOS_RESPONSABLE:
                if not (datos.get(campo) or "").strip():
                    self.add_error(campo, "Obligatorio para menores de edad.")
        else:
            for campo in self.CAMPOS_RESPONSABLE:   # si es mayor de edad no se guardan
                datos[campo] = ""

        p1, p2 = datos.get("password1"), datos.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif p1:
            temporal = User(
                username=datos.get("correo", ""), email=datos.get("correo", ""),
                first_name=datos.get("nombre", ""), last_name=datos.get("apellido", ""),
            )
            try:
                validate_password(p1, temporal)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return datos


class ReenviarVerificacionForm(forms.Form):
    correo = forms.EmailField(
        label="Correo institucional",
        widget=forms.EmailInput(attrs={"class": "form-control", "autofocus": True}),
    )
