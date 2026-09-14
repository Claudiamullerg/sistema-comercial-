"""Sincronización: webhook de ManyChat, refresco por API, catálogos, importación CSV, escritura de segmentación."""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import settings
from .manychat import ManyChatClient, ManyChatError, normalizar_payload
from .models import Contact, McCustomField, McFlow, McTag
from .services import log_event, log_sync, upsert_from_payload
from .taxonomy import CAMPOS_MANYCHAT


# ── 1. Webhook (ManyChat empuja) ──────────────────────────────────────

def procesar_webhook(db: Session, body: dict) -> dict:
    p = normalizar_payload(body)
    if not (p["manychat_id"] or p["ig_username"] or p["email"] or p["phone"]):
        log_sync(db, "webhook", False, 0, "Payload sin identificador (subscriber_id / ig_username / email / phone)")
        return {"ok": False, "error": "Sin identificador"}
    c, nuevo = upsert_from_payload(db, p, source="webhook")
    log_sync(db, "webhook", True, 1, f"{'nuevo' if nuevo else 'actualizado'} {c.display} · evento {p['evento']}")
    if settings.manychat_writeback and settings.manychat_api_key and c.manychat_id:
        try:
            escribir_segmentacion(db, c)
        except ManyChatError as e:
            log_sync(db, "writeback", False, 0, str(e))
    return {"ok": True, "contact_id": c.id, "nuevo": nuevo, "etapa": c.etapa, "intencion": c.intencion, "score": c.score}


# ── 2. Refresco por API (la app consulta uno a uno) ───────────────────

def refrescar_contacto(db: Session, client: ManyChatClient, c: Contact) -> bool:
    if not c.manychat_id:
        return False
    data = client.get_subscriber(c.manychat_id)
    p = normalizar_payload(data)
    p["evento"] = "REFRESH"
    upsert_from_payload(db, p, source="api")
    return True


def refrescar_pendientes(db: Session, client: ManyChatClient | None = None, max_items: int = 200) -> int:
    client = client or ManyChatClient()
    if not client.configured:
        log_sync(db, "api_refresh", False, 0, "MANYCHAT_API_KEY no configurada")
        return 0
    limite = datetime.utcnow() - timedelta(minutes=max(settings.manychat_refresh_minutes, 5))
    q = select(Contact).where(Contact.manychat_id.is_not(None), Contact.merged_into_id.is_(None)).where(
        (Contact.synced_at.is_(None)) | (Contact.synced_at < limite)).order_by(Contact.score.desc()).limit(max_items)
    n, errores = 0, 0
    for c in db.scalars(q).all():
        try:
            if refrescar_contacto(db, client, c):
                n += 1
        except ManyChatError as e:
            errores += 1
            c.sync_status = "PENDIENTE_DE_SINCRONIZACION"
            log_sync(db, "api_refresh", False, 0, f"{c.display}: {e}")
            if "429" in str(e):
                break
    log_sync(db, "api_refresh", errores == 0, n, f"{n} refrescados, {errores} errores")
    return n


def sincronizar_catalogos(db: Session, client: ManyChatClient | None = None) -> dict:
    client = client or ManyChatClient()
    if not client.configured:
        return {"error": "MANYCHAT_API_KEY no configurada"}
    ahora = datetime.utcnow()
    out = {"tags": 0, "fields": 0, "flows": 0}
    tags = client.get_tags() or []
    if isinstance(tags, dict):
        tags = tags.get("tags") or []
    for t in tags:
        row = db.scalar(select(McTag).where(McTag.mc_tag_id == str(t.get("id")))) or db.scalar(select(McTag).where(McTag.name == t.get("name")))
        if not row:
            row = McTag(mc_tag_id=str(t.get("id")), name=t.get("name"))
            db.add(row)
        row.name, row.mc_tag_id, row.synced_at = t.get("name"), str(t.get("id")), ahora
        out["tags"] += 1
    fields = client.get_custom_fields() or []
    if isinstance(fields, dict):
        fields = fields.get("fields") or fields.get("custom_fields") or []
    for f in fields:
        row = db.scalar(select(McCustomField).where(McCustomField.mc_field_id == str(f.get("id"))))
        if not row:
            row = McCustomField(mc_field_id=str(f.get("id")), name=f.get("name"))
            db.add(row)
        row.name, row.type, row.description, row.synced_at = f.get("name"), f.get("type"), f.get("description"), ahora
        out["fields"] += 1
    flows = client.get_flows() or []
    if isinstance(flows, dict):  # ManyChat devuelve {"flows": [...], "folders": [...]}
        flows = flows.get("flows") or []
    for fl in flows:
        if not isinstance(fl, dict):
            continue
        row = db.scalar(select(McFlow).where(McFlow.ns == fl.get("ns")))
        if not row:
            row = McFlow(ns=fl.get("ns"), name=fl.get("name"))
            db.add(row)
        row.name, row.folder, row.synced_at = fl.get("name"), fl.get("folder_id") and str(fl.get("folder_id")), ahora
        out["flows"] += 1
    log_sync(db, "catalogs", True, sum(out.values()), str(out))
    audit.correr_auditoria(db)
    return out


def asegurar_campos_crm(db: Session, client: ManyChatClient | None = None) -> list[str]:
    """Crea en ManyChat los campos CRM_* que falten (una sola vez)."""
    client = client or ManyChatClient()
    if not client.configured:
        return []
    fields = client.get_custom_fields() or []
    if isinstance(fields, dict):
        fields = fields.get("fields") or fields.get("custom_fields") or []
    existentes = {f.get("name") for f in fields if isinstance(f, dict)}
    creados = []
    for nombre, desc in CAMPOS_MANYCHAT.items():
        if nombre not in existentes:
            tipo = "number" if nombre == "CRM_SCORE" else "text"
            client.create_custom_field(nombre, tipo, desc)
            creados.append(nombre)
    log_sync(db, "catalogs", True, len(creados), f"Campos CRM creados: {creados or 'ninguno (ya existían)'}")
    return creados


# ── 3. Escritura de segmentación (la app manda, ManyChat obedece) ─────

def escribir_segmentacion(db: Session, c: Contact, client: ManyChatClient | None = None) -> None:
    client = client or ManyChatClient()
    if not client.configured or not c.manychat_id:
        return
    valores = {"CRM_INTERES": c.interes or "", "CRM_INTENCION": c.intencion, "CRM_ETAPA": c.etapa, "CRM_SCORE": int(c.score)}
    for campo, valor in valores.items():
        if (c.mc_custom_fields or {}).get(campo) != valor:
            client.set_custom_field(c.manychat_id, campo, valor)
    c.mc_custom_fields = {**(c.mc_custom_fields or {}), **valores}
    log_event(db, c, "sync", field="writeback", new=str(valores), source="api")


# ── 4. Importación CSV / Google Sheets (carga inicial) ────────────────

_ALIAS = {
    "subscriber_id": ["subscriber id", "subscriber_id", "id", "contact id", "user id", "psid"],
    "ig_username": ["instagram username", "ig username", "ig_username", "username", "instagram"],
    "name": ["full name", "name", "nombre", "nombre completo"],
    "first_name": ["first name", "nombre"],
    "last_name": ["last name", "apellido"],
    "email": ["email", "correo", "e-mail"],
    "phone": ["phone", "telefono", "teléfono", "whatsapp", "whatsapp phone"],
    "status": ["status", "estado", "subscription status"],
    "subscribed": ["subscribed", "subscribed at", "fecha de suscripción", "opt-in date", "date subscribed"],
    "last_interaction": ["last interaction", "última interacción", "last interaction date"],
    "last_seen": ["last seen"],
    "last_input_text": ["last input text", "último mensaje", "last message"],
    "last_growth_tool": ["last growth tool", "growth tool", "trigger", "última herramienta"],
    "tags": ["tags", "etiquetas"],
    "locale": ["locale", "idioma"],
    "timezone": ["timezone", "zona horaria"],
}


def _mapear_columnas(headers: list[str]) -> dict[str, str]:
    m = {}
    low = {h: h.strip().lower() for h in headers}
    for key, alias in _ALIAS.items():
        for h, hl in low.items():
            if hl in alias and key not in m:
                m[key] = h
    return m


def importar_csv(db: Session, contenido: bytes | str, origen_tipo: str = "IMPORTACION") -> dict:
    texto = contenido.decode("utf-8-sig") if isinstance(contenido, bytes) else contenido
    dialecto = csv.Sniffer().sniff(texto[:4096], delimiters=",;\t") if texto.strip() else csv.excel
    reader = csv.DictReader(io.StringIO(texto), dialect=dialecto)
    headers = reader.fieldnames or []
    mapa = _mapear_columnas(headers)
    nuevos = actualizados = saltados = 0
    for fila in reader:
        body = {k: fila.get(h) for k, h in mapa.items()}
        # Columnas CRM_* y cualquier otra columna van como custom fields
        for h in headers:
            if h and h not in mapa.values():
                body.setdefault("custom_fields", {})[h] = fila.get(h)
        body["evento"] = "IMPORTACION"
        p = normalizar_payload(body)
        if not (p["manychat_id"] or p["ig_username"] or p["email"] or p["phone"]):
            saltados += 1
            continue
        if not p.get("origen_tipo"):
            p["origen_tipo"] = origen_tipo
        _, nuevo = upsert_from_payload(db, p, source="csv")
        nuevos += 1 if nuevo else 0
        actualizados += 0 if nuevo else 1
    log_sync(db, "csv_import", True, nuevos + actualizados, f"{nuevos} nuevos, {actualizados} actualizados, {saltados} sin identificador. Columnas: {list(mapa)}")
    audit.correr_auditoria(db)
    return {"nuevos": nuevos, "actualizados": actualizados, "saltados": saltados, "columnas_reconocidas": mapa}
