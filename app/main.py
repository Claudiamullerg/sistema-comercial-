"""Sistema Comercial · Claudia Müller — servidor web (FastAPI)."""
from __future__ import annotations

import asyncio
import csv
import io
import secrets
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import audit, hotmart, instagram, metrics, services, sync
from .config import PENDIENTE, settings
from .db import SessionLocal, get_db, init_db, session_scope
from .manychat import ManyChatClient, ManyChatError
from .models import Alert, Contact, Content, IgSnapshot, McTag, Proposal, SyncLog
from .taxonomy import (CAMPOS_MANYCHAT, ETAPAS, INTENCIONES, INTERESES, OPCIONES_PREGUNTA, ORIGENES, PREGUNTA_INTELIGENTE,
                       TIPOS_ALERTA, validar)

BASE = Path(__file__).resolve().parent
app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE / "templates"))
templates.env.globals.update(PENDIENTE=PENDIENTE, ETAPAS=ETAPAS, INTENCIONES=INTENCIONES, INTERESES=INTERESES, ORIGENES=ORIGENES,
                             TIPOS_ALERTA=TIPOS_ALERTA, app_name=settings.app_name)


def fmt_num(v):
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    if isinstance(v, float):
        return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{v:,}".replace(",", ".")


def fmt_dt(v, rel: bool = True):
    if not v:
        return "—"
    if rel:
        d = datetime.utcnow() - v
        if d < timedelta(minutes=1):
            return "ahora"
        if d < timedelta(hours=1):
            return f"hace {int(d.total_seconds() // 60)} min"
        if d < timedelta(days=1):
            return f"hace {int(d.total_seconds() // 3600)} h"
        if d < timedelta(days=30):
            return f"hace {d.days} d"
    return v.strftime("%d/%m/%Y %H:%M")


templates.env.filters["num"] = fmt_num
templates.env.filters["dt"] = fmt_dt


# ── Login mínimo (solo si PANEL_PASSWORD está definido) ──
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if settings.panel_password and not path.startswith(("/webhooks", "/login", "/static", "/health")):
        if request.cookies.get("panel") != _cookie_value():
            return RedirectResponse(f"/login?next={path}", status_code=303)
    return await call_next(request)


def _cookie_value() -> str:
    import hashlib
    return hashlib.sha256(("panel:" + settings.panel_password).encode()).hexdigest()[:32]


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


@app.post("/login")
def login(request: Request, password: str = Form(...), next: str = Form("/")):
    if secrets.compare_digest(password, settings.panel_password):
        r = RedirectResponse(next or "/", status_code=303)
        r.set_cookie("panel", _cookie_value(), httponly=True, max_age=60 * 60 * 24 * 30, samesite="lax")
        return r
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": "Contraseña incorrecta"})


# ── Arranque: crear tablas, sembrar línea base, tarea de fondo ──
@app.on_event("startup")
async def startup():
    init_db()
    with session_scope() as db:
        instagram.sembrar_linea_base(db)
        audit.correr_auditoria(db)
    if settings.manychat_refresh_minutes > 0:
        asyncio.create_task(_bucle_fondo())


async def _bucle_fondo():
    await asyncio.sleep(30)
    while True:
        try:
            with session_scope() as db:
                if settings.manychat_api_key:
                    sync.refrescar_pendientes(db)
                audit.correr_auditoria(db)
        except Exception as e:  # pragma: no cover
            with session_scope() as db:
                services.log_sync(db, "fondo", False, 0, str(e))
        await asyncio.sleep(max(settings.manychat_refresh_minutes, 5) * 60)


@app.get("/health")
def health():
    return {"ok": True, "app": settings.app_name}


# ── PANEL PRINCIPAL ──
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    snap = metrics.ultimo_snapshot(db)
    contenido = metrics.valor_comercial_contenido(db)
    return templates.TemplateResponse(request, "dashboard.html", {
        "resumen": metrics.resumen(db), "embudo": metrics.embudo(db, snap), "snap": snap, "mc": metrics.manychat_bloque(db),
        "pipeline": metrics.pipeline(db), "acciones": metrics.acciones_hoy(db), "alertas": metrics.alertas_abiertas(db)[:8],
        "salud": audit.salud(db), "contenido": contenido[:5], "conversion": metrics.conversion(db),
        "reels_hot": metrics.reels_sobre_promedio(db), "sync_ok": metrics.hay_sync(db),
        "mc_configurado": bool(settings.manychat_api_key),
    })


# ── CONTACTOS ──
@app.get("/contactos", response_class=HTMLResponse)
def contactos(request: Request, db: Session = Depends(get_db), q: str = "", etapa: str = "", intencion: str = "", interes: str = "",
              origen: str = "", pais: str = "", pendientes: str = "", orden: str = "score"):
    stmt = select(Contact).where(Contact.merged_into_id.is_(None))
    if q:
        like = f"%{q.strip().lstrip('@')}%"
        stmt = stmt.where(or_(Contact.ig_username.ilike(like), Contact.name.ilike(like), Contact.email.ilike(like), Contact.mc_last_input_text.ilike(like)))
    if etapa:
        stmt = stmt.where(Contact.etapa == etapa)
    if intencion:
        stmt = stmt.where(Contact.intencion == intencion)
    if interes:
        stmt = stmt.where(Contact.interes == interes)
    if origen:
        stmt = stmt.where(Contact.origen_tipo == origen)
    if pais:
        stmt = stmt.where(Contact.country == pais)
    if pendientes:
        stmt = stmt.where(Contact.needs_reply.is_(True))
    stmt = stmt.order_by(Contact.score.desc() if orden == "score" else Contact.updated_at.desc()).limit(300)
    rows = db.scalars(stmt).all()
    paises = [p for (p,) in db.execute(select(Contact.country).where(Contact.country.is_not(None)).distinct()).all()]
    return templates.TemplateResponse(request, "contactos.html", {"rows": rows, "q": q, "etapa": etapa, "intencion": intencion, "interes": interes,
                                                                  "origen": origen, "pais": pais, "pendientes": pendientes, "orden": orden, "paises": paises})


@app.get("/contactos/{cid}", response_class=HTMLResponse)
def contacto(request: Request, cid: int, db: Session = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    alertas = db.scalars(select(Alert).where(Alert.contact_id == cid).order_by(Alert.created_at.desc())).all()
    from .classify import recomendar_reactivacion
    return templates.TemplateResponse(request, "contacto.html", {"c": c, "alertas": alertas, "reactivacion": recomendar_reactivacion(c),
                                                                 "contenidos": db.scalars(select(Content).order_by(Content.title)).all()})


@app.post("/contactos/{cid}/accion")
def contacto_accion(cid: int, accion: str = Form(...), valor: str = Form(""), monto: str = Form(""), producto: str = Form(""),
                    moneda: str = Form("USD"), db: Session = Depends(get_db)):
    c = db.get(Contact, cid)
    if not c:
        raise HTTPException(404)
    try:
        if accion == "respondi":
            services.marcar_respondido(db, c, valor or None)
        elif accion == "etapa":
            services.cambiar_etapa(db, c, valor)
        elif accion == "nota":
            services.agregar_nota(db, c, valor)
        elif accion == "venta":
            services.registrar_venta(db, c, producto or "FRONTERA", float(monto or 0), moneda)
        elif accion == "interes":
            c.interes = validar(valor, INTERESES, "interes")
            services.log_event(db, c, "field_change", "interes", None, c.interes, "claudia")
            services.clasificar(db, c, source="claudia")
        elif accion == "origen":
            c.origen_tipo = validar(valor, ORIGENES, "origen")
            services.log_event(db, c, "field_change", "origen_tipo", None, c.origen_tipo, "claudia")
        elif accion == "contenido":
            ct = db.get(Content, int(valor)) if valor else None
            c.origen_content_id = ct.id if ct else None
            services.log_event(db, c, "field_change", "origen_contenido", None, ct.ref if ct else None, "claudia")
        elif accion == "no_interesado":
            c.temperatura, c.intencion, c.needs_reply = "NO_INTERESADO", "FRIA", False
            services.log_event(db, c, "field_change", "temperatura", None, "NO_INTERESADO", "claudia")
            for a in db.scalars(select(Alert).where(Alert.contact_id == c.id, Alert.status == "abierta")):
                a.status, a.resolved_at = "descartada", datetime.utcnow()
        elif accion == "seguimiento":
            c.next_followup_at = datetime.utcnow() + timedelta(days=int(valor or 3))
            services.log_event(db, c, "note", new=f"Seguimiento programado en {valor or 3} días", source="claudia")
        if settings.manychat_writeback and settings.manychat_api_key and c.manychat_id:
            try:
                sync.escribir_segmentacion(db, c)
            except ManyChatError as e:
                services.log_sync(db, "writeback", False, 0, str(e))
        db.commit()
    except ValueError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    return RedirectResponse(f"/contactos/{cid}", status_code=303)


# ── CONTENIDO (Reels) ──
@app.get("/contenido", response_class=HTMLResponse)
def contenido(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "contenido.html", {"filas": metrics.valor_comercial_contenido(db), "ig_ok": instagram.InstagramClient().configured})


@app.post("/contenido")
def contenido_guardar(request: Request, db: Session = Depends(get_db), id: str = Form(""), title: str = Form(...), type: str = Form("REEL"),
                      keyword: str = Form(""), url: str = Form(""), views: str = Form(""), interactions: str = Form(""),
                      followers_gained: str = Form(""), reach: str = Form(""), published_at: str = Form("")):
    def n(v):
        v = v.replace(".", "").replace(",", "").strip()
        return int(v) if v else None
    if id:
        ct = db.get(Content, int(id))
        if not ct:
            raise HTTPException(404)
        ct.title = title
    else:
        ct = services.get_or_create_content(db, title, type, keyword or None)
    ct.type, ct.keyword, ct.url = type, keyword or None, url or None
    ct.views, ct.interactions, ct.followers_gained, ct.reach = n(views), n(interactions), n(followers_gained), n(reach)
    if published_at:
        try:
            ct.published_at = datetime.fromisoformat(published_at)
        except ValueError:
            pass
    db.commit()
    return RedirectResponse("/contenido", status_code=303)


# ── ALERTAS ──
@app.get("/alertas", response_class=HTMLResponse)
def alertas(request: Request, db: Session = Depends(get_db), todas: str = ""):
    if todas:
        rows = db.scalars(select(Alert).order_by(Alert.created_at.desc()).limit(200)).all()
    else:
        rows = metrics.alertas_abiertas(db)
    return templates.TemplateResponse(request, "alertas.html", {"rows": rows, "todas": todas})


@app.post("/alertas/{aid}/{accion}")
def alerta_accion(aid: int, accion: str, db: Session = Depends(get_db), next: str = Form("/alertas")):
    a = db.get(Alert, aid)
    if not a:
        raise HTTPException(404)
    a.status = "resuelta" if accion == "resolver" else "descartada"
    a.resolved_at = datetime.utcnow()
    db.commit()
    return RedirectResponse(next, status_code=303)


# ── SALUD DEL SISTEMA ──
@app.get("/salud", response_class=HTMLResponse)
def salud(request: Request, db: Session = Depends(get_db)):
    clases = audit.clasificar_etiquetas(db)
    db.commit()
    autos = metrics.automatizaciones(db)
    s = audit.salud(db)
    s["automatizaciones_con_problemas"] = sum(1 for a in autos if a["problema"])
    return templates.TemplateResponse(request, "salud.html", {
        "s": s, "tags": db.scalars(select(McTag).order_by(McTag.classification, McTag.contact_count.desc())).all(), "clases": clases,
        "duplicados": audit.detectar_duplicados(db), "sin_seguimiento": audit.leads_sin_seguimiento(db)[:30],
        "pendientes": audit.conversaciones_pendientes(db)[:30], "abandonadas": audit.conversaciones_abandonadas(db)[:30],
        "reactivacion": audit.segmentos_reactivacion(db), "autos": autos, "paises": metrics.por_pais(db),
        "propuestas_abiertas": db.scalar(select(func.count(Proposal.id)).where(Proposal.status == "propuesta")) or 0,
        "archivables": audit.archivables_en_manychat(db),
    })


@app.get("/exportar-archivables.csv")
def exportar_archivables(db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["manychat_id", "ig_username", "name", "ultima_interaccion", "etapa", "temperatura"])
    for c in audit.archivables_en_manychat(db):
        w.writerow([c.manychat_id, c.ig_username, c.name, (c.last_inbound_at or c.mc_last_interaction or c.created_at), c.etapa, c.temperatura])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=archivables-manychat.csv"})


@app.post("/salud/auditar")
def auditar(db: Session = Depends(get_db)):
    audit.correr_auditoria(db)
    db.commit()
    return RedirectResponse("/salud", status_code=303)


# ── PROPUESTAS (aprobar → ejecutar) ──
@app.get("/propuestas", response_class=HTMLResponse)
def propuestas(request: Request, db: Session = Depends(get_db)):
    rows = db.scalars(select(Proposal).order_by(Proposal.status, Proposal.created_at.desc())).all()
    return templates.TemplateResponse(request, "propuestas.html", {"rows": rows})


@app.post("/propuestas/{pid}/{accion}")
def propuesta_accion(pid: int, accion: str, db: Session = Depends(get_db)):
    p = db.get(Proposal, pid)
    if not p:
        raise HTTPException(404)
    if accion == "aprobar":
        p.status = "aprobada"
    elif accion == "rechazar":
        p.status = "rechazada"
    elif accion == "ejecutar":
        audit.ejecutar_propuesta(db, p)
    db.commit()
    return RedirectResponse("/propuestas", status_code=303)


# ── CONFIGURACIÓN / SINCRONIZACIÓN ──
@app.get("/configuracion", response_class=HTMLResponse)
def configuracion(request: Request, db: Session = Depends(get_db), msg: str = ""):
    base_url = str(request.base_url).rstrip("/")
    logs = db.scalars(select(SyncLog).order_by(SyncLog.created_at.desc()).limit(40)).all()
    snap = metrics.ultimo_snapshot(db)
    return templates.TemplateResponse(request, "configuracion.html", {
        "base_url": base_url, "secret": settings.webhook_secret, "mc_ok": bool(settings.manychat_api_key), "writeback": settings.manychat_writeback,
        "ig_ok": instagram.InstagramClient().configured, "hotmart_ok": bool(settings.hotmart_hottok), "logs": logs, "snap": snap, "msg": msg,
        "campos": CAMPOS_MANYCHAT, "pregunta": PREGUNTA_INTELIGENTE, "opciones": OPCIONES_PREGUNTA,
        "n_tags": db.scalar(select(func.count(McTag.id))) or 0, "refresh": settings.manychat_refresh_minutes,
    })


@app.post("/configuracion/instagram")
def instagram_manual(db: Session = Depends(get_db), period_start: str = Form(...), period_end: str = Form(...), views: str = Form(""),
                     viewers: str = Form(""), non_follower_pct: str = Form(""), net_followers: str = Form(""), followers_total: str = Form(""),
                     profile_visits: str = Form(""), link_clicks: str = Form(""), reels_views: str = Form(""), reels_interactions: str = Form(""),
                     stories_views: str = Form(""), posts_views: str = Form("")):
    def n(v):
        v = v.replace(".", "").replace(",", ".").strip() if "," in v and v.count(",") == 1 and len(v.split(",")[1]) <= 2 else v.replace(".", "").strip()
        try:
            return float(v) if "." in v else int(v)
        except ValueError:
            return None
    ps, pe = datetime.fromisoformat(period_start), datetime.fromisoformat(period_end)
    snap = db.scalar(select(IgSnapshot).where(IgSnapshot.period_start == ps, IgSnapshot.period_end == pe)) or IgSnapshot(period_start=ps, period_end=pe)
    snap.views, snap.viewers, snap.net_followers, snap.followers_total = n(views), n(viewers), n(net_followers), n(followers_total)
    nf = n(non_follower_pct)
    snap.non_follower_pct, snap.follower_pct = nf, (round(100 - nf, 1) if nf is not None else None)
    snap.profile_visits, snap.link_clicks = n(profile_visits), n(link_clicks)
    snap.views_by_type = {"REEL": n(reels_views), "HISTORIA": n(stories_views), "POST": n(posts_views)}
    snap.interactions_by_type = {"REEL": n(reels_interactions)}
    snap.source = "manual"
    db.add(snap)
    db.commit()
    return RedirectResponse("/configuracion?msg=Instagram+actualizado", status_code=303)


@app.post("/configuracion/claves")
def guardar_claves(manychat_api_key: str = Form(""), hotmart_hottok: str = Form(""), webhook_secret: str = Form(""), manychat_writeback: str = Form("")):
    """Guarda claves en el archivo .env (sin pasar por el chat) y las aplica al momento."""
    from .config import BASE_DIR
    env_path = BASE_DIR / ".env"
    lineas = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    nuevos = {"MANYCHAT_API_KEY": manychat_api_key.strip(), "HOTMART_HOTTOK": hotmart_hottok.strip(), "WEBHOOK_SECRET": webhook_secret.strip(),
              "MANYCHAT_WRITEBACK": "true" if manychat_writeback else ""}
    cambiados = []
    for clave, valor in nuevos.items():
        if valor == "" and clave != "MANYCHAT_WRITEBACK":
            continue  # vacío = no tocar
        if clave == "MANYCHAT_WRITEBACK":
            valor = "true" if manychat_writeback else "false"
        hecho = False
        for i, ln in enumerate(lineas):
            if ln.split("=", 1)[0].strip() == clave:
                lineas[i] = f"{clave}={valor}"
                hecho = True
        if not hecho:
            lineas.append(f"{clave}={valor}")
        cambiados.append(clave)
    env_path.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    if nuevos["MANYCHAT_API_KEY"]:
        settings.manychat_api_key = nuevos["MANYCHAT_API_KEY"]
    if nuevos["HOTMART_HOTTOK"]:
        settings.hotmart_hottok = nuevos["HOTMART_HOTTOK"]
    if nuevos["WEBHOOK_SECRET"]:
        settings.webhook_secret = nuevos["WEBHOOK_SECRET"]
    settings.manychat_writeback = bool(manychat_writeback)
    return RedirectResponse(f"/configuracion?msg=Guardado:+{',+'.join(cambiados)}", status_code=303)


@app.post("/configuracion/prueba")
def contacto_de_prueba(db: Session = Depends(get_db)):
    """Simula lo que ManyChat enviará: un contacto de prueba que pregunta precio. Se borra con el botón de al lado."""
    n = (db.scalar(select(func.count(Contact.id)).where(Contact.ig_username.like("prueba_%"))) or 0) + 1
    body = {"evento": "ENTRADA", "subscriber_id": f"prueba-{n}", "ig_username": f"prueba_maria{n if n > 1 else ''}", "name": "María (contacto de prueba)",
            "origen_tipo": "REEL", "origen_contenido": "reel-es-muy-caro", "keyword": "FRONTERA", "automatizacion": "Reel es muy caro → FRONTERA",
            "last_input_text": "Hola Claudia, cuánto cuesta la sesión y cómo trabajas?"}
    sync.procesar_webhook(db, body)
    db.commit()
    return RedirectResponse("/?msg=prueba", status_code=303)


@app.post("/configuracion/borrar-prueba")
def borrar_prueba(db: Session = Depends(get_db)):
    """Borra SOLO los contactos de prueba (usuario que empieza por prueba_) y todo lo suyo."""
    from .models import ContactEvent, Sale
    ids = [i for (i,) in db.execute(select(Contact.id).where(Contact.ig_username.like("prueba_%"))).all()]
    for cid in ids:
        for tabla in (Alert, ContactEvent, Sale):
            for row in db.scalars(select(tabla).where(tabla.contact_id == cid)):
                db.delete(row)
        db.delete(db.get(Contact, cid))
    db.commit()
    return RedirectResponse(f"/configuracion?msg=Borrados+{len(ids)}+contactos+de+prueba", status_code=303)


@app.post("/importar")
async def importar(db: Session = Depends(get_db), archivo: UploadFile = None, origen_tipo: str = Form("IMPORTACION")):
    if not archivo:
        raise HTTPException(400, "Falta el archivo")
    contenido = await archivo.read()
    r = sync.importar_csv(db, contenido, origen_tipo)
    db.commit()
    return RedirectResponse(f"/configuracion?msg=Importados+{r['nuevos']}+nuevos+y+{r['actualizados']}+actualizados", status_code=303)


@app.post("/sync/manychat/{accion}")
def sync_manychat(accion: str, db: Session = Depends(get_db)):
    try:
        if accion == "catalogos":
            r = sync.sincronizar_catalogos(db)
            msg = f"Catálogos: {r}"
        elif accion == "refrescar":
            n = sync.refrescar_pendientes(db)
            msg = f"{n} contactos refrescados"
        elif accion == "campos":
            creados = sync.asegurar_campos_crm(db)
            msg = f"Campos CRM creados: {', '.join(creados) or 'ninguno (ya existían)'}"
        else:
            raise HTTPException(404)
        db.commit()
    except ManyChatError as e:
        db.rollback()
        with session_scope() as s:
            services.log_sync(s, "manychat", False, 0, str(e))
        msg = f"Error ManyChat: {e}"
    return RedirectResponse(f"/configuracion?msg={msg}", status_code=303)


@app.post("/sync/instagram")
def sync_ig(db: Session = Depends(get_db)):
    r = instagram.sincronizar_instagram(db)
    db.commit()
    return RedirectResponse(f"/configuracion?msg={r}", status_code=303)


# ── WEBHOOKS ──
@app.post("/webhooks/manychat")
async def webhook_manychat(request: Request, secret: str = "", db: Session = Depends(get_db)):
    if settings.webhook_secret and secret != settings.webhook_secret:
        raise HTTPException(401, "secret inválido")
    try:
        body = await request.json()
    except Exception:
        form = await request.form()
        body = dict(form)
    r = sync.procesar_webhook(db, body)
    db.commit()
    # ManyChat puede mapear estos valores a campos con "Response Mapping"
    return JSONResponse(r)


@app.post("/webhooks/hotmart")
async def webhook_hotmart(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    r = hotmart.procesar_hotmart(db, body, settings.hotmart_hottok or None)
    db.commit()
    return JSONResponse(r)


# ── API / EXPORT ──
@app.get("/api/resumen")
def api_resumen(db: Session = Depends(get_db)):
    return {"resumen": metrics.resumen(db), "pipeline": metrics.pipeline(db), "salud": audit.salud(db), "manychat": metrics.manychat_bloque(db)}


@app.get("/exportar.csv")
def exportar(db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["id", "manychat_id", "ig_username", "name", "email", "phone", "country", "origen_tipo", "origen_keyword", "origen_automation",
            "interes", "intencion", "etapa", "temperatura", "score", "needs_reply", "last_inbound_at", "last_human_touch", "created_at"]
    w.writerow(cols + ["origen_contenido"])
    for c in db.scalars(select(Contact).where(Contact.merged_into_id.is_(None))).all():
        w.writerow([getattr(c, k) for k in cols] + [c.origen_content.ref if c.origen_content else ""])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=contactos.csv"})
