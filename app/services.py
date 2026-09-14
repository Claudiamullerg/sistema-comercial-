"""Lógica de negocio: crear/actualizar contactos, clasificar, registrar historial, disparar alertas."""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import classify
from .config import settings
from .models import Alert, Contact, ContactEvent, Content, Sale, SyncLog
from .taxonomy import ETAPA_RANGO, ETAPAS, INTERESES, ORIGENES, TIPOS_ALERTA, validar


# ── Historial ─────────────────────────────────────────────────────────

def log_event(db: Session, contact: Contact, type_: str, field: str | None = None, old=None, new=None,
              source: str = "sistema", payload: dict | None = None) -> ContactEvent:
    ev = ContactEvent(contact_id=contact.id, type=type_, field=field,
                      old_value=None if old is None else str(old), new_value=None if new is None else str(new),
                      source=source, payload=payload)
    db.add(ev)
    return ev


def _set(db: Session, c: Contact, field: str, value, source: str, overwrite: bool = True):
    """Cambia un campo registrando el cambio en el historial. No pisa datos con vacío."""
    if value in (None, "", [], {}):
        return
    old = getattr(c, field)
    if old == value:
        return
    if old not in (None, "", [], {}) and not overwrite:
        return
    setattr(c, field, value)
    if field not in ("raw_last_payload", "mc_custom_fields", "mc_tags", "updated_at", "synced_at"):
        log_event(db, c, "field_change", field, old, value, source)


# ── Contenido (Reel/post) ─────────────────────────────────────────────

def slug(text: str) -> str:
    import re, unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:80] or "contenido"


def get_or_create_content(db: Session, ref_or_title: str | None, type_: str = "REEL", keyword: str | None = None) -> Content | None:
    if not ref_or_title:
        return None
    ref = slug(ref_or_title)
    c = db.scalar(select(Content).where(or_(Content.ref == ref, Content.url == ref_or_title, Content.keyword == ref_or_title)))
    if not c:
        c = Content(ref=ref, title=ref_or_title, type=type_ if type_ in ("REEL", "POST", "HISTORIA", "LIVE") else "REEL",
                    url=ref_or_title if ref_or_title.startswith("http") else None, keyword=keyword)
        db.add(c)
        db.flush()
    return c


# ── Contactos ─────────────────────────────────────────────────────────

def find_contact(db: Session, manychat_id: str | None = None, ig_username: str | None = None,
                 email: str | None = None, phone: str | None = None) -> Contact | None:
    if manychat_id:
        c = db.scalar(select(Contact).where(Contact.manychat_id == manychat_id))
        if c:
            return c
    if ig_username:
        c = db.scalar(select(Contact).where(Contact.ig_username == ig_username, Contact.merged_into_id.is_(None)))
        if c:
            return c
    if email:
        c = db.scalar(select(Contact).where(func.lower(Contact.email) == email.lower(), Contact.merged_into_id.is_(None)))
        if c:
            return c
    if phone:
        c = db.scalar(select(Contact).where(Contact.phone == phone, Contact.merged_into_id.is_(None)))
        if c:
            return c
    return None


def upsert_from_payload(db: Session, p: dict, source: str = "webhook") -> tuple[Contact, bool]:
    """Crea o actualiza un contacto a partir de un payload normalizado. Devuelve (contacto, es_nuevo)."""
    c = find_contact(db, p.get("manychat_id"), p.get("ig_username"), p.get("email"), p.get("phone"))
    nuevo = c is None
    if nuevo:
        c = Contact(source_of_record=source)
        db.add(c)
        db.flush()
        log_event(db, c, "created", source=source, payload={"evento": p.get("evento")})

    for f in ("manychat_id", "ig_username", "ig_id", "name", "email", "phone", "locale", "timezone", "profile_pic", "country",
              "mc_status", "mc_subscribed_at", "mc_last_interaction", "mc_last_seen", "mc_last_growth_tool",
              "mc_follows_account", "mc_optin_email", "mc_optin_phone"):
        _set(db, c, f, p.get(f), source)
    if p.get("mc_tags"):
        c.mc_tags = p["mc_tags"]
    if p.get("mc_custom_fields"):
        c.mc_custom_fields = {**(c.mc_custom_fields or {}), **p["mc_custom_fields"]}
    c.raw_last_payload = p.get("raw")
    c.sync_status = "OK" if source in ("webhook", "api") else "PENDIENTE_DE_SINCRONIZACION"
    c.synced_at = datetime.utcnow() if source in ("webhook", "api") else c.synced_at

    # ── Origen: se registra UNA vez (el primero gana). Nunca queda vacío. ──
    if not c.origen_tipo or c.origen_tipo == "DESCONOCIDO":
        tipo = None
        try:
            tipo = validar(p.get("origen_tipo"), ORIGENES, "origen_tipo")
        except ValueError:
            tipo = None
        if not tipo:
            gt = (p.get("mc_last_growth_tool") or "").lower()
            if "reel" in gt or "comment" in gt or "coment" in gt:
                tipo = "REEL" if "reel" in gt else "COMENTARIO"
            elif "story" in gt or "historia" in gt:
                tipo = "HISTORIA"
            elif "ad" in gt.split() or "anuncio" in gt:
                tipo = "ANUNCIO"
            elif "link" in gt or "ref" in gt:
                tipo = "LINK"
            elif gt:
                tipo = "DM"
        if not tipo:
            tipo = "IMPORTACION" if source == "csv" else "DESCONOCIDO"
        _set(db, c, "origen_tipo", tipo, source)
        _set(db, c, "origen_fecha", p.get("mc_subscribed_at") or datetime.utcnow(), source)
    _set(db, c, "origen_keyword", p.get("origen_keyword"), source, overwrite=False)
    _set(db, c, "origen_cta", p.get("origen_cta"), source, overwrite=False)
    _set(db, c, "origen_automation", p.get("origen_automation"), source, overwrite=False)
    _set(db, c, "origen_campaign", p.get("origen_campaign"), source, overwrite=False)
    if not c.origen_content_id:
        content = get_or_create_content(db, p.get("origen_contenido") or (p.get("mc_last_growth_tool") if c.origen_tipo == "REEL" else None),
                                        type_=c.origen_tipo or "REEL", keyword=p.get("origen_keyword"))
        if content:
            c.origen_content_id = content.id
            log_event(db, c, "field_change", "origen_contenido", None, content.ref, source)

    # ── Señales de esta interacción ──
    evento = p.get("evento", "ENTRADA")
    texto = p.get("mc_last_input_text")
    respuesta = p.get("respuesta")
    if evento in ("CLICK", "CLIC"):
        c.clicks = (c.clicks or 0) + 1
        log_event(db, c, "click", source=source, payload={"cta": p.get("origen_cta")})
    if texto and texto != (c.events[0].new_value if c.events and c.events[0].type == "message_in" else None):
        c.interacciones = (c.interacciones or 0) + 1
        c.last_inbound_at = p.get("mc_last_interaction") or datetime.utcnow()
        _set(db, c, "mc_last_input_text", texto, source)
        log_event(db, c, "message_in", new=texto, source=source)
    elif evento == "ENTRADA":
        c.interacciones = (c.interacciones or 0) + (1 if nuevo else 0)
    if respuesta:
        _set(db, c, "respuesta_pregunta", respuesta, source)
        log_event(db, c, "message_in", field="respuesta_pregunta", new=respuesta, source=source)

    clasificar(db, c, texto=texto, respuesta=respuesta, source=source)
    return c, nuevo


def clasificar(db: Session, c: Contact, texto: str | None = None, respuesta: str | None = None, source: str = "sistema") -> None:
    """Aplica el motor: interés, intención, score, temperatura, etapa. Luego alertas."""
    texto_total = " ".join(t for t in (respuesta, texto, c.mc_last_input_text) if t)
    interes = classify.detectar_interes(respuesta) or classify.detectar_interes(texto) or c.interes or classify.detectar_interes(c.mc_last_input_text)
    if interes and interes in INTERESES:
        _set(db, c, "interes", interes, source)

    etiqueta, _ = classify.detectar_intencion(texto or respuesta, c.origen_keyword)
    if etiqueta:
        # La intención nunca baja de INTENCION_COMPRA a CURIOSIDAD por un "gracias"; solo sube o cambia entre señales fuertes.
        fuerza = {None: -1, "CURIOSIDAD": 0, "INTERES": 1, "PROBLEMA_IDENTIFICADO": 2, "BUSQUEDA_SOLUCION": 3, "OBJECION": 4,
                  "PREGUNTA_OFERTA": 5, "INTENCION_COMPRA": 6, "COMPRADOR": 7, "CLIENTE": 8}
        if fuerza.get(etiqueta, 0) >= fuerza.get(c.intent_label, -1) or etiqueta in ("OBJECION", "PREGUNTA_OFERTA", "INTENCION_COMPRA"):
            _set(db, c, "intent_label", etiqueta, source)
    obj = classify.detectar_objecion(texto_total)
    if obj:
        _set(db, c, "objecion", obj, source)
    if etiqueta == "PROBLEMA_IDENTIFICADO" and texto:
        _set(db, c, "problema", texto[:300], source)

    if texto and etiqueta not in (None, "CURIOSIDAD"):
        c.needs_reply = True

    c.score = classify.calcular_score(c)
    nueva_int = classify.intencion_desde_score(c)
    _set(db, c, "intencion", nueva_int, source)
    c.temperatura = classify.temperatura_desde(c)
    minima = classify.etapa_minima(c)
    nueva_etapa = classify.avanzar_etapa(c.etapa, minima)
    if nueva_etapa != c.etapa:
        log_event(db, c, "stage_change", "etapa", c.etapa, nueva_etapa, source)
        c.etapa = nueva_etapa
    if not c.next_followup_at or c.intencion in ("CALIENTE", "COMPRA"):
        c.next_followup_at = classify.siguiente_seguimiento(c) or c.next_followup_at
    generar_alertas_contacto(db, c)


# ── Alertas ───────────────────────────────────────────────────────────

def crear_alerta(db: Session, type_: str, dedupe_key: str, title: str, body: str | None = None,
                 recommendation: str | None = None, contact: Contact | None = None, content: Content | None = None,
                 level: str = "alta") -> Alert | None:
    existente = db.scalar(select(Alert).where(Alert.dedupe_key == dedupe_key, Alert.status == "abierta"))
    if existente:
        return None
    a = Alert(type=type_, level=level, dedupe_key=dedupe_key, title=title, body=body, recommendation=recommendation,
              contact_id=contact.id if contact else None, content_id=content.id if content else None)
    db.add(a)
    if contact:
        log_event(db, contact, "alert", new=type_, payload={"title": title})
    return a


def _ficha(c: Contact) -> str:
    reel = c.origen_content.title if c.origen_content else (c.origen_tipo or "desconocido")
    ultima = (c.last_inbound_at or c.mc_last_interaction)
    return (f"Viene de: {reel}\n"
            f"Problema: {c.problema or '—'}\n"
            f"Interés: {c.interes or '—'}\n"
            f"Objeción: {c.objecion or '—'}\n"
            f"Último mensaje: {c.mc_last_input_text or '—'}\n"
            f"Última interacción: {ultima.strftime('%d/%m %H:%M') if ultima else '—'}\n"
            f"Score: {c.score} · Etapa: {c.etapa}")


def generar_alertas_contacto(db: Session, c: Contact) -> None:
    if c.intent_label in ("INTENCION_COMPRA", "COMPRADOR") and c.etapa not in ("VENTA", "CLIENTE"):
        crear_alerta(db, "INTENCION_COMPRA", f"INTENCION_COMPRA:{c.id}", f"💰 {c.display} quiere comprar", _ficha(c),
                     "Responder ahora, personalmente. No dejar que la automatización siga.", contact=c)
    elif c.intent_label == "PREGUNTA_OFERTA":
        crear_alerta(db, "PIDIO_INFO", f"PIDIO_INFO:{c.id}", f"💬 {c.display} pidió información", _ficha(c),
                     "Responder hoy con una pregunta, no con un precio suelto.", contact=c)
    if c.intencion in ("CALIENTE", "COMPRA") and c.etapa not in ("VENTA", "CLIENTE"):
        crear_alerta(db, "LEAD_CALIENTE", f"LEAD_CALIENTE:{c.id}", f"🔥 LEAD CALIENTE · {c.display}", _ficha(c),
                     "Recomendación: responder ahora.", contact=c)


# ── Acciones humanas (Claudia) ────────────────────────────────────────

def marcar_respondido(db: Session, c: Contact, nota: str | None = None) -> None:
    c.needs_reply = False
    c.last_human_touch = datetime.utcnow()
    c.next_followup_at = classify.siguiente_seguimiento(c)
    if ETAPA_RANGO[c.etapa] < ETAPA_RANGO["CONVERSACION"] and ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"]:
        log_event(db, c, "stage_change", "etapa", c.etapa, "CONVERSACION", "claudia")
        c.etapa = "CONVERSACION"
    log_event(db, c, "message_out", new=nota or "(respondió)", source="claudia")
    for a in db.scalars(select(Alert).where(Alert.contact_id == c.id, Alert.status == "abierta",
                                            Alert.type.in_(["LEAD_SIN_SEGUIMIENTO", "PIDIO_INFO"]))):
        a.status, a.resolved_at = "resuelta", datetime.utcnow()


def cambiar_etapa(db: Session, c: Contact, etapa: str, source: str = "claudia") -> None:
    etapa = validar(etapa, ETAPAS, "etapa")
    if etapa != c.etapa:
        log_event(db, c, "stage_change", "etapa", c.etapa, etapa, source)
        c.etapa = etapa
        c.last_human_touch = datetime.utcnow()
        if etapa in ("VENTA", "CLIENTE"):
            c.intencion, c.temperatura, c.intent_label = "COMPRA", "CLIENTE", "CLIENTE" if etapa == "CLIENTE" else "COMPRADOR"
            for a in db.scalars(select(Alert).where(Alert.contact_id == c.id, Alert.status == "abierta")):
                a.status, a.resolved_at = "resuelta", datetime.utcnow()
        c.score = classify.calcular_score(c)


def registrar_venta(db: Session, c: Contact, product: str, amount: float, currency: str = "USD", notes: str | None = None) -> Sale:
    s = Sale(contact_id=c.id, product=product, amount=amount, currency=currency, notes=notes)
    db.add(s)
    log_event(db, c, "sale", new=f"{product} {amount} {currency}", source="claudia")
    cambiar_etapa(db, c, "VENTA")
    return s


def agregar_nota(db: Session, c: Contact, nota: str) -> None:
    c.notes = ((c.notes or "") + f"\n[{datetime.utcnow():%d/%m %H:%M}] {nota}").strip()
    c.last_human_touch = datetime.utcnow()
    log_event(db, c, "note", new=nota, source="claudia")


def fusionar(db: Session, principal: Contact, duplicado: Contact) -> None:
    """Fusiona el duplicado en el principal sin perder nada (solo tras aprobación)."""
    for f in ("manychat_id", "ig_username", "ig_id", "name", "email", "phone", "country", "timezone", "respuesta_pregunta",
              "interes", "origen_tipo", "origen_content_id", "origen_keyword", "origen_cta", "origen_automation"):
        if getattr(principal, f) in (None, "") and getattr(duplicado, f) not in (None, ""):
            if f == "manychat_id":
                duplicado.manychat_id, val = None, duplicado.manychat_id
                db.flush()
                setattr(principal, f, val)
            else:
                setattr(principal, f, getattr(duplicado, f))
    principal.clicks = (principal.clicks or 0) + (duplicado.clicks or 0)
    principal.interacciones = (principal.interacciones or 0) + (duplicado.interacciones or 0)
    if ETAPA_RANGO[duplicado.etapa] > ETAPA_RANGO[principal.etapa]:
        principal.etapa = duplicado.etapa
    principal.mc_tags = list({json.dumps(t, sort_keys=True): t for t in (principal.mc_tags or []) + (duplicado.mc_tags or [])}.values())
    principal.mc_custom_fields = {**(duplicado.mc_custom_fields or {}), **(principal.mc_custom_fields or {})}
    for ev in list(duplicado.events):
        ev.contact_id = principal.id
    for s in list(duplicado.sales):
        s.contact_id = principal.id
    duplicado.merged_into_id = principal.id
    log_event(db, principal, "merge", new=f"fusionado #{duplicado.id}", source="claudia")
    principal.score = classify.calcular_score(principal)


def log_sync(db: Session, kind: str, ok: bool, items: int = 0, message: str | None = None) -> None:
    db.add(SyncLog(kind=kind, ok=ok, items=items, message=message))
