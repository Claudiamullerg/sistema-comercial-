"""Nomenclatura única del sistema. Nada fuera de estas listas puede guardarse.

Esta es la "regla contra el desorden": cuatro dimensiones, valores cerrados,
una sola fuente de verdad. Si mañana hace falta un valor nuevo, se agrega AQUÍ,
no en ManyChat a mano.
"""
from __future__ import annotations

# ── DIMENSIÓN 1 · ORIGEN ──────────────────────────────────────────────
ORIGENES = ["REEL", "HISTORIA", "DM", "COMENTARIO", "LINK", "ANUNCIO", "IMPORTACION", "DESCONOCIDO"]

# ── DIMENSIÓN 2 · INTERÉS ─────────────────────────────────────────────
INTERESES = ["EXPERIENCIA", "NEGOCIO", "SEGUNDA_ETAPA", "MONETIZACION", "REINVENCION", "OFERTA"]

# ── DIMENSIÓN 3 · INTENCIÓN (temperatura) ─────────────────────────────
INTENCIONES = ["FRIA", "TIBIA", "CALIENTE", "COMPRA"]

# ── DIMENSIÓN 4 · ETAPA (pipeline) — el orden importa ─────────────────
ETAPAS = [
    "NUEVO",
    "INTERACTUO",
    "LEAD",
    "INTERES",
    "CONVERSACION",
    "OPORTUNIDAD",
    "SESION_OFERTA",
    "VENTA",
    "CLIENTE",
]
ETAPA_RANGO = {e: i for i, e in enumerate(ETAPAS)}

# Etiquetas de intención detectadas en el texto (§10 INTENCIÓN)
INTENT_LABELS = [
    "CURIOSIDAD",
    "INTERES",
    "PROBLEMA_IDENTIFICADO",
    "BUSQUEDA_SOLUCION",
    "PREGUNTA_OFERTA",
    "OBJECION",
    "INTENCION_COMPRA",
    "COMPRADOR",
    "CLIENTE",
]

# Clasificación de temperatura del contacto (§13)
TEMPERATURAS = ["FRIO", "TIBIO", "CALIENTE", "CLIENTE", "NO_INTERESADO", "SIN_INFORMACION"]

# Clasificación de etiquetas de ManyChat (§13)
CLASES_ETIQUETA = ["ACTIVA", "OBSOLETA", "DUPLICADA", "CONFLICTIVA", "SIN_USO", "SIN_DATOS"]

# Tipos de alerta (§23) — solo las que requieren intervención humana
TIPOS_ALERTA = {
    "LEAD_CALIENTE": "🔥 Lead caliente",
    "PIDIO_INFO": "💬 Persona pidió información",
    "INTENCION_COMPRA": "💰 Intención de compra",
    "LEAD_SIN_SEGUIMIENTO": "⚠️ Lead sin seguimiento",
    "REEL_SOBRE_PROMEDIO": "📈 Reel generando contactos por encima del promedio",
    "CONVERSACIONES_SIN_RESPUESTA": "🚨 Muchas conversaciones sin respuesta",
    "PROBLEMA_SEGMENTACION": "🧹 Problema detectado en segmentación",
}

# Campos personalizados canónicos que la app espera/crea en ManyChat.
# Las automatizaciones de ManyChat solo rellenan estos; la app hace el resto.
CAMPOS_MANYCHAT = {
    "CRM_ORIGEN_TIPO": "Origen (REEL/HISTORIA/DM/COMENTARIO/LINK/ANUNCIO)",
    "CRM_ORIGEN_CONTENIDO": "Nombre corto o URL del Reel/post que originó el contacto",
    "CRM_KEYWORD": "Keyword/CTA que disparó la automatización",
    "CRM_AUTOMATIZACION": "Nombre del flujo de ManyChat que se activó",
    "CRM_CAMPANA": "Campaña (opcional)",
    "CRM_RESPUESTA": "Respuesta a la pregunta inteligente",
    # Los 4 de abajo los ESCRIBE la app (segmentación canónica), ManyChat solo los lee para condicionar flujos
    "CRM_INTERES": "Interés (escrito por la app)",
    "CRM_INTENCION": "Intención FRIA/TIBIA/CALIENTE/COMPRA (escrito por la app)",
    "CRM_ETAPA": "Etapa del pipeline (escrito por la app)",
    "CRM_SCORE": "Puntaje comercial (escrito por la app)",
}

# Opciones de la pregunta inteligente (PASO 7) → Interés. Se usan como quick replies en ManyChat.
PREGUNTA_INTELIGENTE = "Para enviarte lo que de verdad te sirve: ¿en qué punto estás hoy?"
OPCIONES_PREGUNTA = [
    ("Quiero convertir mi experiencia en un negocio", "MONETIZACION"),
    ("Tengo un negocio y quiero venderlo mejor", "NEGOCIO"),
    ("No sé qué sigue después de esta etapa", "SEGUNDA_ETAPA"),
    ("Quiero saber cómo trabajas / precios", "OFERTA"),
]


def validar(valor: str | None, permitidos: list[str], campo: str) -> str | None:
    if valor is None or valor == "":
        return None
    v = str(valor).strip().upper().replace(" ", "_").replace("Ó", "O").replace("É", "E").replace("Í", "I").replace("Á", "A").replace("Ú", "U")
    if v not in permitidos:
        raise ValueError(f"Valor '{valor}' no permitido para {campo}. Permitidos: {', '.join(permitidos)}")
    return v
