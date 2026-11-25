from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone

from espacios.models import Espacio
from usuarios.forms import limpiar_telefono
from usuarios.models import MAYORIA_DE_EDAD, Perfil, calcular_edad
from usuarios.servicios import es_correo_institucional, dominio_institucional

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
        fields = ["nombre", "tipo", "descripcion", "aforo_minimo", "aforo_maximo", "activo"]
        labels = {
            "nombre": "Nombre",
            "tipo": "Tipo",
            "descripcion": "Descripción",
            "aforo_minimo": "Aforo mínimo",
            "aforo_maximo": "Aforo máximo",
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

    El rol junta el tipo de perfil (estudiante o docente) y el permiso de
    administrador, para que sea una sola elección. Estudiantes y docentes deben
    usar el correo institucional; el administrador puede usar cualquier correo.
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
    # Datos del perfil (no aplican al administrador).
    fecha_nacimiento = forms.DateField(
        label="Fecha de nacimiento", required=False,
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
    )
    telefono = forms.CharField(label="Teléfono", max_length=20, required=False)
    responsable_nombre = forms.CharField(label="Nombre del adulto responsable", max_length=150, required=False)
    responsable_documento = forms.CharField(label="Documento del adulto responsable", max_length=30, required=False)
    responsable_telefono = forms.CharField(label="Teléfono del adulto responsable", max_length=20, required=False)

    CAMPOS_PERFIL = ("fecha_nacimiento", "telefono", "responsable_nombre", "responsable_documento", "responsable_telefono")
    CAMPOS_RESPONSABLE = ("responsable_nombre", "responsable_documento", "responsable_telefono")

    def __init__(self, *args, usuario=None, editor=None, **kwargs):
        self.usuario = usuario   # None si es un usuario nuevo
        self.editor = editor     # el administrador que está editando
        if usuario is not None and "initial" not in kwargs:
            perfil = getattr(usuario, "perfil", None)
            kwargs["initial"] = {
                "nombre": usuario.first_name,
                "apellido": usuario.last_name,
                "correo": usuario.email or usuario.username,
                "rol": ROL_ADMINISTRADOR if usuario.is_staff else (perfil.tipo if perfil else Perfil.Tipo.ESTUDIANTE),
                "activo": usuario.is_active,
            }
            if perfil is not None:
                kwargs["initial"].update({campo: getattr(perfil, campo) for campo in self.CAMPOS_PERFIL})
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

        correo, rol = datos.get("correo"), datos.get("rol")
        if correo and rol and rol != ROL_ADMINISTRADOR and not es_correo_institucional(correo):
            self.add_error("correo", f"Estudiantes y docentes deben usar un correo @{dominio_institucional()}.")

        if rol and rol != ROL_ADMINISTRADOR:
            nacimiento = datos.get("fecha_nacimiento")
            if nacimiento and nacimiento > timezone.localdate():
                self.add_error("fecha_nacimiento", "La fecha de nacimiento no puede ser futura.")
            elif nacimiento and calcular_edad(nacimiento) < MAYORIA_DE_EDAD:
                for campo in self.CAMPOS_RESPONSABLE:
                    if not (datos.get(campo) or "").strip():
                        self.add_error(campo, "Obligatorio para menores de edad.")
            for campo in ("telefono", "responsable_telefono"):
                if campo in datos:
                    try:
                        datos[campo] = limpiar_telefono(datos.get(campo), obligatorio=False)
                    except forms.ValidationError as error:
                        self.add_error(campo, error)

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
            perfil, creado = Perfil.objects.get_or_create(usuario=usuario, defaults={"tipo": datos["rol"]})
            perfil.tipo = datos["rol"]
            for campo in self.CAMPOS_PERFIL:
                setattr(perfil, campo, datos.get(campo) or (None if campo == "fecha_nacimiento" else ""))
            # Una cuenta creada por el administrador no necesita verificar el correo.
            if perfil.correo_verificado_en is None:
                perfil.correo_verificado_en = timezone.now()
            perfil.save()
        return usuario


class DocentesAutorizadosForm(forms.Form):
    """Agregar correos a la lista: pegándolos o subiendo un archivo CSV."""

    correos = forms.CharField(
        label="Pega los correos",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "uno por línea, o separados por comas"}),
    )
    archivo = forms.FileField(
        label="O sube un archivo CSV",
        required=False,
        help_text="Se toman los correos de cualquier columna. Máximo 1 MB.",
    )

    TAMANO_MAXIMO = 1024 * 1024

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        con_estilo_bootstrap(self)
        self.fields["archivo"].widget.attrs["accept"] = ".csv,text/csv,text/plain"

    def clean_archivo(self):
        archivo = self.cleaned_data.get("archivo")
        if not archivo:
            return ""
        if archivo.size > self.TAMANO_MAXIMO:
            raise forms.ValidationError("El archivo pesa más de 1 MB.")
        contenido = archivo.read()
        for codificacion in ("utf-8-sig", "latin-1"):
            try:
                return contenido.decode(codificacion)
            except UnicodeDecodeError:
                continue
        raise forms.ValidationError("No se pudo leer el archivo. Guárdalo como CSV.")

    def clean(self):
        datos = super().clean()
        if not (datos.get("correos") or "").strip() and not datos.get("archivo"):
            raise forms.ValidationError("Pega al menos un correo o sube un archivo.")
        return datos

    def texto(self):
        """Todo lo pegado y lo del archivo, juntos, para sacar los correos."""
        return "\n".join([self.cleaned_data.get("correos") or "", self.cleaned_data.get("archivo") or ""])
