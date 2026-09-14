"""Números del panel: HOY, SEMANA, embudo, pipeline, ManyChat, atribución por Reel, país."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import PENDIENTE, settings
from .models import Alert, Contact, ContactEvent, Content, IgSnapshot, Sale, SyncLog
from .taxonomy import ETAPA_RANGO, ETAPAS


def _activos(db: Session):
    return db.scalars(select(Contact).where(Contact.merged_into_id.is_(None))).all()


def _o_pendiente(valor, hay_datos: bool):
    return valor if hay_datos else PENDIENTE


def hay_sync(db: Session) -> bool:
    return db.scalar(select(func.count(Contact.id)).where(Contact.sync_status == "OK")) > 0


def _desde(db: Session, contactos, dias: int) -> dict:
    desde = datetime.utcnow() - timedelta(days=dias)
    nuevos = [c for c in contactos if c.created_at >= desde]
    conv = [c for c in contactos if (c.last_inbound_at and c.last_inbound_at >= desde)]
    leads = [c for c in nuevos if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"]]
    calientes = [c for c in contactos if c.intencion in ("CALIENTE", "COMPRA") and c.etapa not in ("VENTA", "CLIENTE")]
    oport = db.scalar(select(func.count(ContactEvent.id)).where(ContactEvent.type == "stage_change", ContactEvent.new_value == "OPORTUNIDAD", ContactEvent.created_at >= desde)) or 0
    ventas = db.scalars(select(Sale).where(Sale.sold_at >= desde)).all()
    return {
        "contactos_nuevos": len(nuevos), "conversaciones": len(conv), "leads": len(leads), "calientes": len(calientes),
        "oportunidades": oport, "ventas": len(ventas), "ingresos": round(sum(s.amount for s in ventas), 2),
        "tasa_conversion": round(100 * len(ventas) / len(leads), 1) if leads else 0.0,
    }


def resumen(db: Session) -> dict:
    contactos = _activos(db)
    return {"hoy": _desde(db, contactos, 1), "semana": _desde(db, contactos, 7), "mes": _desde(db, contactos, 30)}


def pipeline(db: Session) -> dict:
    contactos = _activos(db)
    conteo = {e: 0 for e in ETAPAS}
    for c in contactos:
        conteo[c.etapa] = conteo.get(c.etapa, 0) + 1
    return conteo


def embudo(db: Session, snap: IgSnapshot | None) -> list[dict]:
    """Visualizaciones → Perfil → Click → DM → Lead → Conversación → Oportunidad → Venta (§19)."""
    contactos = _activos(db)
    sync = hay_sync(db)
    dms = len(contactos)
    leads = sum(1 for c in contactos if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"])
    convs = sum(1 for c in contactos if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["CONVERSACION"])
    oport = sum(1 for c in contactos if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["OPORTUNIDAD"])
    ventas = sum(1 for c in contactos if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["VENTA"])
    pasos = [
        ("Visualizaciones", snap.views if snap else None, "instagram"),
        ("Visitas al perfil", snap.profile_visits if snap else None, "instagram"),
        ("Clicks en enlace", snap.link_clicks if snap else None, "instagram"),
        ("DM / Contactos", _o_pendiente(dms, sync), "manychat"),
        ("Leads", _o_pendiente(leads, sync), "app"),
        ("Conversaciones", _o_pendiente(convs, sync), "app"),
        ("Oportunidades", _o_pendiente(oport, sync), "app"),
        ("Ventas", ventas if (sync or ventas) else _o_pendiente(ventas, sync), "app"),
    ]
    out, prev = [], None
    for nombre, valor, fuente in pasos:
        tasa = None
        if isinstance(valor, int) and isinstance(prev, int) and prev > 0:
            tasa = round(100 * valor / prev, 2)
        out.append({"nombre": nombre, "valor": valor, "tasa": tasa, "fuente": fuente})
        prev = valor if isinstance(valor, int) else prev
    return out


def manychat_bloque(db: Session) -> dict:
    contactos = _activos(db)
    sync = hay_sync(db)
    ahora = datetime.utcnow()
    inact = ahora - timedelta(days=settings.dias_inactivo)
    ultimo = db.scalar(select(SyncLog).where(SyncLog.kind.in_(["webhook", "api_refresh", "csv_import"])).order_by(SyncLog.created_at.desc()))
    def n(pred):
        return _o_pendiente(sum(1 for c in contactos if pred(c)), sync)
    return {
        "sincronizado": sync,
        "ultima_sync": ultimo.created_at if ultimo else None,
        "total": _o_pendiente(len(contactos), sync),
        "activos": n(lambda c: (c.mc_last_interaction or c.created_at) >= inact and (c.mc_status or "active").lower() not in ("unsubscribed",)),
        "inactivos": n(lambda c: (c.mc_last_interaction or c.created_at) < inact),
        "nuevos_7d": n(lambda c: c.created_at >= ahora - timedelta(days=7)),
        "interactuaron_7d": n(lambda c: (c.last_inbound_at or c.mc_last_interaction or datetime.min) >= ahora - timedelta(days=7)),
        "dejaron_de_interactuar": n(lambda c: (c.interacciones or 0) > 0 and (c.last_inbound_at or c.created_at) < inact),
        "conversaciones_abiertas": n(lambda c: c.needs_reply),
        "respuestas": _o_pendiente(db.scalar(select(func.count(ContactEvent.id)).where(ContactEvent.type == "message_in")) or 0, sync),
        "sin_respuesta": n(lambda c: c.needs_reply),
        "calientes": n(lambda c: c.intencion in ("CALIENTE", "COMPRA")),
        "leads_nuevos_7d": n(lambda c: c.created_at >= ahora - timedelta(days=7) and ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"]),
        "leads_calificados": n(lambda c: c.interes is not None and ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"]),
        "leads_sin_calificar": n(lambda c: c.interes is None and ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"]),
        "leads_en_nutricion": n(lambda c: c.intencion in ("FRIA", "TIBIA") and ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"] and c.etapa not in ("VENTA", "CLIENTE")),
        "leads_listos_oferta": n(lambda c: c.intencion in ("CALIENTE", "COMPRA") and c.etapa not in ("VENTA", "CLIENTE")),
        "opt_in_email": n(lambda c: bool(c.email)),
        "opt_in_telefono": n(lambda c: bool(c.phone)),
    }


def conversion(db: Session) -> dict:
    contactos = _activos(db)
    sync = hay_sync(db)
    def cnt(etapa):
        return sum(1 for c in contactos if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO[etapa])
    leads, conv, ses, venta = cnt("LEAD"), cnt("CONVERSACION"), cnt("SESION_OFERTA"), cnt("VENTA")
    def pct(a, b):
        return round(100 * a / b, 1) if b else None
    return {"lead_conversacion": _o_pendiente(pct(conv, leads), sync), "conversacion_sesion": _o_pendiente(pct(ses, conv), sync),
            "sesion_oferta_venta": _o_pendiente(pct(venta, ses), sync), "oferta_venta": _o_pendiente(pct(venta, ses), sync)}


def automatizaciones(db: Session) -> list[dict]:
    """Estadísticas por automatización a partir de los eventos que llegaron por webhook."""
    contactos = _activos(db)
    por = defaultdict(lambda: {"entradas": 0, "respondieron": 0, "clicks": 0, "leads": 0, "oportunidades": 0, "ventas": 0, "abandonaron": 0})
    for c in contactos:
        k = c.origen_automation or (c.mc_last_growth_tool or "(sin automatización registrada)")
        d = por[k]
        d["entradas"] += 1
        d["respondieron"] += 1 if (c.respuesta_pregunta or (c.interacciones or 0) > 0) else 0
        d["clicks"] += c.clicks or 0
        d["leads"] += 1 if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"] else 0
        d["oportunidades"] += 1 if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["OPORTUNIDAD"] else 0
        d["ventas"] += 1 if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["VENTA"] else 0
        d["abandonaron"] += 1 if not c.respuesta_pregunta and (c.interacciones or 0) == 0 else 0
    out = []
    for k, d in por.items():
        d["nombre"] = k
        d["completaron"] = d["respondieron"]
        d["tasa_respuesta"] = round(100 * d["respondieron"] / d["entradas"], 1) if d["entradas"] else 0
        d["problema"] = d["entradas"] >= 10 and d["tasa_respuesta"] < 15
        out.append(d)
    return sorted(out, key=lambda x: -x["entradas"])


def valor_comercial_contenido(db: Session) -> list[dict]:
    """Por cada Reel/post: Alcance · Conversación · Negocio (§20-21)."""
    contactos = _activos(db)
    contenidos = db.scalars(select(Content)).all()
    por_id = defaultdict(list)
    for c in contactos:
        if c.origen_content_id:
            por_id[c.origen_content_id].append(c)
    filas = []
    for ct in contenidos:
        cs = por_id.get(ct.id, [])
        leads = sum(1 for c in cs if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"])
        conv = sum(1 for c in cs if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["CONVERSACION"])
        oport = sum(1 for c in cs if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["OPORTUNIDAD"])
        ventas = sum(1 for c in cs if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["VENTA"])
        ingresos = sum(s.amount for c in cs for s in c.sales)
        calientes = sum(1 for c in cs if c.intencion in ("CALIENTE", "COMPRA"))
        filas.append({
            "id": ct.id, "ref": ct.ref, "title": ct.title or ct.ref, "type": ct.type, "keyword": ct.keyword, "url": ct.url,
            "views": ct.views, "interactions": ct.interactions, "followers_gained": ct.followers_gained,
            "contactos": len(cs), "leads": leads, "conversaciones": conv, "oportunidades": oport, "ventas": ventas, "ingresos": round(ingresos, 2),
            "calientes": calientes,
            # tres indicadores
            "alcance": ct.views or 0,
            "conversacion": len(cs),
            "negocio": oport + ventas * 3 + calientes,
            "contactos_por_mil_views": round(1000 * len(cs) / ct.views, 2) if ct.views else None,
            "leads_por_mil_views": round(1000 * leads / ct.views, 2) if ct.views else None,
        })
    # Etiqueta cualitativa: viral+bajo negocio / poco viral+alto negocio / etc.
    if filas:
        med_alc = sorted(f["alcance"] for f in filas)[len(filas) // 2]
        med_neg = sorted(f["negocio"] for f in filas)[len(filas) // 2]
        for f in filas:
            viral = f["alcance"] >= max(med_alc, 1)
            negocio = f["negocio"] > med_neg or (f["negocio"] > 0 and med_neg == 0)
            f["veredicto"] = ("Viral + negocio ✅" if viral and negocio else "Viral, bajo negocio" if viral else
                              "Poco viral, ALTO negocio ★" if negocio else "Bajo en ambos")
    return sorted(filas, key=lambda f: (-f["negocio"], -f["conversacion"], -f["alcance"]))


def reels_sobre_promedio(db: Session) -> list[dict]:
    """Detecta Reels que están generando contactos por encima del promedio en las últimas 24 h."""
    desde = datetime.utcnow() - timedelta(hours=24)
    contactos = [c for c in _activos(db) if c.created_at >= desde and c.origen_content_id]
    if len(contactos) < 5:
        return []
    por = defaultdict(int)
    for c in contactos:
        por[c.origen_content_id] += 1
    prom = len(contactos) / max(len(por), 1)
    out = []
    for cid, n in por.items():
        if n >= 5 and n > 1.5 * prom:
            ct = db.get(Content, cid)
            out.append({"content": ct, "contactos_24h": n, "promedio": round(prom, 1)})
    return out


def por_pais(db: Session) -> list[dict]:
    contactos = _activos(db)
    por = defaultdict(lambda: {"contactos": 0, "leads": 0, "calientes": 0, "ventas": 0, "ingresos": 0.0})
    for c in contactos:
        d = por[c.country or "sin país"]
        d["contactos"] += 1
        d["leads"] += 1 if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["LEAD"] else 0
        d["calientes"] += 1 if c.intencion in ("CALIENTE", "COMPRA") else 0
        d["ventas"] += 1 if ETAPA_RANGO[c.etapa] >= ETAPA_RANGO["VENTA"] else 0
        d["ingresos"] += sum(s.amount for s in c.sales)
    out = []
    for k, d in por.items():
        d["pais"] = k
        d["tasa_lead"] = round(100 * d["leads"] / d["contactos"], 1) if d["contactos"] else 0
        d["tasa_venta"] = round(100 * d["ventas"] / d["leads"], 1) if d["leads"] else 0
        out.append(d)
    return sorted(out, key=lambda x: -x["contactos"])


def acciones_hoy(db: Session, limite: int = 5) -> list[dict]:
    """«Claudia, hoy debes hablar con estas 5 personas.»"""
    contactos = [c for c in _activos(db) if c.etapa not in ("VENTA", "CLIENTE")]
    ahora = datetime.utcnow()
    puntuadas = []
    for c in contactos:
        prio = c.score
        motivo = None
        if c.intent_label in ("INTENCION_COMPRA",):
            prio += 100; motivo = "Quiere comprar"
        elif c.intent_label == "PREGUNTA_OFERTA":
            prio += 60; motivo = "Pidió información"
        elif c.needs_reply:
            prio += 40; motivo = "Escribió y espera respuesta"
        elif c.next_followup_at and c.next_followup_at <= ahora and c.intencion in ("TIBIA", "CALIENTE", "COMPRA"):
            prio += 30; motivo = "Toca seguimiento"
        elif c.intencion in ("CALIENTE", "COMPRA"):
            prio += 25; motivo = "Lead caliente"
        if motivo:
            puntuadas.append((prio, c, motivo))
    puntuadas.sort(key=lambda x: -x[0])
    return [{"contact": c, "motivo": m, "prioridad": p} for p, c, m in puntuadas[:limite]]


def alertas_abiertas(db: Session) -> list[Alert]:
    orden = {"alta": 0, "media": 1, "baja": 2}
    als = db.scalars(select(Alert).where(Alert.status == "abierta").order_by(Alert.created_at.desc())).all()
    return sorted(als, key=lambda a: (orden.get(a.level, 3), -a.created_at.timestamp()))


def ultimo_snapshot(db: Session) -> IgSnapshot | None:
    return db.scalar(select(IgSnapshot).order_by(IgSnapshot.period_end.desc()))
