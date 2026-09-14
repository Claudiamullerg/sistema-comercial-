"""Motor de clasificación y scoring.

Entrada: lo que la persona dijo/hizo. Salida: interés, etiqueta de intención,
puntaje, temperatura y etapa mínima. Reglas explícitas en español, sin magia:
cualquier regla se puede leer y cambiar aquí.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta

from .config import settings
from .taxonomy import ETAPA_RANGO, OPCIONES_PREGUNTA


def _norm(t: str | None) -> str:
    if not t:
        return ""
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t.lower()).strip()


# ── Diccionarios de señales (orden = prioridad, la más fuerte primero) ──
SENALES_INTENCION: list[tuple[str, list[str], int]] = [
    # etiqueta, patrones (texto normalizado), puntos
    ("COMPRADOR", [r"\bya pague\b", r"\bya compre\b", r"\bhice el pago\b", r"\bcomprobante\b", r"\btransferi\b"], 60),
    ("INTENCION_COMPRA", [r"\bquiero comprar\b", r"\bquiero empezar\b", r"\bcomo pago\b", r"\bme apunto\b", r"\bdonde pago\b",
                          r"\bquiero la sesion\b", r"\bquiero agendar\b", r"\bagendar\b", r"\breservar\b", r"\bquiero trabajar contigo\b",
                          r"\bme interesa la sesion\b", r"\bcomo empiezo\b", r"\bquiero inscribirme\b", r"\blink de pago\b", r"\bquiero (la )?frontera\b"], 45),
    ("PREGUNTA_OFERTA", [r"\bprecio\b", r"\bcuanto cuesta\b", r"\bcuanto vale\b", r"\bvalor\b", r"\bcomo trabajas\b", r"\bque incluye\b",
                         r"\bmas informacion\b", r"\bmas info\b", r"\binformacion\b", r"\bcomo funciona\b", r"\bduracion\b", r"\bmodalidad\b",
                         r"\bsesion\b", r"\bprograma\b", r"\bmentoria\b", r"\bel mapa\b"], 30),
    ("OBJECION", [r"\bmuy caro\b", r"\bno tengo dinero\b", r"\bno tengo tiempo\b", r"\bno puedo ahora\b", r"\bmas adelante\b", r"\bdespues\b",
                  r"\blo pienso\b", r"\bno estoy segura\b", r"\bno se si\b", r"\bes caro\b", r"\bpresupuesto\b"], 15),
    ("BUSQUEDA_SOLUCION", [r"\bcomo puedo\b", r"\bque hago\b", r"\bque me recomiendas\b", r"\bnecesito\b", r"\bayuda\b", r"\bquiero aprender\b",
                           r"\bpor donde empiezo\b", r"\bcomo lo hago\b", r"\bme gustaria\b"], 20),
    ("PROBLEMA_IDENTIFICADO", [r"\bno se que hacer\b", r"\bestoy estancada\b", r"\bme siento\b", r"\bno se que sigue\b", r"\bno vendo\b",
                               r"\bno consigo clientes\b", r"\bme quede sin\b", r"\bperdi\b", r"\bcerre\b", r"\bme despidieron\b",
                               r"\bno se por donde\b", r"\bestoy cansada\b", r"\bno me alcanza\b"], 15),
    ("INTERES", [r"\bme interesa\b", r"\bquiero saber\b", r"\bcuentame\b", r"\bme gustaria saber\b", r"\bsi\b", r"\bsi quiero\b", r"\bdale\b", r"\bclaro\b"], 10),
    ("CURIOSIDAD", [r"\bhola\b", r"\bgracias\b", r"\binfo\b", r"\bguia\b", r"\bpdf\b", r"\bregalo\b", r"\bme lo mandas\b"], 3),
]

SENALES_INTERES: list[tuple[str, list[str]]] = [
    ("OFERTA", [r"\bprecio\b", r"\bcuanto\b", r"\bcomo trabajas\b", r"\bsesion\b", r"\bmentoria\b", r"\bprograma\b", r"\bagendar\b"]),
    ("MONETIZACION", [r"\bmonetizar\b", r"\bconvertir mi experiencia\b", r"\bganar dinero\b", r"\bcobrar\b", r"\bvender mi conocimiento\b", r"\bmonetiz"]),
    ("NEGOCIO", [r"\bmi negocio\b", r"\bclientes\b", r"\bvender\b", r"\bventas\b", r"\bemprend", r"\bmi empresa\b", r"\bcaro\b"]),
    ("SEGUNDA_ETAPA", [r"\bque sigue\b", r"\bsegunda etapa\b", r"\bsiguiente etapa\b", r"\bdespues de\b", r"\bretir", r"\bjubil", r"\bpension\b", r"\bnueva etapa\b"]),
    ("REINVENCION", [r"\bcambiar de\b", r"\bempezar de cero\b", r"\breinvent", r"\bnuevo rumbo\b", r"\botra cosa\b", r"\bcambio de vida\b"]),
    ("EXPERIENCIA", [r"\bexperiencia\b", r"\btrayectoria\b", r"\banos de\b", r"\bmi carrera\b", r"\bconocimiento\b"]),
]

_OPCION_A_INTERES = {_norm(texto): interes for texto, interes in OPCIONES_PREGUNTA}


def detectar_intencion(texto: str | None, keyword: str | None = None) -> tuple[str | None, int]:
    """Devuelve (etiqueta_intención, puntos). Gana la señal más fuerte.

    Si el texto es solo la keyword del CTA (ej. "FRONTERA"), es una entrada, no una intención.
    """
    t = _norm(texto)
    if not t:
        return None, 0
    if keyword and t.strip("!.¡¿? ") == _norm(keyword):
        return "CURIOSIDAD", 2
    if len(t.split()) <= 2 and t.strip("!.¡¿? ") in ("hola", "info", "frontera", "quiero", "si", "ok", "gracias", "buenas", "hola info"):
        return "CURIOSIDAD", 2
    for etiqueta, patrones, puntos in SENALES_INTENCION:
        for p in patrones:
            if re.search(p, t):
                return etiqueta, puntos
    return "CURIOSIDAD", 2


def detectar_interes(texto: str | None) -> str | None:
    t = _norm(texto)
    if not t:
        return None
    # Respuesta exacta a una opción de la pregunta inteligente
    for opcion, interes in _OPCION_A_INTERES.items():
        if opcion in t or t in opcion:
            return interes
    for interes, patrones in SENALES_INTERES:
        for p in patrones:
            if re.search(p, t):
                return interes
    return None


def detectar_objecion(texto: str | None) -> str | None:
    t = _norm(texto)
    for p in [r"muy caro", r"no tengo dinero", r"no tengo tiempo", r"mas adelante", r"no estoy segura", r"presupuesto", r"lo pienso"]:
        if re.search(p, t):
            return p.replace(r"\b", "")
    return None


def calcular_score(c) -> int:
    """Puntaje comercial 0–100. Suma señales, resta por enfriamiento."""
    pts = 0
    if c.origen_tipo and c.origen_tipo not in ("DESCONOCIDO", "IMPORTACION"):
        pts += 5
    if c.respuesta_pregunta:
        pts += 10
    if c.interes:
        pts += {"OFERTA": 20, "MONETIZACION": 12, "NEGOCIO": 10, "SEGUNDA_ETAPA": 10, "REINVENCION": 8, "EXPERIENCIA": 6}.get(c.interes, 5)
    pts += {
        None: 0, "CURIOSIDAD": 2, "INTERES": 8, "PROBLEMA_IDENTIFICADO": 15, "BUSQUEDA_SOLUCION": 18,
        "OBJECION": 22, "PREGUNTA_OFERTA": 30, "INTENCION_COMPRA": 45, "COMPRADOR": 60, "CLIENTE": 60,
    }.get(c.intent_label, 0)
    pts += min(c.clicks or 0, 3) * 8
    pts += min(c.interacciones or 0, 6) * 3
    if c.mc_follows_account:
        pts += 3
    if c.email or c.phone:
        pts += 4
    # Enfriamiento: cada semana sin interacción resta 5, hasta -30
    ref = c.last_inbound_at or c.mc_last_interaction or c.created_at
    if ref:
        semanas = max(0, (datetime.utcnow() - ref).days // 7)
        pts -= min(semanas * 5, 30)
    return max(0, min(100, pts))


def intencion_desde_score(c) -> str:
    if c.intent_label in ("INTENCION_COMPRA", "COMPRADOR", "CLIENTE") or c.etapa in ("VENTA", "CLIENTE"):
        return "COMPRA"
    if c.score >= settings.umbral_caliente:
        return "CALIENTE"
    if c.score >= settings.umbral_tibio:
        return "TIBIA"
    return "FRIA"


def temperatura_desde(c) -> str:
    if c.etapa in ("VENTA", "CLIENTE"):
        return "CLIENTE"
    if c.intent_label == "OBJECION" and c.score < settings.umbral_tibio:
        return "NO_INTERESADO"
    if not c.interes and not c.intent_label and not c.respuesta_pregunta and (c.interacciones or 0) == 0:
        return "SIN_INFORMACION"
    if c.mc_status and c.mc_status.lower() in ("unsubscribed", "unsubscribe", "deleted"):
        return "NO_INTERESADO"
    return {"COMPRA": "CALIENTE", "CALIENTE": "CALIENTE", "TIBIA": "TIBIO", "FRIA": "FRIO"}[c.intencion]


def etapa_minima(c) -> str:
    """La etapa nunca retrocede sola; aquí se calcula el mínimo que las señales justifican."""
    if c.etapa in ("VENTA", "CLIENTE"):
        return c.etapa
    if c.intent_label in ("COMPRADOR",):
        return "VENTA"
    if c.intent_label in ("INTENCION_COMPRA",):
        return "OPORTUNIDAD"
    if c.intent_label in ("PREGUNTA_OFERTA", "OBJECION") or c.interes == "OFERTA":
        return "CONVERSACION"
    if c.interes or c.respuesta_pregunta or c.intent_label in ("BUSQUEDA_SOLUCION", "PROBLEMA_IDENTIFICADO"):
        return "INTERES"
    if c.email or c.phone or (c.clicks or 0) > 0 or c.intent_label == "INTERES":
        return "LEAD"
    if (c.interacciones or 0) > 0 or c.mc_last_input_text:
        return "INTERACTUO"
    return "NUEVO"


def avanzar_etapa(actual: str, minima: str) -> str:
    return minima if ETAPA_RANGO.get(minima, 0) > ETAPA_RANGO.get(actual, 0) else actual


def recomendar_reactivacion(c) -> str | None:
    """Cuándo conviene reactivar (§18)."""
    ref = c.last_inbound_at or c.mc_last_interaction
    if not ref:
        return None
    dias = (datetime.utcnow() - ref).days
    if c.intencion in ("CALIENTE", "COMPRA") and dias >= 2:
        return "Reactivar hoy: mostró intención y se enfrió en 48 h."
    if c.intencion == "TIBIA" and dias >= 5:
        return "Reactivar esta semana con un mensaje personal (no automatizado)."
    if c.intencion == "FRIA" and 14 <= dias <= 45:
        return "Reactivar con contenido, no con oferta."
    if dias > 45:
        return "Reactivación de baja prioridad: mandar a secuencia de contenido y dejar que vuelva sola."
    return None


def siguiente_seguimiento(c) -> datetime | None:
    base = datetime.utcnow()
    if c.intencion == "COMPRA":
        return base + timedelta(hours=4)
    if c.intencion == "CALIENTE":
        return base + timedelta(days=1)
    if c.intencion == "TIBIA":
        return base + timedelta(days=settings.dias_sin_seguimiento)
    return None
