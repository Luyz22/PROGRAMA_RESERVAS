from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from espacios.models import Espacio
from usuarios.models import Perfil

User = get_user_model()

ROL_ADMINISTRADOR = "administrador"
ROLES = list(Perfil.Tipo.choices) + [(ROL_ADMINISTRADOR, "Administrador")]


def con_estilo_bootstrap(form):
    """Pone las clases de Bootstrap a todos los campos de un formulario."""
    for campo in form.fields.values():
        widget = campo.widget
        if isinstance(widget, forms.CheckboxInput):
            widget.attrs["class"] = "form-check-input"
        elif isinstance(widget, forms.Select):
            widget.attrs["class"] = "form-select"
        else:
            widget.attrs["class"] = "form-control"


class EspacioForm(forms.ModelForm):
    class Meta:
        model = Espacio
        fields = ["nombre", "tipo", "descripcion", "activo"]
        labels = {
            "nombre": "Nombre",
            "tipo": "Tipo",
            "descripcion": "Descripción",
            "activo": "Disponible para reservar",
        }
        help_texts = {
            "descripcion": "Opcional. Se muestra en la tarjeta del espacio.",
            "activo": "Si lo desactivas, deja de aparecer y nadie lo puede reservar. Las reservas pasadas se conservan.",
        }
        widgets = {"descripcion": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        con_estilo_bootstrap(self)

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        repetido = Espacio.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Ya existe un espacio con ese nombre.")
        return nombre


class UsuarioForm(forms.Form):
    """Crear o editar un usuario desde el panel.

    El rol junta el tipo de perfil (estudiante, docente, externo) y el
    permiso de administrador, para que sea una sola elección.
    """

    nombre = forms.CharField(max_length=150)
    apellido = forms.CharField(max_length=150)
    correo = forms.EmailField(label="Correo electrónico")
    rol = forms.ChoiceField(choices=ROLES)
    activo = forms.BooleanField(
        required=False, initial=True,
        help_text="Si lo desactivas, la persona ya no puede iniciar sesión.",
    )
    password = forms.CharField(
        label="Contraseña", strip=False, required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, usuario=None, editor=None, **kwargs):
        self.usuario = usuario   # None si es un usuario nuevo
        self.editor = editor     # el administrador que está editando
        if usuario is not None and "initial" not in kwargs:
            perfil = getattr(usuario, "perfil", None)
            kwargs["initial"] = {
                "nombre": usuario.first_name,
                "apellido": usuario.last_name,
                "correo": usuario.email or usuario.username,
                "rol": ROL_ADMINISTRADOR if usuario.is_staff else (perfil.tipo if perfil else Perfil.Tipo.EXTERNO),
                "activo": usuario.is_active,
            }
        super().__init__(*args, **kwargs)
        if usuario is None:
            self.fields["password"].required = True
            self.fields["password"].help_text = "La persona la podrá usar para entrar. Mínimo 8 caracteres."
        else:
            self.fields["password"].label = "Nueva contraseña"
            self.fields["password"].help_text = "Déjala vacía para no cambiarla."
        con_estilo_bootstrap(self)

    def clean_correo(self):
        correo = self.cleaned_data["correo"].strip().lower()
        otros = User.objects.filter(email__iexact=correo) | User.objects.filter(username__iexact=correo)
        if self.usuario is not None:
            otros = otros.exclude(pk=self.usuario.pk)
        if otros.exists():
            raise forms.ValidationError("Ya existe una cuenta con este correo.")
        return correo

    def clean(self):
        datos = super().clean()
        if self.usuario is not None and self.usuario == self.editor:
            if datos.get("rol") != ROL_ADMINISTRADOR:
                self.add_error("rol", "No puedes quitarte a ti mismo el rol de administrador.")
            if not datos.get("activo"):
                self.add_error("activo", "No puedes desactivar tu propia cuenta.")

        clave = datos.get("password")
        if clave:
            temporal = self.usuario or User(
                username=datos.get("correo", ""), email=datos.get("correo", ""),
                first_name=datos.get("nombre", ""), last_name=datos.get("apellido", ""),
            )
            try:
                validate_password(clave, temporal)
            except forms.ValidationError as error:
                self.add_error("password", error)
        return datos

    def save(self):
        datos = self.cleaned_data
        usuario = self.usuario or User(username=datos["correo"])
        usuario.username = datos["correo"]
        usuario.email = datos["correo"]
        usuario.first_name = datos["nombre"]
        usuario.last_name = datos["apellido"]
        usuario.is_active = datos["activo"]
        usuario.is_staff = datos["rol"] == ROL_ADMINISTRADOR
        if datos.get("password"):
            usuario.set_password(datos["password"])
        usuario.save()

        if datos["rol"] != ROL_ADMINISTRADOR:
            Perfil.objects.update_or_create(usuario=usuario, defaults={"tipo": datos["rol"]})
        return usuario
