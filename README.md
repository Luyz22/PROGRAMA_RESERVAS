# Reservas deportivas UNIMINUTO

Sistema web para reservar los espacios deportivos de la universidad (proyecto académico).
Hecho con **Django 6.1**, SQLite y Bootstrap 5.

## Requisitos

- **Python 3.12 o superior** (Django 6.1 no funciona con 3.11 o anteriores). Compruébalo con `python --version`.
- Git.

## Instalación (la primera vez)

Desde la carpeta del proyecto (la que tiene `manage.py`), en PowerShell:

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py crear_usuarios_prueba
```

- Si `Activate.ps1` da un error de "ejecución de scripts deshabilitada", ejecuta una vez
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y vuelve a activar.
- Después de activar, al inicio de la línea debe aparecer `(venv)`.
- `migrate` crea la base de datos `db.sqlite3`. Cada persona tiene la suya: **no se sube a GitHub**.
- `crear_usuarios_prueba` crea usuarios de prueba. Sus correos y la contraseña están al inicio de
  `usuarios/management/commands/crear_usuarios_prueba.py` y el comando los muestra al terminar.

## Uso diario

```powershell
venv\Scripts\Activate.ps1
python manage.py runserver
```

Abre http://127.0.0.1:8000. Para apagar el servidor: `Ctrl + C` en la terminal.

Después de cada `git pull`, ejecuta `python manage.py migrate` por si hay cambios en la base de datos.

## Pruebas

```powershell
python manage.py check
python manage.py test
```

## Estructura

| Carpeta | Qué contiene |
|---|---|
| `config/` | Configuración del proyecto (`settings.py`, `urls.py`). |
| `usuarios/` | Perfil, inicio de sesión con correo, registro y usuarios de prueba. |
| `espacios/` | Espacios deportivos y su listado. |
| `reservas/` | Reservas, bloqueos y las reglas del negocio (`servicios.py`). |
| `panel/` | Panel del administrador (`/panel/`). |
| `templates/`, `static/` | Plantillas y estilos comunes. |

## Correo

En desarrollo los correos no se envían: se imprimen en la terminal donde corre `runserver`.
Se configura en `MAILERS` dentro de `config/settings.py`.
