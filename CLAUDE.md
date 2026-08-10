## Objetivo
Resuelve cada tarea leyendo y modificando el menor número de archivos posible.

## Stack
- Python
- Django 6
- Django REST Framework
- SimpleJWT
- Django Channels / ASGI
- Redis opcional mediante `REDIS_URL`
- MySQL en entorno compatible
- PostgreSQL mediante `DATABASE_URL` en producción
- WhiteNoise
- ReportLab / Pillow / openpyxl / python-pptx para generación de documentos

## Estructura principal
- `backend/` — configuración Django (`settings.py`, `urls.py`, ASGI/WSGI)
- `autenticacion/` — autenticación, usuarios, JWT/OTP y correos
- `catalogos/` — catálogos del sistema
- `solicitudes/` — lógica de solicitudes
- `scripts/` — scripts auxiliares
- `legacy/` — código heredado; no tocar salvo que la tarea lo requiera
- `manage.py` — comandos Django
- `requirements.txt` — dependencias

## Flujo dirigido por tipo de tarea
- Endpoint/API: busca primero `urls.py` → `views.py` → `serializers.py`; abre `models.py` solo si hace falta.
- Modelo/datos: revisa `models.py` y después solo serializer/view relacionados.
- Autenticación: empieza en `autenticacion/urls.py`, `views.py`, `serializers.py`; usa `otp.py` o `emails.py` solo si la tarea los menciona.
- Configuración/CORS/DB/Redis/Channels: revisa primero `backend/settings.py`.
- Rutas globales: revisa `backend/urls.py`.
- WebSockets: revisa `backend/asgi.py` y solo consumidores/routing relacionados.
- Generación PDF/Excel/PPT: localiza primero la función exacta que use ReportLab/openpyxl/python-pptx; no explores todas las apps.

## Reglas para ahorrar tokens
- NO recorras todas las apps Django al comenzar.
- Busca primero símbolo, endpoint, modelo, mensaje de error o ruta exacta.
- Lee únicamente archivos directamente relacionados con la tarea.
- No abras migraciones salvo que el cambio afecte el esquema o una migración falle.
- No leas `legacy/` salvo petición explícita o referencia directa desde código activo.
- No leas `.env`; usa `.env.example` solo cuando necesites conocer nombres de variables.
- No inspecciones `.git/`, entornos virtuales, caches, binarios ni archivos generados.
- No releas archivos que no han cambiado.
- Evita refactors globales.
- No cambies versiones de dependencias salvo que sea imprescindible.

## Convenciones Django/DRF
- Respeta separación entre `urls`, `views`, `serializers` y `models`.
- Reutiliza serializers, permisos y utilidades existentes antes de crear otros.
- No cambies nombres de campos o respuestas API sin comprobar su uso en frontend.
- Para cambios de modelo, crea migración solo si corresponde.
- No edites migraciones históricas.
- Mantén compatibilidad con JWT y permisos existentes.
- No expongas secretos, tokens ni valores reales de variables de entorno.

## Base de datos
- No asumas que desarrollo y producción usan el mismo motor.
- Evita SQL específico de un motor salvo necesidad.
- Antes de tocar configuración de DB, revisa `backend/settings.py`.
- No borres ni resetees datos sin autorización explícita.

## Verificación
Empieza por la comprobación más barata y localizada:
- Sintaxis/configuración Django: `python manage.py check`
- Tests de una app: `python manage.py test <app>`
- Test específico: usa la ruta de test más concreta disponible.
- Migraciones: `python manage.py makemigrations --check --dry-run` cuando aplique.

No ejecutes toda la suite por defecto si un test localizado es suficiente.

## Coordinación con frontend
El frontend está separado en `FUS_Frontend`.
Si modificas:
- URL de endpoint
- método HTTP
- parámetros
- estructura JSON
- nombres de campos
- autenticación/permisos

indica explícitamente que puede requerir un cambio correspondiente en frontend.

## Respuesta final
Sé breve:
- `Hecho:` una frase.
- `Archivos:` rutas modificadas.
- `Verificación:` comando ejecutado y resultado.

No muestres razonamiento interno ni pegues archivos completos salvo que se solicite.
"""

base = Path("/mnt/data")
(base/"CLAUDE_FUS_Frontend.md").write_text(frontend, encoding="utf-8")
(base/"CLAUDE_FUS_Backend.md").write_text(backend, encoding="utf-8")

print(base/"CLAUDE_FUS_Frontend.md")
print(base/"CLAUDE_FUS_Backend.md")