"""Auditoría y salud del sistema: duplicados, etiquetas, huecos, seguimiento, reactivación.

Nunca borra nada. Detecta → propone (tabla proposals) → Claudia aprueba → se ejecuta.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import Alert, Contact, McTag, Proposal
from .services import crear_alerta, fusionar, log_event
from .taxonomy import ETAPA_RANGO


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", t)


def _activos(db: Session):
    return db.scalars(select(Contact).where(Contact.merged_into_id.is_(None))).all()


# ── Duplicados ────────────────────────────────────────────────────────

def detectar_duplicados(db: Session) -> list[dict]:
    grupos: dict[tuple, list[Contact]] = defaultdict(list)
    for c in _activos(db):
        if c.ig_username:
            grupos[("ig", c.ig_username.lower())].append(c)
        if c.email:
            grupos[("email", c.email.lower())].append(c)
        if c.phone:
            grupos[("tel", re.sub(r"\D", "", c.phone))].append(c)
        if c.ig_id:
            grupos[("ig_id", c.ig_id)].append(c)
    out = []
    vistos = set()
    for (campo, valor), lista in grupos.items():
        ids = tuple(sorted({c.id for c in lista}))
        if len(ids) < 2 or ids in vistos:
            continue
        vistos.add(ids)
        out.append({"campo": campo, "valor": valor, "ids": list(ids),
                    "contactos": [{"id": c.id, "display": c.display, "etapa": c.etapa, "manychat_id": c.manychat_id} for c in lista]})
    return out


def proponer_duplicados(db: Session) -> int:
    n = 0
    for d in detectar_duplicados(db):
        key = "FUSIONAR:" + "-".join(map(str, d["ids"]))
        if db.scalar(select(Proposal).where(Proposal.dedupe_key == key)):
            continue
        principal = min(d["ids"])
        db.add(Proposal(type="FUSIONAR_DUPLICADOS", dedupe_key=key,
                        title=f"Fusionar {len(d['ids'])} registros con el mismo {d['campo']} ({d['valor']})",
                        detail="Se conserva el registro más antiguo como principal; el resto se marca como fusionado. No se borra nada.",
                        payload={"principal": principal, "duplicados": [i for i in d["ids"] if i != principal]}))
        n += 1
    return n


# ── Etiquetas de ManyChat ─────────────────────────────────────────────

def clasificar_etiquetas(db: Session) -> dict:
    tags = db.scalars(select(McTag)).all()
    # Contar uso real a partir de los contactos sincronizados
    uso: dict[str, int] = defaultdict(int)
    for c in _activos(db):
        for t in (c.mc_tags or []):
            if isinstance(t, dict) and t.get("name"):
                uso[t["name"]] += 1
    por_norm: dict[str, list[McTag]] = defaultdict(list)
    for t in tags:
        t.contact_count = uso.get(t.name, t.contact_count or 0)
        por_norm[_norm(t.name)].append(t)
    resumen = defaultdict(int)
    hoy = datetime.utcnow()
    for t in tags:
        clase, razon = "ACTIVA", None
        if len(por_norm[_norm(t.name)]) > 1:
            clase, razon = "DUPLICADA", "Otra etiqueta con el mismo nombre (mayúsculas/acentos/espacios)"
        elif (t.contact_count or 0) == 0:
            clase, razon = "SIN_USO", "Ningún contacto la tiene"
        elif t.last_used_at and (hoy - t.last_used_at).days > 90:
            clase, razon = "OBSOLETA", "Sin uso en 90 días"
        # Conflictivas: dos temperaturas/etapas a la vez en el mismo contacto
        t.classification, t.reason = clase, razon
        resumen[clase] += 1
    # Conflictos por contacto (ej. tiene "frio" y "caliente")
    conflictos = 0
    palabras = [("frio", "caliente"), ("frio", "tibio"), ("lead", "cliente"), ("nointeresad", "caliente"), ("cliente", "nointeresad")]
    for c in _activos(db):
        nombres = {_norm(t.get("name", "")) for t in (c.mc_tags or []) if isinstance(t, dict)}
        for a, b in palabras:
            if any(a in n for n in nombres) and any(b in n for n in nombres):
                conflictos += 1
                break
    resumen["CONFLICTIVA"] = conflictos
    return dict(resumen)


def proponer_etiquetas(db: Session) -> int:
    n = 0
    for t in db.scalars(select(McTag).where(McTag.classification.in_(["SIN_USO", "DUPLICADA", "OBSOLETA"]))):
        key = f"RETIRAR_ETIQUETA:{t.name}"
        if db.scalar(select(Proposal).where(Proposal.dedupe_key == key)):
            continue
        db.add(Proposal(type="RETIRAR_ETIQUETA", dedupe_key=key, title=f"Retirar etiqueta «{t.name}» ({t.classification})",
                        detail=(t.reason or "") + ". Al aprobar, se marca como retirada en la app y se anota en el historial; "
                               "el borrado en ManyChat lo haces tú con un clic desde ManyChat (la app no borra allí).",
                        payload={"tag": t.name, "clase": t.classification}))
        n += 1
    return n


# ── Seguimiento y reactivación ────────────────────────────────────────

def leads_sin_seguimiento(db: Session) -> list[Contact]:
    limite = datetime.utcnow() - timedelta(days=settings.dias_sin_seguimiento)
    out = []
    for c in _activos(db):
        if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"] and c.etapa not in ("VENTA", "CLIENTE"):
            ultimo = c.last_human_touch
            if (c.needs_reply and (c.last_inbound_at or c.created_at) < limite) or (ultimo is None and c.created_at < limite) or (ultimo and ultimo < limite and c.intencion in ("TIBIA", "CALIENTE", "COMPRA")):
                out.append(c)
    return sorted(out, key=lambda c: -c.score)


def conversaciones_pendientes(db: Session) -> list[Contact]:
    return sorted([c for c in _activos(db) if c.needs_reply], key=lambda c: -c.score)


def conversaciones_abandonadas(db: Session) -> list[Contact]:
    limite = datetime.utcnow() - timedelta(days=settings.dias_conversacion_abandonada)
    return [c for c in _activos(db) if c.etapa in ("CONVERSACION", "OPORTUNIDAD", "SESION_OFERTA")
            and (c.last_inbound_at or c.created_at) < limite and (c.last_human_touch or c.created_at) < limite]


def segmentos_reactivacion(db: Session) -> dict[str, list[Contact]]:
    ahora = datetime.utcnow()
    seg = {"Interesadas sin respuesta": [], "Calientes perdidas": [], "Antiguas interesadas": []}
    for c in _activos(db):
        if c.etapa in ("VENTA", "CLIENTE"):
            continue
        ref = c.last_inbound_at or c.mc_last_interaction or c.created_at
        dias = (ahora - ref).days if ref else 999
        if c.intencion in ("CALIENTE", "COMPRA") and dias >= 2:
            seg["Calientes perdidas"].append(c)
        elif c.interes and dias >= 3 and ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["INTERES"] and dias < settings.dias_inactivo:
            seg["Interesadas sin respuesta"].append(c)
        elif ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["INTERES"] and dias >= settings.dias_inactivo:
            seg["Antiguas interesadas"].append(c)
    for k in seg:
        seg[k].sort(key=lambda c: -c.score)
    return seg


def archivables_en_manychat(db: Session, dias: int = 60) -> list[Contact]:
    """Contactos que ocupan cupo en ManyChat sin aportar: nunca mostraron interés y llevan N días sin interactuar.
    La app conserva su ficha e historial; en ManyChat se pueden archivar/borrar para no pagar por ellos.
    Si vuelven a escribir, entran como nuevos y la app los reconoce por su usuario de Instagram."""
    limite = datetime.utcnow() - timedelta(days=dias)
    out = []
    for c in _activos(db):
        if c.etapa in ("VENTA", "CLIENTE") or c.intencion in ("CALIENTE", "COMPRA"):
            continue
        if c.interes or c.respuesta_pregunta or (c.clicks or 0) > 0 or c.email or c.phone:
            continue
        ref = c.last_inbound_at or c.mc_last_interaction or c.created_at
        if ref and ref < limite:
            out.append(c)
    return sorted(out, key=lambda c: (c.last_inbound_at or c.mc_last_interaction or c.created_at))


# ── Salud del sistema (§32) ───────────────────────────────────────────

def salud(db: Session) -> dict:
    activos = _activos(db)
    total = len(activos) or 1
    bien = sum(1 for c in activos if c.origen_tipo not in (None, "DESCONOCIDO") and c.etapa and c.intencion and (c.interes or c.etapa in ("NUEVO", "INTERACTUO")))
    sin_origen = sum(1 for c in activos if c.origen_tipo in (None, "DESCONOCIDO"))
    sin_etapa = sum(1 for c in activos if not c.etapa)
    sin_segmentar = sum(1 for c in activos if not c.interes and ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"])
    dup = detectar_duplicados(db)
    tags_obsoletas = db.scalar(select(func.count(McTag.id)).where(McTag.classification.in_(["OBSOLETA", "SIN_USO", "DUPLICADA"]))) or 0
    demasiadas_tags = sum(1 for c in activos if len(c.mc_tags or []) > 6)
    pendientes_sync = sum(1 for c in activos if c.sync_status != "OK")
    return {
        "contactos_total": len(activos),
        "clasificados_pct": round(100 * bien / total, 1) if activos else None,
        "sin_origen": sin_origen,
        "sin_etapa": sin_etapa,
        "sin_segmentacion": sin_segmentar,
        "duplicados": len(dup),
        "etiquetas_obsoletas": tags_obsoletas,
        "contactos_con_demasiadas_etiquetas": demasiadas_tags,
        "leads_sin_seguimiento": len(leads_sin_seguimiento(db)),
        "conversaciones_pendientes": len(conversaciones_pendientes(db)),
        "conversaciones_abandonadas": len(conversaciones_abandonadas(db)),
        "pendientes_de_sincronizacion": pendientes_sync,
        "automatizaciones_con_problemas": 0,  # se calcula en metrics.automatizaciones()
    }


def correr_auditoria(db: Session) -> dict:
    """Se ejecuta tras cada sync y cada N minutos: genera propuestas y alertas de sistema."""
    clasificar_etiquetas(db)
    proponer_duplicados(db)
    proponer_etiquetas(db)
    s = salud(db)
    for c in leads_sin_seguimiento(db)[:20]:
        crear_alerta(db, "LEAD_SIN_SEGUIMIENTO", f"LEAD_SIN_SEGUIMIENTO:{c.id}", f"⚠️ {c.display} lleva {settings.dias_sin_seguimiento}+ días sin seguimiento",
                     f"Etapa {c.etapa} · Intención {c.intencion} · Score {c.score}", "Escribirle hoy con un mensaje personal.", contact=c, level="media")
    if s["conversaciones_pendientes"] >= 5:
        crear_alerta(db, "CONVERSACIONES_SIN_RESPUESTA", f"CONV_SIN_RESPUESTA:{datetime.utcnow():%Y-%m-%d}",
                     f"🚨 {s['conversaciones_pendientes']} conversaciones esperan respuesta", None, "Bloquear 30 min hoy para responder, de mayor a menor score.", level="alta")
    problemas = []
    if s["duplicados"]:
        problemas.append(f"{s['duplicados']} duplicados")
    if s["sin_origen"] > max(3, 0.1 * s["contactos_total"]):
        problemas.append(f"{s['sin_origen']} contactos sin origen")
    if s["etiquetas_obsoletas"]:
        problemas.append(f"{s['etiquetas_obsoletas']} etiquetas obsoletas/duplicadas/sin uso")
    if problemas:
        crear_alerta(db, "PROBLEMA_SEGMENTACION", f"SEGMENTACION:{datetime.utcnow():%Y-%m-%d}", "🧹 Problema detectado en segmentación",
                     " · ".join(problemas), "Revisar la sección Propuestas y aprobar la limpieza.", level="baja")
    return s


# ── Ejecutar propuestas aprobadas ─────────────────────────────────────

def ejecutar_propuesta(db: Session, p: Proposal) -> str:
    if p.status != "aprobada":
        return "La propuesta no está aprobada."
    if p.type == "FUSIONAR_DUPLICADOS":
        principal = db.get(Contact, p.payload["principal"])
        hechos = 0
        for did in p.payload["duplicados"]:
            d = db.get(Contact, did)
            if d and principal and not d.merged_into_id:
                fusionar(db, principal, d)
                hechos += 1
        p.result = f"Fusionados {hechos} registros en #{principal.id if principal else '?'}"
    elif p.type == "RETIRAR_ETIQUETA":
        t = db.scalar(select(McTag).where(McTag.name == p.payload["tag"]))
        if t:
            t.classification = "OBSOLETA"
            t.reason = "Retirada por Claudia"
        p.result = f"Etiqueta «{p.payload['tag']}» marcada como retirada. Bórrala en ManyChat cuando quieras."
    else:
        p.result = "Tipo de propuesta sin ejecutor."
    p.status, p.executed_at = "ejecutada", datetime.utcnow()
    return p.result
