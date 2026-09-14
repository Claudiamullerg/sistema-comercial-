# Guía paso a paso · Fase 1
## Sistema Comercial · Claudia Müller

Esta guía está pensada para hacerla sola, en el orden en que está. Cada bloque dice cuánto tarda y qué tiene que pasar para saber que salió bien. Si algo no coincide con lo que ves en pantalla, para ahí y me lo cuentas; no sigas adivinando.

Hay dos caminos y los dos sirven: el **Camino A** es verlo funcionar hoy en tu Mac (20 minutos, sin gastar nada). El **Camino B** es ponerlo en internet para que ManyChat y Hotmart le manden datos solos (30 minutos, ≈ 5 USD/mes). Haz A primero para conocer la app; B es la fase 1 completa.

---

## Qué hay en la carpeta

```
sistema-comercial/
  run.sh                 ← arranca la app en tu Mac
  .env.example           ← plantilla de configuración (se copia como .env)
  app/                   ← la aplicación (no hace falta tocarla)
  tests/                 ← 13 pruebas automáticas del flujo completo (todas pasan)
  docs/                  ← este documento y la auditoría
  Dockerfile, railway.json  ← para ponerla en internet
```

---

## Camino A · Verla funcionar en tu Mac (20 min)

**1. Descomprime la carpeta** en Documentos. Queda `Documentos/sistema-comercial`.

**2. Abre Terminal** (Spotlight → escribe "Terminal" → Enter). No te asustes con la ventana negra: solo vas a pegar tres líneas.

**3. Comprueba que tienes Python.** Pega y Enter:
```
python3 --version
```
Debe decir `Python 3.9` o superior (el Mac trae 3.9.6 y sirve). Si dice "command not found", instala Python desde python.org (botón amarillo "Download", abrir el instalador, siguiente-siguiente) y vuelve a este paso.

**4. Entra en la carpeta y arranca:**
```
cd ~/Documents/sistema-comercial
bash run.sh
```
La primera vez tarda 1–2 minutos (instala lo que necesita). Cuando veas `Listo. Abre en tu navegador: http://localhost:8000`, ya está.

**5. Abre Safari o Chrome** y entra en `http://localhost:8000`.
Qué tienes que ver: el Panel con tus números de Instagram de los últimos 30 días (1.649.894 visualizaciones, +5.155 seguidores…) y, en todo lo que depende de ManyChat, la etiqueta `PENDIENTE DE SINCRONIZACIÓN`. Eso es correcto: la app no inventa cifras.

**6. Recorre las pestañas** para conocerla: Panel, Contactos (vacío), Alertas (vacío), Contenido (tus 3 Reels de la línea base ya están), Salud, Propuestas, Configuración.

**7. Prueba el flujo con un contacto de mentira.** En Configuración verás la URL del webhook. Abre otra pestaña de Terminal (⌘N) y pega esto tal cual:
```
curl -X POST "http://localhost:8000/webhooks/manychat?secret=cambia-este-secreto-por-uno-largo" -H "Content-Type: application/json" -d '{"evento":"ENTRADA","subscriber_id":"1","ig_username":"prueba_maria","origen_tipo":"REEL","origen_contenido":"reel-es-muy-caro","keyword":"FRONTERA","last_input_text":"Hola, cuánto cuesta la sesión?"}'
```
Vuelve al navegador y recarga el Panel. Qué tienes que ver: `@prueba_maria` en "Acciones" con el motivo "Pidió información", una alerta 💬 y el pipeline con 1 en CONVERSACIÓN. Entra en su ficha, pulsa **Ya le respondí** y mira cómo cambia el historial. Ese es el sistema entero en pequeño.

**8. Para parar la app:** en la Terminal donde corre, `Ctrl + C`. Para volver a arrancarla otro día: pasos 4 y 5 (ya no tarda).

Si quieres borrar el contacto de prueba antes de conectar lo real: cierra la app, borra el archivo `data/sistema.db` y arranca de nuevo. Todo vuelve a cero salvo la línea base de Instagram, que se siembra sola.

---

## Camino B · Ponerla en internet (30 min, ≈ 5 USD/mes)

La app necesita estar encendida 24/7 con una dirección pública para que ManyChat y Hotmart le envíen datos. Railway lo hace sin que tengas que administrar nada.

**1. Crea una cuenta en GitHub** (github.com → Sign up, gratis). Es donde vive el código; Railway lo lee de ahí.

**2. Sube la carpeta a GitHub** (la forma sin comandos):
- En GitHub: botón **+** arriba a la derecha → **New repository** → nombre `sistema-comercial` → marca **Private** → **Create repository**.
- En la página que aparece, pulsa el enlace **uploading an existing file**.
- Arrastra TODO el contenido de la carpeta `sistema-comercial` (no la carpeta, su contenido). Espera a que suba. Abajo, **Commit changes**.
- Comprueba que se ven `app`, `docs`, `tests`, `Dockerfile`, `run.sh`, `requirements.txt`, `railway.json`. Los archivos que empiezan por punto (`.env.example`, `.gitignore`) a veces el Mac los oculta: pulsa `⌘ + Shift + .` en el Finder para verlos y súbelos también.

**3. Crea la cuenta en Railway** (railway.app → Login with GitHub). Elige el plan **Hobby** (5 USD/mes; incluye el uso de una app pequeña como esta).

**4. Crea el proyecto:** **New Project** → **Deploy from GitHub repo** → elige `sistema-comercial`. Railway detecta el `Dockerfile` y construye la app (2–4 minutos). Verás un cuadro con el nombre del servicio.

**5. Añade la base de datos:** en el mismo proyecto, botón **+ New** → **Database** → **PostgreSQL**. Railway la crea y la conecta.

**6. Configura las variables.** Pulsa en el servicio de la app → pestaña **Variables** → **+ New Variable** y añade estas (una por una):

| Variable | Valor |
|---|---|
| `DATABASE_URL` | pulsa **Add Reference** → elige `Postgres` → `DATABASE_URL` (la app la entiende tal cual) |
| `WEBHOOK_SECRET` | inventa una palabra larga sin espacios (ej. `frontera-2026-luz-verde-93`) |
| `PANEL_PASSWORD` | la contraseña con la que entrarás al panel |
| `MANYCHAT_API_KEY` | la clave de ManyChat (ver Bloque 1 abajo). Si aún no la tienes, déjala para después |
| `MANYCHAT_WRITEBACK` | `false` por ahora |
| `HOTMART_HOTTOK` | el token de Hotmart (ver Bloque 3). Si aún no, después |

Railway redespliega solo al guardar.

**7. Dale una dirección pública:** pestaña **Settings** → **Networking** → **Generate Domain**. Te da algo como `sistema-comercial-production.up.railway.app`. Esa es la dirección de tu app. Ábrela: te pide la contraseña del panel y entras.

Qué tienes que ver: el mismo Panel que en tu Mac. A partir de aquí, la dirección de Railway es la buena; la de tu Mac queda para pruebas.

---

## Bloque 1 · ManyChat como portero (45 min)

Objetivo: que cada persona que interactúe con un Reel llegue a la app con su origen, y que se le haga una sola pregunta.

**1. Clave de API.** ManyChat → Settings (abajo a la izquierda) → **API** → **Generate your API Key** → copia. Pégala en Railway como `MANYCHAT_API_KEY` (Camino B, paso 6). Nunca la pegues en un chat ni en un correo.

**2. Crea los campos.** En la app → Configuración → botón **Crear campos CRM_\* en ManyChat**. Debe decir "Campos CRM creados: CRM_ORIGEN_TIPO, CRM_ORIGEN_CONTENIDO, …". Compruébalo en ManyChat → Settings → Fields → Custom User Fields.

**3. Lee los catálogos.** Botón **Leer catálogos**. En Salud verás todas tus etiquetas actuales clasificadas (ACTIVA / DUPLICADA / SIN USO…). No borres nada todavía: solo mira.

**4. Registra tus Reels con CTA.** En la app → Contenido → "Registrar un Reel nuevo". Un nombre corto por Reel, en minúsculas y con guiones, por ejemplo `reel-es-muy-caro`, y su keyword (`FRONTERA`). Rellena vistas e interacciones copiándolas de Instagram (pestaña Insights del Reel). Este nombre corto es el que une el Reel con sus contactos.

**5. Reforma el flujo de la keyword** (por ejemplo el de FRONTERA). Ábrelo en ManyChat y déjalo con esta forma, nada más:

1. Disparador: comentario con la keyword (o respuesta a historia, o DM con la keyword).
2. Acción **Set Custom Field** × 4: `CRM_ORIGEN_TIPO = REEL`, `CRM_ORIGEN_CONTENIDO = reel-es-muy-caro`, `CRM_KEYWORD = FRONTERA`, `CRM_AUTOMATIZACION = Reel es muy caro → FRONTERA`. (Cambia los valores en cada flujo; es lo único que cambia entre flujos.)
3. Mensaje 1: tu texto de bienvenida y lo que prometiste (guía, enlace…).
4. Acción **External Request** con `"evento": "ENTRADA"` (bloque de abajo).
5. Mensaje 2 con la pregunta inteligente y 4 **quick replies**:
   «Para enviarte lo que de verdad te sirve: ¿en qué punto estás hoy?»
   - Quiero convertir mi experiencia en un negocio
   - Tengo un negocio y quiero venderlo mejor
   - No sé qué sigue después de esta etapa
   - Quiero saber cómo trabajas / precios
   Cada quick reply hace **Set Custom Field** `CRM_RESPUESTA` = el texto de la opción, y a continuación un **External Request** con `"evento": "RESPUESTA"`.
6. Después de la respuesta, un mensaje corto que corresponda a la opción (dos o tres frases, sin oferta). Fin del flujo. **No añadas más pasos automáticos**: desde aquí decide la app y avisa a Claudia si hace falta.

**El External Request**, paso a paso: en el flujo, **+ Action** → **External Request** (Dev Tools). Method `POST`. Request URL: `https://TU-DIRECCION-DE-RAILWAY/webhooks/manychat?secret=TU-WEBHOOK-SECRET`. Headers: `Content-Type` = `application/json`. Body (pestaña Body → Raw):

```
{
  "evento": "ENTRADA",
  "subscriber_id": "{{user_id}}",
  "ig_username": "{{ig_username}}",
  "name": "{{full_name}}",
  "email": "{{email}}",
  "phone": "{{phone}}",
  "last_input_text": "{{last_input_text}}",
  "origen_tipo": "{{cuf_CRM_ORIGEN_TIPO}}",
  "origen_contenido": "{{cuf_CRM_ORIGEN_CONTENIDO}}",
  "keyword": "{{cuf_CRM_KEYWORD}}",
  "automatizacion": "{{cuf_CRM_AUTOMATIZACION}}",
  "respuesta": "{{cuf_CRM_RESPUESTA}}"
}
```
Las partes entre llaves dobles no se escriben a mano: se insertan con el botón **{ }** del editor eligiendo la variable (Contact ID, Instagram Username, Full Name, Email, Phone, Last Input Text y tus campos CRM_*). Pulsa **Test request**: debe responder `"ok": true`, y en la app → Configuración → Registro aparece "nuevo @tu_usuario". Guarda. Publica el flujo.

Copia ese mismo External Request en el paso de `RESPUESTA` (cambiando solo `"evento": "RESPUESTA"`) y, si tienes un botón con enlace, después del clic con `"evento": "CLICK"`.

**6. Regla de oro para ManyChat desde hoy:** no crear etiquetas nuevas. No crear campos nuevos. Cada Reel nuevo = registrar el Reel en la app + duplicar el flujo cambiando los 4 valores del paso 2. Nada más.

**7. Carga inicial de los contactos que ya tienes** (opcional, cuando quieras): ManyChat → Contacts → selecciona todos → Bulk Actions → **Send Flow** → elige un flujo nuevo que contenga solo el External Request con `"evento": "IMPORTACION"`. Cada contacto llega a la app con lo que ManyChat sepa de él. Si son miles, hazlo por tandas de 500 para no saturar. Alternativa: exportar a Google Sheets desde ManyChat, descargar como CSV e importarlo en la app → Configuración → Importar contactos.

---

## Bloque 2 · Systeme.io gobernado por la app (fase 1: 15 min)

En la fase 1 Systeme.io solo envía los correos que ya tienes. La única regla: la etiqueta que dispara una secuencia se llama igual que un interés de la app (`MONETIZACION`, `NEGOCIO`, `SEGUNDA_ETAPA`, `OFERTA`, `REINVENCION`, `EXPERIENCIA`) y se pone a mano desde Systeme.io cuando una persona te da su email en conversación. En la fase 2 el email pasa a la app y este bloque desaparece.

---

## Bloque 3 · Hotmart avisa las ventas (10 min)

Hotmart → **Herramientas** → **Webhook (Postback)** → **Crear webhook**. URL: `https://TU-DIRECCION-DE-RAILWAY/webhooks/hotmart`. Eventos: marca **Compra aprobada**, **Compra completa**, **Reembolso**, **Carrito abandonado** y **Boleto impreso**. Versión 2.0.0. Guarda. Hotmart te muestra un token **hottok**: pégalo en Railway como `HOTMART_HOTTOK`.

Qué pasa después: cada compra crea o encuentra a la persona por su email o teléfono, la marca VENTA, guarda importe y país, y si venía de un Reel, la venta queda atribuida a ese Reel en Contenido. Los carritos abandonados se convierten en alerta 💰 para que les escribas.

---

## Bloque 4 · Tu rutina diaria (10 minutos al día)

1. Abre el Panel. Lee solo dos cosas: **Acciones** (a quién hablar hoy) y **Alertas**.
2. Por cada persona de la lista: abre su ficha, lee el origen, la respuesta y el último mensaje, respóndele en Instagram (o pásala a WhatsApp), y en la app pulsa **Ya le respondí**. Si agendó, cambia etapa a SESIÓN / OFERTA. Si no le interesa, **No interesada**.
3. Una vez por semana: Salud → revisa duplicados y etiquetas → Propuestas → aprueba lo que proceda. Contenido → actualiza vistas e interacciones de los Reels activos.
4. Una vez al mes: Configuración → Instagram carga manual → los 30 días (5 minutos con la pestaña de Insights abierta).

Cuando la app se llena con el volumen real, pasamos a la fase 2 (email dentro de la app, IA que clasifica y redacta, Instagram por API).

---

## Si algo falla

- **"Address already in use" al arrancar en el Mac**: ya hay una copia corriendo. Ciérrala con `Ctrl + C` en la otra Terminal, o cambia el puerto: `PORT=8001 bash run.sh`.
- **ManyChat dice error en el Test request**: revisa que la URL empiece por `https://`, que el `secret` de la URL sea idéntico al `WEBHOOK_SECRET` de Railway, y que el Body sea JSON válido (sin comas al final de la última línea).
- **En Configuración → Registro aparece "Payload sin identificador"**: el External Request no está enviando `subscriber_id`; vuelve a insertar la variable Contact ID.
- **"Error ManyChat 401/403"** al leer catálogos: la clave de API está mal pegada o el plan no es Pro.
- **La app en Railway no arranca**: pestaña **Deployments** → **View logs**; casi siempre falta la referencia `DATABASE_URL` a Postgres.
- Cualquier otra cosa: copia el mensaje de error tal cual y me lo pegas.
