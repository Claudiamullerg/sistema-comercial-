"""Webhook de Hotmart: compra aprobada → VENTA automática atribuida al origen del contacto."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import Contact
from .services import agregar_nota, find_contact, log_event, log_sync, registrar_venta, upsert_from_payload

EVENTOS_VENTA = {"PURCHASE_APPROVED", "PURCHASE_COMPLETE"}
EVENTOS_INTENCION = {"PURCHASE_BILLET_PRINTED", "PURCHASE_OUT_OF_SHOPPING_CART", "PURCHASE_DELAYED", "PURCHASE_PROTEST"}
EVENTOS_REEMBOLSO = {"PURCHASE_REFUNDED", "PURCHASE_CHARGEBACK", "PURCHASE_CANCELED"}


def procesar_hotmart(db: Session, body: dict, hottok_esperado: str | None = None) -> dict:
    if hottok_esperado and body.get("hottok") not in (hottok_esperado,):
        log_sync(db, "hotmart", False, 0, "hottok inválido")
        return {"ok": False, "error": "hottok inválido"}
    evento = str(body.get("event") or body.get("status") or "").upper()
    data = body.get("data") or body
    buyer = data.get("buyer") or {}
    purchase = data.get("purchase") or {}
    product = data.get("product") or {}
    email = (buyer.get("email") or data.get("email") or "").strip().lower() or None
    phone = buyer.get("checkout_phone") or data.get("phone")
    name = buyer.get("name") or data.get("name")
    precio = (purchase.get("price") or {})
    monto = float(precio.get("value") or data.get("price") or 0)
    moneda = precio.get("currency_value") or data.get("currency") or "USD"
    producto = product.get("name") or data.get("prod_name") or "Producto Hotmart"
    pais = ((buyer.get("address") or {}).get("country_iso") or "").upper()[:2] or None

    c = find_contact(db, email=email, phone=phone)
    if not c:
        c, _ = upsert_from_payload(db, {"manychat_id": None, "ig_username": None, "ig_id": None, "name": name, "email": email, "phone": phone,
                                        "locale": None, "timezone": None, "profile_pic": None, "country": pais, "mc_status": None,
                                        "mc_subscribed_at": None, "mc_last_interaction": None, "mc_last_seen": None, "mc_last_input_text": None,
                                        "mc_last_growth_tool": None, "mc_follows_account": None, "mc_optin_email": None, "mc_optin_phone": None,
                                        "mc_tags": [], "mc_custom_fields": {}, "origen_tipo": "LINK", "origen_contenido": None,
                                        "origen_keyword": None, "origen_cta": "checkout-hotmart", "origen_automation": None,
                                        "origen_campaign": None, "respuesta": None, "evento": "HOTMART", "raw": body}, source="webhook")
    elif pais and not c.country:
        c.country = pais

    if evento in EVENTOS_VENTA:
        registrar_venta(db, c, producto, monto, moneda, notes=f"Hotmart {purchase.get('transaction', '')}".strip())
        c.needs_reply = False
        log_sync(db, "hotmart", True, 1, f"Venta {producto} {monto} {moneda} → {c.display}")
        return {"ok": True, "contact_id": c.id, "venta": True}
    if evento in EVENTOS_INTENCION:
        c.intent_label = "INTENCION_COMPRA"
        from .services import clasificar
        clasificar(db, c, source="hotmart")
        agregar_nota(db, c, f"Hotmart: {evento.lower().replace('_', ' ')} ({producto}). Escribirle para cerrar.")
        log_sync(db, "hotmart", True, 1, f"{evento} → {c.display}")
        return {"ok": True, "contact_id": c.id, "intencion": True}
    if evento in EVENTOS_REEMBOLSO:
        agregar_nota(db, c, f"Hotmart: {evento.lower().replace('_', ' ')} ({producto}).")
        log_event(db, c, "sale", new=f"REEMBOLSO/CANCELACION {producto}", source="hotmart")
        log_sync(db, "hotmart", True, 1, f"{evento} → {c.display}")
        return {"ok": True, "contact_id": c.id, "reembolso": True}
    log_sync(db, "hotmart", True, 0, f"Evento ignorado: {evento or 'sin evento'}")
    return {"ok": True, "ignorado": evento}
