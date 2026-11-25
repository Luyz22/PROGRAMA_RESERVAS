from django import forms

from usuarios.servicios import dominio_institucional

from .servicios import deportes_de


class DatosReservaForm(forms.Form):
    """Datos que se piden antes de confirmar una reserva.

    Este formulario solo dibuja los campos y recoge lo que se escribe: las
    reglas (aforo, ARL, correo institucional...) las revisa
    servicios.validar_datos_reserva, para que valgan igual en todas partes.
    """

    deporte = forms.ChoiceField(label="Deporte", required=False, widget=forms.RadioSelect)
    participantes = forms.CharField(
        label="Número de participantes", required=False,
        widget=forms.NumberInput(attrs={"inputmode": "numeric"}),
    )
    arl_nombre = forms.CharField(
        label="Nombre de tu ARL", required=False, max_length=100,
        help_text="La ARL de quien hace la reserva.",
        widget=forms.TextInput(attrs={"placeholder": "Ej.: Positiva, Sura, Colmena"}),
    )
    arl_confirmada = forms.BooleanField(
        label="Confirmo que todos los participantes están afiliados a una ARL.", required=False,
    )
    recibe_nombre = forms.CharField(label="Nombre de quien recibe el espacio", required=False, max_length=150)
    recibe_correo = forms.CharField(
        label="Correo de quien recibe el espacio", required=False, max_length=254,
        widget=forms.EmailInput(),
    )

    def __init__(self, *args, espacio, **kwargs):
        super().__init__(*args, **kwargs)
        self.espacio = espacio
        deportes = deportes_de(espacio)
        if deportes:
            self.fields["deporte"].choices = deportes
        else:
            del self.fields["deporte"]

        participantes = self.fields["participantes"].widget.attrs
        participantes["min"] = espacio.aforo_minimo or 1
        if espacio.aforo_maximo:
            participantes["max"] = espacio.aforo_maximo
        if espacio.aforo_minimo or espacio.aforo_maximo:
            self.fields["participantes"].help_text = f"Contando a todos: {espacio.aforo_texto}."
        self.fields["recibe_correo"].help_text = (
            f"Correo @{dominio_institucional()}. Por defecto eres tú; cámbialo si otra persona recibe el espacio."
        )

        for nombre, campo in self.fields.items():
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs["class"] = "form-check-input"
            elif isinstance(campo.widget, forms.RadioSelect):
                campo.widget.attrs["class"] = "btn-check"
            else:
                campo.widget.attrs["class"] = "form-control"

    def agregar_errores(self, error):
        """Pone en cada campo los errores que devolvió el servicio."""
        for campo, mensajes in error.message_dict.items():
            self.add_error(campo if campo in self.fields else None, mensajes)
