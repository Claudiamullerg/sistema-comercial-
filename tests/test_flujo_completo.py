"""Prueba del flujo completo: Reel → ManyChat → webhook → contacto → clasificación → alerta → panel → venta.

Los datos de estas pruebas son de PRUEBA (usuarios inventados con prefijo test_). Nunca se cargan en la app real.
"""
import os
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = f"sqlite:///{Path(tempfile.mkdtemp()) / 'test.db'}"
os.environ["WEBHOOK_SECRET"] = "secreto-test"
os.environ["MANYCHAT_REFRESH_MINUTES"] = "0"
os.environ["PANEL_PASSWORD"] = ""

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import audit, sync  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.manychat import ManyChatClient  # noqa: E402
from app.models import Alert, Contact, Proposal  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


WH = "/webhooks/manychat?secret=secreto-test"


def test_panel_antes_de_sync_muestra_pendiente(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "PENDIENTE DE SINCRONIZACIÓN" in r.text
    assert "1.649.894" in r.text  # línea base de Instagram sembrada


def test_webhook_rechaza_secret_malo(client):
    assert client.post("/webhooks/manychat?secret=malo", json={"subscriber_id": "1"}).status_code == 401


def test_entrada_desde_reel_crea_contacto_con_origen(client):
    body = {"evento": "ENTRADA", "subscriber_id": "1001", "ig_username": "test_maria", "name": "María Test", "origen_tipo": "REEL",
            "origen_contenido": "reel-es-muy-caro", "keyword": "FRONTERA", "automatizacion": "Reel es muy caro → FRONTERA", "last_input_text": "FRONTERA"}
    r = client.post(WH, json=body)
    assert r.status_code == 200 and r.json()["nuevo"] is True
    with SessionLocal() as db:
        c = db.query(Contact).filter_by(manychat_id="1001").one()
        assert c.origen_tipo == "REEL" and c.origen_content.ref == "reel-es-muy-caro" and c.origen_keyword == "FRONTERA"
        assert c.etapa in ("INTERACTUO", "LEAD") and c.intencion == "FRIA"
        assert any(e.type == "created" for e in c.events)


def test_respuesta_pregunta_clasifica_interes(client):
    body = {"evento": "RESPUESTA", "subscriber_id": "1001", "ig_username": "test_maria", "respuesta": "Quiero convertir mi experiencia en un negocio"}
    client.post(WH, json=body)
    with SessionLocal() as db:
        c = db.query(Contact).filter_by(manychat_id="1001").one()
        assert c.interes == "MONETIZACION" and c.etapa == "INTERES" and c.score > 0


def test_pregunta_de_precio_dispara_alerta_y_accion(client):
    body = {"evento": "ENTRADA", "subscriber_id": "1001", "ig_username": "test_maria", "last_input_text": "Hola, cuánto cuesta la sesión?"}
    r = client.post(WH, json=body).json()
    assert r["etapa"] == "CONVERSACION" and r["intencion"] in ("TIBIA", "CALIENTE")
    with SessionLocal() as db:
        c = db.query(Contact).filter_by(manychat_id="1001").one()
        assert c.needs_reply and c.intent_label == "PREGUNTA_OFERTA"
        assert db.query(Alert).filter_by(contact_id=c.id, type="PIDIO_INFO", status="abierta").count() == 1
    panel = client.get("/").text
    assert "@test_maria" in panel and "Pidió información" in panel


def test_intencion_de_compra_es_oportunidad_y_lead_caliente(client):
    body = {"evento": "ENTRADA", "subscriber_id": "1002", "ig_username": "test_lucia", "origen_tipo": "REEL", "origen_contenido": "reel-es-muy-caro",
            "last_input_text": "quiero agendar la sesión, cómo pago?"}
    r = client.post(WH, json=body).json()
    assert r["etapa"] == "OPORTUNIDAD" and r["intencion"] == "COMPRA"
    with SessionLocal() as db:
        c = db.query(Contact).filter_by(manychat_id="1002").one()
        tipos = {a.type for a in db.query(Alert).filter_by(contact_id=c.id, status="abierta")}
        assert "INTENCION_COMPRA" in tipos and "LEAD_CALIENTE" in tipos


def test_full_contact_data_de_manychat(client):
    body = {"id": "1003", "key": "user:1003", "status": "active", "first_name": "Ana", "last_name": "Test", "ig_username": "test_ana",
            "subscribed": "2026-09-10T10:00:00+00:00", "last_interaction": "2026-09-12T18:30:00+00:00", "last_input_text": "no sé qué hacer con mi carrera",
            "last_growth_tool": "Reel comentarios 'como funcionan los negocios'", "phone": "+573001234567",
            "custom_fields": [{"id": 1, "name": "CRM_ORIGEN_CONTENIDO", "type": "text", "value": "reel-como-funcionan-los-negocios"}],
            "tags": [{"id": 5, "name": "frio"}, {"id": 6, "name": "Frío"}]}
    r = client.post(WH, json=body).json()
    assert r["ok"]
    with SessionLocal() as db:
        c = db.query(Contact).filter_by(manychat_id="1003").one()
        assert c.country == "CO" and c.origen_tipo == "REEL" and c.origen_content.ref == "reel-como-funcionan-los-negocios"
        assert c.intent_label == "PROBLEMA_IDENTIFICADO" and c.etapa == "INTERES"


def test_acciones_de_claudia(client):
    with SessionLocal() as db:
        cid = db.query(Contact).filter_by(manychat_id="1001").one().id
    assert client.post(f"/contactos/{cid}/accion", data={"accion": "respondi", "valor": "le mandé audio"}).status_code == 200
    assert client.post(f"/contactos/{cid}/accion", data={"accion": "etapa", "valor": "SESION_OFERTA"}).status_code == 200
    with SessionLocal() as db:
        c = db.get(Contact, cid)
        assert not c.needs_reply and c.etapa == "SESION_OFERTA" and c.last_human_touch is not None
        assert db.query(Alert).filter_by(contact_id=cid, type="PIDIO_INFO", status="abierta").count() == 0
    assert client.post(f"/contactos/{cid}/accion", data={"accion": "etapa", "valor": "INVENTADA"}).status_code == 400


def test_hotmart_registra_venta_atribuida(client):
    # Primero llega el email por ManyChat, luego Hotmart avisa la compra
    client.post(WH, json={"evento": "RESPUESTA", "subscriber_id": "1001", "email": "maria@test.com"})
    body = {"event": "PURCHASE_APPROVED", "data": {"buyer": {"email": "maria@test.com", "name": "María Test", "address": {"country_iso": "CO"}},
                                                     "purchase": {"transaction": "HP123", "price": {"value": 197, "currency_value": "USD"}},
                                                     "product": {"name": "FRONTERA"}}}
    r = client.post("/webhooks/hotmart", json=body).json()
    assert r.get("venta") is True
    with SessionLocal() as db:
        c = db.query(Contact).filter_by(manychat_id="1001").one()
        assert c.etapa == "VENTA" and c.sales[0].amount == 197 and c.origen_content.ref == "reel-es-muy-caro"
    contenido = client.get("/contenido").text
    assert "reel-es-muy-caro" in contenido or "es muy caro" in contenido


def test_duplicados_propuesta_aprobar_ejecutar(client):
    client.post(WH, json={"evento": "ENTRADA", "subscriber_id": "1004", "ig_username": "test_dup", "last_input_text": "hola"})
    client.post(WH, json={"evento": "ENTRADA", "subscriber_id": "1005", "email": "dup@test.com", "last_input_text": "hola"})
    with SessionLocal() as db:
        # simular que el segundo registro también es test_dup pero llegó sin username y luego lo trae por CSV
        c2 = db.query(Contact).filter_by(manychat_id="1005").one()
        c2.ig_username = "test_dup"
        db.commit()
        audit.correr_auditoria(db)
        db.commit()
        p = db.query(Proposal).filter(Proposal.type == "FUSIONAR_DUPLICADOS").first()
        assert p is not None and p.status == "propuesta"
        pid = p.id
    client.post(f"/propuestas/{pid}/aprobar")
    client.post(f"/propuestas/{pid}/ejecutar")
    with SessionLocal() as db:
        p = db.get(Proposal, pid)
        assert p.status == "ejecutada"
        activos = db.query(Contact).filter(Contact.ig_username == "test_dup", Contact.merged_into_id.is_(None)).count()
        assert activos == 1


def test_importar_csv(client):
    csv_text = "Subscriber ID,Instagram Username,Full Name,Email,Tags,Last Interaction\n2001,test_csv1,CSV Uno,csv1@test.com,\"lead, frio\",2026-09-01 10:00:00\n2002,test_csv2,CSV Dos,,,\n"
    r = client.post("/importar", files={"archivo": ("contactos.csv", csv_text, "text/csv")}, data={"origen_tipo": "IMPORTACION"})
    assert r.status_code == 200
    with SessionLocal() as db:
        c = db.query(Contact).filter_by(manychat_id="2001").one()
        assert c.origen_tipo == "IMPORTACION" and c.sync_status == "PENDIENTE_DE_SINCRONIZACION" and [t["name"] for t in c.mc_tags] == ["lead", "frio"]


def test_refresco_por_api_con_manychat_simulado(client):
    def handler(request: httpx.Request):
        assert request.headers["Authorization"] == "Bearer clave-test"
        if request.url.path.endswith("/fb/subscriber/getInfo"):
            return httpx.Response(200, json={"status": "success", "data": {"id": "2001", "ig_username": "test_csv1", "status": "active",
                                                                            "last_interaction": "2026-09-12T09:00:00+00:00", "last_input_text": "me interesa saber más",
                                                                            "custom_fields": [], "tags": [{"id": 1, "name": "lead"}]}})
        if request.url.path.endswith("/fb/page/getTags"):
            return httpx.Response(200, json={"status": "success", "data": [{"id": 1, "name": "lead"}, {"id": 2, "name": "Lead"}, {"id": 3, "name": "viejo"}]})
        if request.url.path.endswith("/fb/page/getCustomFields"):
            return httpx.Response(200, json={"status": "success", "data": [{"id": 9, "name": "CRM_RESPUESTA", "type": "text"}]})
        if request.url.path.endswith("/fb/page/getFlows"):
            return httpx.Response(200, json={"status": "success", "data": [{"ns": "content2026", "name": "FRONTERA"}]})
        return httpx.Response(404, json={"status": "error", "message": "no"})
    mc = ManyChatClient(api_key="clave-test", transport=httpx.MockTransport(handler))
    with SessionLocal() as db:
        n = sync.refrescar_pendientes(db, mc)
        assert n >= 1
        cat = sync.sincronizar_catalogos(db, mc)
        db.commit()
        assert cat["tags"] == 3
        c = db.query(Contact).filter_by(manychat_id="2001").one()
        assert c.sync_status == "OK" and c.intent_label == "INTERES"
    salud = client.get("/salud").text
    assert "DUPLICADA" in salud  # lead / Lead
    assert "SIN USO" in salud or "SIN_USO" in salud  # viejo


def test_paginas_renderizan(client):
    for path in ["/", "/contactos", "/contactos?etapa=VENTA&pendientes=1", "/alertas", "/alertas?todas=1", "/contenido", "/salud", "/propuestas", "/configuracion", "/exportar.csv", "/api/resumen"]:
        r = client.get(path)
        assert r.status_code == 200, path
    with SessionLocal() as db:
        cid = db.query(Contact).first().id
    assert client.get(f"/contactos/{cid}").status_code == 200
