# Sistema Comercial · Claudia Müller

Centro de control comercial: convierte el alcance de Instagram en una base de datos propia, con origen, interés, intención y etapa por persona; avisa a Claudia solo cuando hace falta intervenir.

- **Arrancar en tu Mac:** `bash run.sh` → http://localhost:8000
- **Guía paso a paso:** `docs/02-guia-paso-a-paso.md`
- **Auditoría y arquitectura:** `docs/01-auditoria-tecnologica.md`
- **Pruebas:** `python3 -m pytest tests`

## Cómo fluye un contacto

Reel → ManyChat (keyword) → External Request → `POST /webhooks/manychat` → contacto único → clasificación (4 dimensiones + score) → pipeline → alerta si hace falta → Claudia responde → Hotmart avisa la venta → atribución al Reel.

## Módulos

| Archivo | Qué hace |
|---|---|
| `app/taxonomy.py` | Nomenclatura cerrada: orígenes, intereses, intenciones, etapas, campos CRM_* |
| `app/models.py` | Modelo de datos (contactos, historial, contenido, ventas, alertas, etiquetas, propuestas, Instagram, sync) |
| `app/classify.py` | Reglas de intención, interés, score, temperatura, etapa mínima, reactivación |
| `app/services.py` | Crear/actualizar contactos, historial, alertas, acciones de Claudia, fusiones |
| `app/manychat.py` | Cliente API de ManyChat + normalizador de payloads |
| `app/sync.py` | Webhook, refresco por API, catálogos, escritura de segmentación, importación CSV |
| `app/hotmart.py` | Webhook de Hotmart → venta / intención / reembolso |
| `app/instagram.py` | Línea base de Instagram + cliente Graph API (fase 2) |
| `app/audit.py` | Duplicados, etiquetas, seguimiento, reactivación, salud, propuestas |
| `app/metrics.py` | Números del panel, embudo, pipeline, valor comercial por Reel, país |
| `app/main.py` | Rutas web y arranque |

## Variables de entorno

Ver `.env.example`. Sin ninguna variable la app arranca igual: lo que falte se muestra como `PENDIENTE_DE_SINCRONIZACION`.
