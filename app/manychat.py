"""Cliente de la API pública de ManyChat + normalizador de payloads.

Realidad técnica (verificada en la documentación y comunidad de ManyChat):
- La API NO permite listar todos los contactos. Solo consulta uno por uno
  (getInfo por subscriber_id, findByName, findBySystemField por email/teléfono).
- Sí permite leer catálogos (tags, custom fields, flows) y escribir en un contacto
  (addTag, removeTag, setCustomField, sendFlow).
- La forma automática de recibir contactos es que ManyChat los EMPUJE con un
  "External Request" (Dev Tools) dentro de las automatizaciones → nuestro webhook.

Por eso la app funciona así:  ManyChat empuja (webhook)  +  la app refresca (API)  +  la app escribe segmentación (API).
"""
from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any

import httpx

from .config import settings


class ManyChatError(RuntimeError):
    pass


class ManyChatClient:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, transport=None):
        self.api_key = api_key if api_key is not None else settings.manychat_api_key
        self.base_url = (base_url or settings.manychat_base_url).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=15, transport=transport,
                                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
        self._last_call = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _throttle(self, per_sec: float = 8.0):
        gap = 1.0 / per_sec
        wait = self._last_call + gap - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, path: str, **params) -> Any:
        self._throttle()
        try:
            r = self._client.get(path, params=params)
        except httpx.HTTPError as e:
            raise ManyChatError(f"No se pudo conectar con ManyChat ({e.__class__.__name__}). Revisa la conexión a internet.") from e
        return self._unwrap(r)

    def _post(self, path: str, body: dict) -> Any:
        self._throttle()
        try:
            r = self._client.post(path, json=body)
        except httpx.HTTPError as e:
            raise ManyChatError(f"No se pudo conectar con ManyChat ({e.__class__.__name__}). Revisa la conexión a internet.") from e
        return self._unwrap(r)

    @staticmethod
    def _unwrap(r: httpx.Response) -> Any:
        if r.status_code == 429:
            raise ManyChatError("ManyChat: límite de peticiones alcanzado (429). Reintentar más tarde.")
        try:
            data = r.json()
        except ValueError:
            raise ManyChatError(f"ManyChat respondió {r.status_code} sin JSON: {r.text[:200]}")
        if r.status_code >= 400 or data.get("status") == "error":
            raise ManyChatError(f"ManyChat error {r.status_code}: {data.get('message') or data.get('details') or data}")
        return data.get("data", data)

    # ── Catálogos de la cuenta ──
    def get_page_info(self):        return self._get("/fb/page/getInfo")
    def get_tags(self):             return self._get("/fb/page/getTags")
    def get_custom_fields(self):    return self._get("/fb/page/getCustomFields")
    def get_flows(self):            return self._get("/fb/page/getFlows")
    def get_growth_tools(self):     return self._get("/fb/page/getGrowthTools")

    def create_tag(self, name: str):
        return self._post("/fb/page/createTag", {"name": name})

    def create_custom_field(self, caption: str, type_: str = "text", description: str = ""):
        return self._post("/fb/page/createCustomField", {"caption": caption, "type": type_, "description": description})

    # ── Contactos (uno a uno) ──
    def get_subscriber(self, subscriber_id: str):
        return self._get("/fb/subscriber/getInfo", subscriber_id=subscriber_id)

    def find_by_name(self, name: str):
        return self._get("/fb/subscriber/findByName", name=name)

    def find_by_system_field(self, email: str | None = None, phone: str | None = None):
        params = {k: v for k, v in {"email": email, "phone": phone}.items() if v}
        return self._get("/fb/subscriber/findBySystemField", **params)

    def add_tag(self, subscriber_id: str, tag_name: str):
        return self._post("/fb/subscriber/addTagByName", {"subscriber_id": subscriber_id, "tag_name": tag_name})

    def remove_tag(self, subscriber_id: str, tag_name: str):
        return self._post("/fb/subscriber/removeTagByName", {"subscriber_id": subscriber_id, "tag_name": tag_name})

    def set_custom_field(self, subscriber_id: str, field_name: str, value):
        return self._post("/fb/subscriber/setCustomFieldByName", {"subscriber_id": subscriber_id, "field_name": field_name, "field_value": value})

    def send_flow(self, subscriber_id: str, flow_ns: str):
        return self._post("/fb/sending/sendFlow", {"subscriber_id": subscriber_id, "flow_ns": flow_ns})


# ── Normalización de payloads ──────────────────────────────────────────

def _parse_dt(v) -> datetime | None:
    if not v or v in ("null", "None"):
        return None
    if isinstance(v, (int, float)):
        return datetime.utcfromtimestamp(v)
    s = str(v).strip()

    def _utc(d: datetime) -> datetime:
        if d.tzinfo is not None:
            d = (d - d.utcoffset()).replace(tzinfo=None)
        return d

    try:
        return _utc(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return _utc(datetime.strptime(s.replace("Z", "+0000"), fmt))
        except ValueError:
            continue
    return None


_PHONE_CC = {"57": "CO", "52": "MX", "58": "VE", "56": "CL", "54": "AR", "51": "PE", "593": "EC", "34": "ES", "1": "US", "507": "PA",
             "506": "CR", "502": "GT", "503": "SV", "504": "HN", "505": "NI", "591": "BO", "595": "PY", "598": "UY", "809": "DO", "27": "ZA"}


def derivar_pais(phone: str | None, locale: str | None, custom: dict) -> str | None:
    if custom.get("CRM_PAIS"):
        return str(custom["CRM_PAIS"]).strip().upper()[:2]
    if phone:
        digits = re.sub(r"\D", "", phone)
        for cc in sorted(_PHONE_CC, key=len, reverse=True):
            if digits.startswith(cc):
                return _PHONE_CC[cc]
    if locale and "_" in locale:
        cc = locale.split("_")[1].upper()
        if cc not in ("LA", "ES", "US", "419"):
            return cc
    return None


def normalizar_payload(body: dict) -> dict:
    """Convierte cualquier forma de payload de ManyChat en un dict plano y uniforme.

    Acepta:
      A) "Full Contact Data" del External Request (= forma de getInfo): tiene "id" y listas custom_fields/tags.
      B) Cuerpo personalizado con variables: subscriber_id, ig_username, last_input_text, origen_tipo, ...
      C) La respuesta de getInfo de la API (mismo que A).
    """
    d = dict(body)
    if "data" in d and isinstance(d["data"], dict):
        d = {**d, **d["data"]}

    custom: dict[str, Any] = {}
    cf = d.get("custom_fields")
    if isinstance(cf, list):
        for f in cf:
            if isinstance(f, dict) and f.get("name") is not None:
                custom[str(f["name"])] = f.get("value")
    elif isinstance(cf, dict):
        custom.update(cf)
    # Variables sueltas con prefijo CRM_ también cuentan como custom fields
    for k, v in d.items():
        if isinstance(k, str) and k.upper().startswith("CRM_"):
            custom[k.upper()] = v

    tags = d.get("tags") or []
    if isinstance(tags, str):
        tags = [{"name": t.strip()} for t in tags.split(",") if t.strip()]
    tags = [t if isinstance(t, dict) else {"name": str(t)} for t in tags]

    def pick(*keys):
        for k in keys:
            v = d.get(k)
            if v not in (None, "", "null"):
                return v
        return None

    name = pick("name", "full_name")
    if not name:
        fn, ln = d.get("first_name") or "", d.get("last_name") or ""
        name = (f"{fn} {ln}").strip() or None

    ig_username = pick("ig_username", "instagram_username", "username")
    if ig_username:
        ig_username = str(ig_username).lstrip("@").strip().lower()

    phone = pick("phone", "whatsapp_phone", "optin_phone_number")
    locale = pick("locale")

    return {
        "manychat_id": str(pick("subscriber_id", "id", "contact_id", "user_id") or "") or None,
        "ig_username": ig_username,
        "ig_id": str(pick("ig_id") or "") or None,
        "name": name,
        "email": (pick("email") or None),
        "phone": phone,
        "locale": locale,
        "timezone": pick("timezone"),
        "profile_pic": pick("profile_pic"),
        "country": derivar_pais(phone, locale, custom),
        "mc_status": pick("status", "subscription_status"),
        "mc_subscribed_at": _parse_dt(pick("subscribed", "subscribed_at")),
        "mc_last_interaction": _parse_dt(pick("last_interaction", "last_interaction_at")),
        "mc_last_seen": _parse_dt(pick("last_seen")),
        "mc_last_input_text": pick("last_input_text", "last_message", "mensaje"),
        "mc_last_growth_tool": pick("last_growth_tool", "trigger", "growth_tool"),
        "mc_follows_account": _to_bool(pick("ig_follows_account", "follows_account", "is_follower")),
        "mc_optin_email": _to_bool(pick("optin_email")),
        "mc_optin_phone": _to_bool(pick("optin_phone")),
        "mc_tags": tags,
        "mc_custom_fields": custom,
        # Origen: primero lo explícito del body, luego los campos CRM_*, luego el growth tool
        "origen_tipo": pick("origen_tipo") or custom.get("CRM_ORIGEN_TIPO"),
        "origen_contenido": pick("origen_contenido", "contenido", "reel") or custom.get("CRM_ORIGEN_CONTENIDO"),
        "origen_keyword": pick("keyword", "palabra_clave") or custom.get("CRM_KEYWORD"),
        "origen_cta": pick("cta") or custom.get("CRM_CTA"),
        "origen_automation": pick("automatizacion", "flow", "flow_name") or custom.get("CRM_AUTOMATIZACION"),
        "origen_campaign": pick("campana", "campaign") or custom.get("CRM_CAMPANA"),
        "respuesta": pick("respuesta") or custom.get("CRM_RESPUESTA"),
        "evento": str(pick("evento", "event") or "ENTRADA").upper(),
        "raw": body,
    }


def _to_bool(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "si", "sí")
