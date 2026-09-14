"""Instagram: línea base (los datos reales de Claudia) + cliente opcional de la Graph API (fase 2)."""
from __future__ import annotations

from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Content, IgSnapshot
from .services import get_or_create_content, log_sync

# ── Línea base: últimos 30 días al 13/09/2026 (datos entregados por Claudia) ──
LINEA_BASE = {
    "period_start": datetime(2026, 8, 13), "period_end": datetime(2026, 9, 13),
    "views": 1_649_894, "viewers": 1_242_011, "non_follower_pct": 99.2, "follower_pct": 0.8,
    "net_followers": 5_155, "followers_total": 7_701, "growth_pct": 202.2,
    "views_by_type": {"REEL": 1_600_000, "HISTORIA": 4_500, "POST": 3_600, "LIVE": 0},
    "interactions_by_type": {"REEL": 89_000, "HISTORIA": 194, "POST": 88, "LIVE": 0},
    "profile_visits": 2_274, "link_clicks": 19,
    "gender": {"Mujeres": 63.8, "Hombres": 36.2},
    "ages": {"13-17": 0.3, "18-24": 3.1, "25-34": 23.0, "35-44": 36.7, "45-54": 25.1, "55-64": 9.5, "65+": 2.4},
    "countries": {"Colombia": 38.9, "México": 12.6, "Venezuela": 8.4, "Chile": 8.4, "Argentina": 6.7},
    "source": "manual",
}

# Reels que Instagram muestra como origen de nuevos seguidores (datos de Claudia)
REELS_BASE = [
    {"ref": "reel-estrategia-atraer-clientes", "title": "Estrategia efectiva para atraer más clientes", "followers_gained": 5000},
    {"ref": "reel-es-muy-caro", "title": "Qué hacer cuando te dicen 'es muy caro'", "followers_gained": 242},
    {"ref": "reel-como-funcionan-los-negocios", "title": "Cómo funcionan los negocios", "followers_gained": 21},
]


def sembrar_linea_base(db: Session) -> None:
    if not db.scalar(select(IgSnapshot).where(IgSnapshot.period_end == LINEA_BASE["period_end"])):
        db.add(IgSnapshot(**LINEA_BASE))
    for r in REELS_BASE:
        c = db.scalar(select(Content).where(Content.ref == r["ref"]))
        if not c:
            db.add(Content(ref=r["ref"], title=r["title"], type="REEL", followers_gained=r["followers_gained"],
                           data_source="manual", notes="Línea base: 'contenido destacado por nuevos seguidores' de Instagram"))
    db.commit()


# ── Graph API (fase 2): solo funciona con token; sin token no inventa nada ──

class InstagramClient:
    def __init__(self, token: str | None = None, user_id: str | None = None):
        self.token = token if token is not None else settings.ig_access_token
        self.user_id = user_id or settings.ig_user_id
        self.base = "https://graph.facebook.com/v21.0"

    @property
    def configured(self) -> bool:
        return bool(self.token and self.user_id)

    def _get(self, path: str, **params):
        params["access_token"] = self.token
        r = httpx.get(f"{self.base}/{path}", params=params, timeout=20)
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "Error de Instagram"))
        return data

    def media(self, limit: int = 50):
        return self._get(f"{self.user_id}/media", fields="id,caption,media_type,media_product_type,permalink,timestamp", limit=limit).get("data", [])

    def media_insights(self, media_id: str) -> dict:
        # Métricas de Reels en la API actual; si alguna no aplica, Instagram la omite.
        data = self._get(f"{media_id}/insights", metric="views,reach,likes,comments,shares,saved,total_interactions").get("data", [])
        return {m["name"]: (m.get("values") or [{}])[0].get("value") for m in data}

    def account_insights(self, since: datetime, until: datetime) -> dict:
        data = self._get(f"{self.user_id}/insights", metric="reach,profile_views,website_clicks,accounts_engaged,follower_count",
                         period="day", since=int(since.timestamp()), until=int(until.timestamp())).get("data", [])
        return {m["name"]: sum(v.get("value") or 0 for v in m.get("values", [])) for m in data}


def sincronizar_instagram(db: Session, client: InstagramClient | None = None) -> dict:
    client = client or InstagramClient()
    if not client.configured:
        log_sync(db, "instagram", False, 0, "IG_ACCESS_TOKEN / IG_USER_ID no configurados (fase 2)")
        return {"error": "Instagram no conectado. Las métricas se cargan a mano hasta la fase 2."}
    n = 0
    for m in client.media():
        if m.get("media_product_type") not in ("REELS", "FEED"):
            continue
        titulo = (m.get("caption") or "").split("\n")[0][:120] or m["id"]
        c = db.scalar(select(Content).where(Content.ig_media_id == m["id"])) or get_or_create_content(db, titulo, "REEL" if m.get("media_product_type") == "REELS" else "POST")
        c.ig_media_id, c.url = m["id"], m.get("permalink")
        c.type = "REEL" if m.get("media_product_type") == "REELS" else "POST"
        try:
            c.published_at = datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")).replace(tzinfo=None)
        except Exception:
            pass
        ins = client.media_insights(m["id"])
        c.views, c.reach, c.likes, c.comments = ins.get("views"), ins.get("reach"), ins.get("likes"), ins.get("comments")
        c.shares, c.saves, c.interactions = ins.get("shares"), ins.get("saved"), ins.get("total_interactions")
        c.data_source = "graph_api"
        n += 1
    log_sync(db, "instagram", True, n, f"{n} contenidos actualizados desde la Graph API")
    return {"contenidos": n}
