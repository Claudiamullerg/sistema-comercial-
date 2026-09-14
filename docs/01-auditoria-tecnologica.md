# Auditoría tecnológica y arquitectura final
## Sistema Comercial · Claudia Müller · Segunda Etapa Laboral

Fecha: 13 de septiembre de 2026
Estado: para decisión de Claudia antes de seguir construyendo

---

## 0. Lo primero: qué hice y qué no

Tu instrucción llegó cuando ya había construido el núcleo de la aplicación (modelo de datos, motor de clasificación, scoring, pipeline, auditoría de duplicados/etiquetas, alertas). Paré ahí. No construí dashboard ni pantallas.

Eso no fue trabajo perdido: el núcleo no depende de ninguna herramienta. ManyChat, Systeme.io o Hotmart entran como "adaptadores" (piezas pequeñas que traducen sus datos al formato de la app). Si mañana cambias una herramienta, se cambia el adaptador, no el sistema.

Este documento responde a lo que pediste: auditoría herramienta por herramienta, tres escenarios, la tabla comparativa y mi elección como si fuera mi propio negocio. Al final tienes qué necesito de ti para continuar.

---

## 1. Tu situación en una frase

Tienes un motor de adquisición que funciona (1,65 M de visualizaciones en 30 días, 99,2 % de no seguidores, +5.155 seguidores) y un embudo que gotea justo después: 2.274 visitas al perfil, 19 clics en el enlace. Es decir: la gente te descubre en Reels, pero casi nadie pasa a un canal donde puedas hablarle. Lo que falta no es más alcance. Es un puente entre el Reel y una conversación registrada en una base de datos tuya.

El sistema tiene que hacer una cosa bien: **convertir cada interacción en un registro con origen, interés, intención y etapa, y avisarte cuando alguien está lista para hablar.**

---

## 2. Auditoría herramienta por herramienta

Evalué cada pieza con tus diez criterios. Resumo la conclusión primero y el detalle después.

### 2.1 ManyChat — captura en Instagram

| Criterio | Evaluación |
|---|---|
| Función | Convierte comentarios, respuestas a historias, menciones y palabras clave en conversaciones de DM automáticas. Es la única forma práctica de hacer "comenta FRONTERA y te escribo". |
| ¿La necesitas? | **Sí, hoy.** Es la pieza que convierte alcance en contacto. Sin ella, el Reel termina en un "like". |
| ¿Se integra? | Sí. Puede empujar cada contacto a la app en tiempo real (External Request) y la app puede leer/escribir contactos vía API. Limitación real: su API **no permite listar todos los contactos**; por eso la app se alimenta de lo que ManyChat empuja, no de "descargas". |
| ¿Se puede reemplazar? | Técnicamente sí, construyendo la captura dentro de la app con la API de mensajería de Instagram (Meta). Para tu propia cuenta no exige revisión de app, pero exige mantenimiento continuo, no tiene constructor visual y Meta cambia reglas con frecuencia. |
| ¿Hay alternativa mejor? | No a tu tamaño. Chatfuel/Botpress no aportan nada nuevo y cuestan parecido. Construirlo propio tiene sentido cuando pases de ~5.000 contactos activos (ahí ManyChat sube a 69–99 USD/mes) o cuando quieras lógica que ManyChat no permite. |
| Coste | Pro ≈ 29–39 USD/mes hasta 2.500 contactos activos; Business ≈ 69–99 USD hasta 5.000–7.500; ≈ 199 USD en 15.000+. Lo que te pasó ("pagué 17, se bloqueó, pagué más") es exactamente su modelo: el plan Essential (250 contactos) se llena en una semana con tus Reels. |
| Escalabilidad | Escala, pero el precio crece con contactos activos, incluidos los que nunca respondieron. La app te dirá cuáles conviene archivar para no pagar por ruido. |
| Limitaciones | Sin exportación por API; etiquetas y campos crecen sin control si nadie manda; sus estadísticas de flujos no salen por API. |
| Riesgo de dependencia | Medio. Si se cae ManyChat, se cae la captura, pero tu base de datos ya está en la app. Nada se pierde. |
| Mantenimiento | Bajo si se usa como te propongo: pocos flujos, 6 campos CRM_*, cero etiquetas nuevas sin aprobación. |

**Veredicto: se queda, pero degradada a "portero".** Captura, hace la pregunta inteligente y empuja a la app. No decide nada, no segmenta, no nutre.

### 2.2 Systeme.io — email, páginas, cursos

| Criterio | Evaluación |
|---|---|
| Función | Email marketing, secuencias, landing pages, checkout, cursos, todo en uno. Hoy lo usas para email/CRM tras la compra en Hotmart. |
| ¿La necesitas? | **Para email, no a largo plazo. Para páginas/cursos, opcional.** Tu nutrición debe depender de la segmentación (interés × intención) que vive en la app; un ESP externo solo puede reaccionar a etiquetas que la app le mande. Cada contacto pasa a existir en dos sitios, y eso es el desorden que quieres evitar. |
| ¿Se integra? | Sí: tiene API (contactos, etiquetas) y disparadores por etiqueta. Suficiente para que la app lo gobierne mientras exista. |
| ¿Se puede reemplazar? | Sí. Un motor de secuencias dentro de la app + un servicio de envío (Resend o Amazon SES) cubre email con trazabilidad total: cada apertura y clic suma al score del contacto. |
| ¿Hay alternativa mejor? | Como ESP visual: Kit (ConvertKit) o MailerLite son mejores en automatizaciones y entregabilidad, pero son otra herramienta más. La mejor alternativa, en tu caso, es **dentro de la app**. |
| Coste | Gratis hasta 2.000 contactos, 17 USD hasta 5.000, 47 USD hasta 10.000. Con tu ritmo (+5.000 seguidores/mes) el escalón gratis dura poco si metes ahí a todo el mundo. |
| Escalabilidad | Correcta para email masivo; pobre para nutrición condicionada por comportamiento fino. |
| Limitaciones | Segmentación por etiquetas planas; la API no expone eventos de apertura/clic con detalle para atribuir. |
| Riesgo de dependencia | Bajo-medio: los contactos se exportan. |
| Mantenimiento | Bajo, pero es una interfaz más que abrir y mantener sincronizada. |

**Veredicto: fase 1 se queda en plan gratis como buzón de email gobernado por la app (la app manda la etiqueta, Systeme dispara la secuencia). Fase 2 el email pasa a la app y Systeme.io se cancela**, salvo que quieras conservar sus páginas o el audiocurso.

### 2.3 Hotmart — cobro

| Criterio | Evaluación |
|---|---|
| Función | Checkout con medios de pago locales de Latinoamérica (PSE, OXXO, cuotas, moneda local), facturación e impuestos. |
| ¿La necesitas? | **Sí.** Tu compradora está en Colombia, México, Venezuela, Chile, Argentina. Un checkout con tarjeta internacional (Stripe/PayPal) pierde ventas ahí. Esto vale más que su comisión. |
| ¿Se integra? | Sí: envía un aviso automático (webhook) por cada compra aprobada, reembolso o abandono de carrito. La app lo recibe y marca VENTA sola. |
| ¿Se puede reemplazar? | Por Stripe solo si tu mercado principal fuera EE. UU./Europa. No es tu caso. |
| Coste | Comisión por venta (≈ 10 % + tarifa fija, varía por país). Sin cuota mensual. |
| Riesgo / mantenimiento | Bajo. |

**Veredicto: se queda como único checkout.** Se elimina el checkout de Systeme.io para no tener dos.

### 2.4 Instagram (Meta Graph API) — adquisición y métricas

| Criterio | Evaluación |
|---|---|
| Función | Es tu fuente de audiencia. Su API da, gratis, las métricas de cuenta y de cada Reel (visualizaciones, alcance, interacciones, seguidores ganados, demografía). |
| ¿La necesitas? | Sí, para que la atribución Reel → contacto → venta no dependa de copiar números a mano. |
| ¿Se integra? | Sí, con tu propia cuenta profesional vinculada a una página de Facebook y una app de Meta. Para tu propia cuenta no hace falta revisión de Meta. |
| Coste | 0. |
| Limitaciones | Algunas métricas de Reels cambian de nombre con las versiones de la API; se mantiene. |
| Riesgo | Medio: Meta manda. Por eso la base de datos vive fuera de Meta. |

**Veredicto: se conecta en fase 2.** En fase 1 los números de Instagram se cargan a mano (una pantalla, cinco minutos al mes) y los Reels se registran con su nombre corto.

### 2.5 WhatsApp — conversación de cierre

| Criterio | Evaluación |
|---|---|
| Función | Donde se cierran ventas en Latinoamérica. Hoy no está en tu sistema. |
| ¿La necesitas? | Sí, pero no necesitas tecnología nueva para empezar: WhatsApp Business (app del teléfono) + un enlace wa.me que ManyChat manda a las calientes. La app registra "pasó a WhatsApp". |
| Alternativas | WhatsApp Cloud API desde la app (fase 3) cuando quieras plantillas, respuestas automáticas y registro automático de la conversación. Meta cobra por conversación iniciada por ti; las respuestas dentro de 24 h no cuestan. ManyChat también lo ofrece, pero es una capa más sobre lo mismo. |
| Coste | 0 ahora; después, centavos por conversación. |

**Veredicto: fase 1 WhatsApp Business manual con registro en la app; fase 3 Cloud API dentro de la app.**

### 2.6 CRM externo (HubSpot, Pipedrive, Notion, Airtable)

Función: registro por persona, pipeline, tareas. **No lo necesitas.** Esa es exactamente la función que debe vivir en tu app, porque el CRM genérico no entiende "vino del Reel 'es muy caro', contestó MONETIZACIÓN, preguntó precio". Un CRM externo te obligaría a otra sincronización y otra interfaz. HubSpot gratis parece barato hasta que necesitas automatizaciones (≥ 800 USD/mes). Se elimina de la ecuación.

### 2.7 Automatizadores (Zapier, Make, n8n)

Función: conectar herramientas sin código. **No los necesitas.** La app recibe webhooks directamente de ManyChat y Hotmart, y llama a las API que haga falta. Zapier/Make añaden coste por operación (con 5.000 contactos/mes se vuelve caro), retrasos y un punto de fallo más. Se eliminan.

### 2.8 Hojas de cálculo (Google Sheets)

Hoy son tu base de datos accidental. **Se eliminan como base de datos.** La app exporta a CSV cuando quieras mirar algo en una hoja, pero la verdad vive en un solo sitio.

### 2.9 Base de datos y hosting

La app necesita un lugar donde vivir encendida 24/7 (para recibir webhooks) y una base de datos. Opciones evaluadas: Railway (≈ 5–10 USD/mes, base de datos Postgres incluida, despliegue sencillo), Render (similar), Supabase (Postgres gestionado, gratis hasta 500 MB). Elijo **Railway con Postgres**: un solo proveedor, un solo panel, copias de seguridad automáticas, y la app arranca hoy con SQLite y pasa a Postgres sin cambiar código.

### 2.10 Email transaccional/envío (Resend, Amazon SES, Postmark)

Para la fase 2 (email desde la app): **Resend** (gratis hasta 3.000 correos/mes; 20 USD hasta 50.000) con tu dominio autenticado (SPF/DKIM en el cPanel que ya tienes). Amazon SES es más barato a gran volumen (≈ 0,10 USD por 1.000) pero más incómodo de configurar. Se empieza con Resend.

### 2.11 Inteligencia artificial

Dos usos concretos, dentro de la app: (1) clasificar el texto libre de los DMs cuando las reglas por palabras no alcanzan ("no sé si esto es para mí, tengo 52 y una consulta de psicología…" → interés SEGUNDA_ETAPA, intención TIBIA, problema identificado); (2) redactar un borrador de respuesta con tu voz para que tú lo apruebes en un clic. Coste con la API de Claude: 5–15 USD/mes a tu volumen. Se activa en fase 2. El "AI Step" de ManyChat cuesta 29 USD/mes extra y decide dentro de ManyChat, fuera de tu base de datos: no.

### 2.12 Meta Ads: públicos personalizados y CAPI

Cuando pautes, la app puede enviar a Meta los eventos reales (lead calificado, sesión, venta) y las audiencias por temperatura (fría/tibia/caliente/cliente). ManyChat ya tiene CAPI y públicos de Instagram; usarlo en fase 1 es aceptable, pero en cuanto el pipeline vive en la app, los eventos salen de la app, que es donde está la verdad. Fase 3.

### 2.13 Calendly / Google Meet

Se quedan (gratis, cumplen). Fase 2: Calendly avisa a la app cuando alguien agenda (webhook) y la etapa pasa a SESIÓN sola. Hasta entonces, lo marcas en un clic.

---

## 3. Los tres escenarios

### ESCENARIO A — Mantener herramientas actuales
Instagram + ManyChat + Systeme.io + Hotmart + hojas de cálculo + tú como integradora.
Qué pasa: los contactos entran en ManyChat, algunos en Systeme.io, los compradores en Hotmart; nadie sabe de qué Reel vino quién; el seguimiento depende de tu memoria. Escala el alcance, no el negocio. Es lo que tienes hoy.

### ESCENARIO B — Optimizar y sustituir algunas
La app como cerebro (CRM, segmentación, scoring, pipeline, alertas, atribución, salud) + ManyChat solo como portero + Systeme.io en plan gratis gobernado por la app para email + Hotmart con webhook a la app + WhatsApp Business manual. Se eliminan hojas de cálculo, automatizadores y cualquier CRM externo.
Qué pasa: una sola base de datos, todo trazable, alertas cuando alguien está caliente, tú intervienes solo en conversaciones. Se construye en días.

### ESCENARIO C — Arquitectura ideal desde cero
La app absorbe además el email (secuencias por segmento + Resend), las métricas de Instagram por API, la clasificación con IA, WhatsApp por Cloud API y los eventos a Meta. ManyChat sigue de portero hasta que el volumen justifique captura propia. Herramientas externas: ManyChat, Hotmart, y proveedores invisibles (hosting, envío de email, Meta).
Qué pasa: mínimo de herramientas, máxima automatización, todo el conocimiento del cliente en un activo tuyo. Se construye por fases sobre B.

### Tabla comparativa

| | **Actual (A)** | **Optimizada (B)** | **Ideal (C)** |
|---|---|---|---|
| **Herramientas** | Instagram, ManyChat, Systeme.io, Hotmart, hojas de cálculo, Calendly, Meet (+ tú) | App (cerebro) + ManyChat (portero) + Systeme.io gratis (email) + Hotmart + Calendly/Meet | App (cerebro, CRM, email, IA, WhatsApp, métricas) + ManyChat (portero) + Hotmart + Calendly/Meet. Proveedores invisibles: Railway, Resend, Meta |
| **Coste mensual** | ≈ 40–60 USD (ManyChat según contactos + Systeme) + comisión Hotmart | ≈ 45–55 USD (ManyChat 29–39 + Railway 5–10 + Systeme 0) + comisión Hotmart | ≈ 60–95 USD (ManyChat 29–39 + Railway 10–20 + Resend 0–20 + IA 5–15) + comisión Hotmart. Systeme.io cancelado |
| **Automatización** | Solo dentro de ManyChat; el resto manual | Captura → registro → clasificación → alerta automáticas; email por etiqueta | Todo lo anterior + nutrición por segmento, venta registrada sola, IA que clasifica y redacta, WhatsApp registrado |
| **Base de datos** | Dispersa en 3 herramientas + hojas | Una sola, tuya, en la app (Postgres) | Una sola, tuya, con historial completo por persona |
| **Email** | Systeme.io, secuencia igual para todas | Systeme.io gobernado por la app (etiqueta = interés × intención) | Motor propio en la app: cada persona recibe lo que su interés e intención piden; aperturas y clics suman al score |
| **Conversaciones** | DM en ManyChat, sin registro fuera | DM en ManyChat + WhatsApp manual; ambas registradas en la app con etapa y score | Igual + WhatsApp por API con la conversación en la ficha y borradores con IA |
| **Ventas** | Hotmart, registradas a mano en otro sitio | Hotmart avisa a la app → VENTA automática atribuida al Reel de origen | Igual + eventos a Meta (CAPI) y audiencias por temperatura |
| **Datos en tiempo real** | No | Sí (webhooks de ManyChat y Hotmart) | Sí, incluidas métricas de Instagram por API |
| **Trabajo manual** | Alto: revisar, copiar, recordar | Bajo: responder a quien la app te señala; cargar métricas de IG una vez al mes | Mínimo: responder y vender |
| **Escalabilidad** | No escala: cada 1.000 contactos son más caos | Escala hasta ~5.000 contactos activos sin cambiar nada | Escala sin límite práctico; a partir de ~5.000–10.000 contactos se evalúa captura propia y ManyChat sale |

---

## 4. Lo que elegiría si fuera mi negocio

**Elijo C, construida por fases, y la fase 1 es exactamente B.** No hay contradicción: la app es el centro en ambos, y cada fase quita una herramienta o un trabajo manual sin romper lo anterior.

Por qué no me quedo en B: porque el email por etiquetas en Systeme.io repite el problema de raíz (dos bases, segmentación plana, sin atribución), y porque la clasificación con IA es lo que convierte un DM ambiguo en un dato útil sin que tú lo leas uno por uno.

Por qué no salto directo a C completo: porque el 80 % del valor (saber quién vino de dónde, quién está caliente, con quién hablar hoy) está en la fase 1, se puede tener funcionando esta semana y ya cambia tu rutina. Lo demás se añade con datos reales, no con suposiciones.

Por qué ManyChat se queda como portero y no lo construyo yo hoy: cuesta 29–39 USD/mes y hace bien una cosa que a mí me costaría semanas construir y meses mantener frente a los cambios de Meta. Cuando pases de 5.000 contactos activos (a tu ritmo, en pocos meses), el precio de ManyChat justifica la captura propia y la app ya estará lista para recibirla. Regla clara: **ManyChat no decide, no segmenta, no nutre. Captura, pregunta y empuja.**

### Qué se construye dentro de la app (porque nadie lo hace mejor para ti)
Registro único por persona; origen automático (Reel, keyword, automatización); las 4 dimensiones (Origen, Interés, Intención, Etapa) con nomenclatura cerrada; scoring; pipeline; historial de cada cambio; alertas que solo avisan cuando hay que intervenir; "hoy habla con estas 5"; atribución Reel → contacto → lead → conversación → oportunidad → venta con los tres indicadores (Alcance, Conversación, Negocio); auditoría (duplicados, etiquetas, huecos) con DETECTAR → PROPONER → APROBAR → EJECUTAR; salud del sistema; reactivación; métricas de conversión y por país. Fase 2: secuencias de email, IA de clasificación y borradores, métricas de Instagram por API. Fase 3: WhatsApp Cloud API, CAPI y audiencias.

### Qué NO se construye (porque una herramienta lo hace mejor y más barato)
La captura de DMs en Instagram (ManyChat, por ahora); el cobro con medios locales (Hotmart); el envío físico de correos (Resend); la agenda (Calendly); el hosting (Railway).

---

## 5. De dónde sale cada dato (para que no haya cifras inventadas)

| Dato | Fuente | Cómo llega |
|---|---|---|
| Visualizaciones, alcance, seguidores, demografía, países, visitas al perfil, clics en enlace | Instagram | Fase 1: pantalla de carga mensual (los de tus últimos 30 días ya quedan cargados como línea base). Fase 2: API de Meta, automático |
| Métricas por Reel (views, interacciones, seguidores ganados) | Instagram | Igual que arriba, por Reel |
| Contacto: ID, usuario de IG, nombre, email, teléfono, estado, última interacción, etiquetas, campos, último mensaje, si te sigue | ManyChat | Automático: External Request al webhook de la app en cada entrada, respuesta y clic; refresco por API |
| Origen (Reel, keyword, CTA, automatización, campaña) | ManyChat, escrito por el flujo | Automático: 6 campos CRM_* que cada flujo rellena. El Reel se identifica por un nombre corto (ej. `reel-es-muy-caro`) |
| Respuesta a la pregunta inteligente | ManyChat (quick replies) | Automático |
| Interés, intención, score, etapa, temperatura | La app | Calculado. Se escribe de vuelta en ManyChat (4 campos) para que los flujos condicionen |
| Estadísticas por automatización (entradas, respuestas, abandonos) | La app | Contadas a partir de lo que ManyChat empuja (su API no las expone) |
| Conversaciones (quién escribió, quién espera respuesta) | ManyChat → app | Automático el mensaje entrante; "respondí" lo marcas tú en un clic (fase 3 automático por WhatsApp API) |
| Sesión agendada | Calendly | Fase 1 un clic; fase 2 webhook |
| Venta, importe, producto, país | Hotmart | Automático por webhook de compra aprobada |
| Lo que todavía no llegó | — | Se muestra como `PENDIENTE_DE_SINCRONIZACION`, nunca como cero ni como estimación |

Qué necesita intervención humana (y solo esto): responder a las personas que la app señala; marcar "respondí", "sesión" y "venta manual" cuando no venga de Hotmart; aprobar propuestas de limpieza; cargar las métricas de Instagram una vez al mes hasta la fase 2.

---

## 6. Plan por fases

**Fase 1 (esta semana) — Escenario B funcionando.** App desplegada en Railway; ManyChat con los 6 campos CRM_* y el External Request en los flujos de entrada; Hotmart con webhook; línea base de Instagram cargada; dashboard, pipeline, alertas, salud, propuestas. Tú empiezas a trabajar desde "Acciones de hoy".

**Fase 2 (2–4 semanas después, con datos reales).** Email dentro de la app con Resend; Systeme.io se cancela; IA para clasificar DMs y redactar borradores; métricas de Instagram por API; Calendly por webhook.

**Fase 3 (cuando el volumen lo pida).** WhatsApp Cloud API con conversación en la ficha; eventos a Meta (CAPI) y audiencias por temperatura; evaluación de captura propia para sustituir ManyChat.

---

## 7. Qué necesito de ti para continuar

1. **Tu decisión**: C por fases (mi recomendación), B a secas, o A.
2. **Clave de API de ManyChat** (Settings → API). Solo la pegas en la configuración de la app; no me la mandes por chat.
3. **Cuenta en Railway** (railway.app, con tu Google). Te guío paso a paso o lo hacemos juntas desde tu navegador. Coste ≈ 5 USD/mes.
4. **Acceso a Hotmart → Herramientas → Webhook** para pegar la URL de la app (lo hacemos después de desplegar).
5. **Lista de tus Reels activos con CTA** (nombre corto y keyword). Con eso dejo creados los "orígenes" para que la atribución funcione desde el primer contacto.

Con el punto 1 sigo construyendo de inmediato. Con el 2 y el 3, el sistema queda vivo.
