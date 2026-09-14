"""Modelo de datos: una sola fuente de verdad, un registro por persona, historial de todo."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.utcnow()


class Contact(Base):
    """Una persona = un registro. Identidad + origen + intención + etapa."""
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(primary_key=True)

    # ── IDENTIDAD ──
    manychat_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    ig_username: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    ig_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    email: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    country: Mapped[Optional[str]] = mapped_column(String(2))          # ISO-2, derivado de timezone/teléfono si ManyChat no lo da
    timezone: Mapped[Optional[str]] = mapped_column(String(64))
    locale: Mapped[Optional[str]] = mapped_column(String(16))
    profile_pic: Mapped[Optional[str]] = mapped_column(String(500))

    # ── DATOS DE MANYCHAT (espejo; se refrescan por sync) ──
    mc_status: Mapped[Optional[str]] = mapped_column(String(32))         # active / unsubscribed / ...
    mc_subscribed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    mc_last_interaction: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    mc_last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)
    mc_last_input_text: Mapped[Optional[str]] = mapped_column(Text)
    mc_last_growth_tool: Mapped[Optional[str]] = mapped_column(String(200))
    mc_follows_account: Mapped[Optional[bool]] = mapped_column(Boolean)
    mc_tags: Mapped[list] = mapped_column(JSON, default=list)          # [{id,name}]
    mc_custom_fields: Mapped[dict] = mapped_column(JSON, default=dict) # {nombre: valor}
    mc_optin_email: Mapped[Optional[bool]] = mapped_column(Boolean)
    mc_optin_phone: Mapped[Optional[bool]] = mapped_column(Boolean)

    # ── ORIGEN ──
    origen_tipo: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    origen_content_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contents.id"), index=True)
    origen_keyword: Mapped[Optional[str]] = mapped_column(String(120))
    origen_cta: Mapped[Optional[str]] = mapped_column(String(200))
    origen_automation: Mapped[Optional[str]] = mapped_column(String(200))
    origen_campaign: Mapped[Optional[str]] = mapped_column(String(120))
    origen_fecha: Mapped[Optional[datetime]] = mapped_column(DateTime)

    # ── INTENCIÓN / SEGMENTACIÓN (4 dimensiones) ──
    interes: Mapped[Optional[str]] = mapped_column(String(32), index=True)
    intencion: Mapped[str] = mapped_column(String(16), default="FRIA", index=True)
    etapa: Mapped[str] = mapped_column(String(32), default="NUEVO", index=True)
    intent_label: Mapped[Optional[str]] = mapped_column(String(32))
    temperatura: Mapped[str] = mapped_column(String(32), default="SIN_INFORMACION", index=True)
    score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    respuesta_pregunta: Mapped[Optional[str]] = mapped_column(Text)
    objecion: Mapped[Optional[str]] = mapped_column(String(300))
    problema: Mapped[Optional[str]] = mapped_column(String(300))

    # ── SEGUIMIENTO ──
    needs_reply: Mapped[bool] = mapped_column(Boolean, default=False, index=True)   # la persona escribió y espera respuesta
    last_human_touch: Mapped[Optional[datetime]] = mapped_column(DateTime)             # última vez que Claudia respondió/actuó
    last_inbound_at: Mapped[Optional[datetime]] = mapped_column(DateTime)              # último mensaje de la persona
    next_followup_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    interacciones: Mapped[int] = mapped_column(Integer, default=0)

    # ── CONTROL ──
    source_of_record: Mapped[str] = mapped_column(String(32), default="webhook")  # webhook/api/csv/manual
    sync_status: Mapped[str] = mapped_column(String(40), default="PENDIENTE_DE_SINCRONIZACION")
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    merged_into_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"))
    raw_last_payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    origen_content = relationship("Content", foreign_keys=[origen_content_id])
    events = relationship("ContactEvent", back_populates="contact", order_by="ContactEvent.created_at.desc()")
    sales = relationship("Sale", back_populates="contact")

    @property
    def display(self) -> str:
        return ("@" + self.ig_username) if self.ig_username else (self.name or self.email or f"#{self.id}")


class ContactEvent(Base):
    """Historial: cada cambio, mensaje, click, venta, alerta. Nunca se borra."""
    __tablename__ = "contact_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)   # created/message_in/message_out/stage_change/field_change/click/sale/note/sync/alert
    field: Mapped[Optional[str]] = mapped_column(String(60))
    old_value: Mapped[Optional[str]] = mapped_column(Text)
    new_value: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="sistema")
    payload: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)

    contact = relationship("Contact", back_populates="events")


class Content(Base):
    """Un Reel / post / historia. Se relaciona con los contactos que originó."""
    __tablename__ = "contents"

    id: Mapped[int] = mapped_column(primary_key=True)
    ref: Mapped[str] = mapped_column(String(200), unique=True, index=True)  # nombre corto único (ej. "reel-es-muy-caro")
    ig_media_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    type: Mapped[str] = mapped_column(String(16), default="REEL")           # REEL/POST/HISTORIA/LIVE
    title: Mapped[Optional[str]] = mapped_column(String(300))
    url: Mapped[Optional[str]] = mapped_column(String(500))
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    keyword: Mapped[Optional[str]] = mapped_column(String(120))               # keyword de ManyChat asociada
    # Métricas de Instagram (a mano o por Graph API)
    views: Mapped[Optional[int]] = mapped_column(Integer)
    reach: Mapped[Optional[int]] = mapped_column(Integer)
    interactions: Mapped[Optional[int]] = mapped_column(Integer)
    likes: Mapped[Optional[int]] = mapped_column(Integer)
    comments: Mapped[Optional[int]] = mapped_column(Integer)
    shares: Mapped[Optional[int]] = mapped_column(Integer)
    saves: Mapped[Optional[int]] = mapped_column(Integer)
    followers_gained: Mapped[Optional[int]] = mapped_column(Integer)
    data_source: Mapped[str] = mapped_column(String(20), default="manual")  # manual / graph_api
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class Sale(Base):
    __tablename__ = "sales"
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    product: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = mapped_column(Float, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    sold_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    contact = relationship("Contact", back_populates="sales")


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    level: Mapped[str] = mapped_column(String(16), default="alta")     # alta / media / baja
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"), index=True)
    content_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contents.id"))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[Optional[str]] = mapped_column(Text)
    recommendation: Mapped[Optional[str]] = mapped_column(String(300))
    dedupe_key: Mapped[str] = mapped_column(String(200), index=True)
    status: Mapped[str] = mapped_column(String(16), default="abierta", index=True)  # abierta / resuelta / descartada
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    contact = relationship("Contact")
    content = relationship("Content")


class McTag(Base):
    """Catálogo de etiquetas de ManyChat + su clasificación (auditoría)."""
    __tablename__ = "mc_tags"
    id: Mapped[int] = mapped_column(primary_key=True)
    mc_tag_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    contact_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    classification: Mapped[str] = mapped_column(String(20), default="ACTIVA")
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class McCustomField(Base):
    __tablename__ = "mc_custom_fields"
    id: Mapped[int] = mapped_column(primary_key=True)
    mc_field_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    type: Mapped[Optional[str]] = mapped_column(String(32))
    description: Mapped[Optional[str]] = mapped_column(String(300))
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class McFlow(Base):
    """Automatizaciones. Las estadísticas se cuentan con los eventos que llegan por webhook."""
    __tablename__ = "mc_flows"
    id: Mapped[int] = mapped_column(primary_key=True)
    ns: Mapped[Optional[str]] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    folder: Mapped[Optional[str]] = mapped_column(String(200))
    synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class Proposal(Base):
    """DETECTAR → PROPONER → MOSTRAR → APROBAR → EJECUTAR. Nada destructivo sin aprobación."""
    __tablename__ = "proposals"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)  # FUSIONAR_DUPLICADOS / RETIRAR_ETIQUETA / RECLASIFICAR / ...
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[Optional[str]] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="propuesta", index=True)  # propuesta/aprobada/ejecutada/rechazada
    result: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


class IgSnapshot(Base):
    """Foto de Instagram por período (la línea base de 30 días se siembra al arrancar)."""
    __tablename__ = "ig_snapshots"
    __table_args__ = (UniqueConstraint("period_start", "period_end", name="uq_ig_period"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    period_start: Mapped[datetime] = mapped_column(DateTime)
    period_end: Mapped[datetime] = mapped_column(DateTime, index=True)
    views: Mapped[Optional[int]] = mapped_column(Integer)
    viewers: Mapped[Optional[int]] = mapped_column(Integer)
    non_follower_pct: Mapped[Optional[float]] = mapped_column(Float)
    follower_pct: Mapped[Optional[float]] = mapped_column(Float)
    net_followers: Mapped[Optional[int]] = mapped_column(Integer)
    followers_total: Mapped[Optional[int]] = mapped_column(Integer)
    growth_pct: Mapped[Optional[float]] = mapped_column(Float)
    views_by_type: Mapped[dict] = mapped_column(JSON, default=dict)          # {REEL:.., HISTORIA:.., POST:.., LIVE:..}
    interactions_by_type: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_visits: Mapped[Optional[int]] = mapped_column(Integer)
    link_clicks: Mapped[Optional[int]] = mapped_column(Integer)
    gender: Mapped[dict] = mapped_column(JSON, default=dict)
    ages: Mapped[dict] = mapped_column(JSON, default=dict)
    countries: Mapped[dict] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class SyncLog(Base):
    __tablename__ = "sync_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)   # webhook / api_refresh / csv_import / catalogs / instagram
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    items: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
