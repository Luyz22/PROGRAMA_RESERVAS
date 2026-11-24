from django import template

register = template.Library()


@register.filter
def ampm(hora):
    """Muestra una hora como en el mockup: 6:00 am, 5:00 pm."""
    if hora is None:
        return ""
    h12 = hora.hour % 12 or 12
    sufijo = "am" if hora.hour < 12 else "pm"
    return f"{h12}:{hora.minute:02d} {sufijo}"
