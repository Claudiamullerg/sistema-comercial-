"""Configuración central. Todo se lee de variables de entorno (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

# Valor canónico para cualquier dato de ManyChat/Instagram que todavía no llegó por sincronización.
PENDIENTE = "PENDIENTE_DE_SINCRONIZACION"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    app_name: str = "Sistema Comercial · Claudia Müller"
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'sistema.db'}"

    # ManyChat (Settings → API en ManyChat Pro)
    manychat_api_key: str = ""
    manychat_base_url: str = "https://api.manychat.com"
    # Secreto que ManyChat manda en la URL del External Request: /webhooks/manychat?secret=...
    webhook_secret: str = "cambia-este-secreto"
    # Si está activo, la app escribe de vuelta en ManyChat los 4 campos CRM_* (segmentación canónica)
    manychat_writeback: bool = False
    # Cada cuántos minutos refrescar contactos vía API (0 = desactivado)
    manychat_refresh_minutes: int = 60

    # Hotmart: token "hottok" que Hotmart manda en cada webhook (Herramientas → Webhook). Vacío = no se valida.
    hotmart_hottok: str = ""

    # Instagram Graph API (opcional, fase 2). Sin token, las métricas se cargan a mano.
    ig_access_token: str = ""
    ig_user_id: str = ""

    # Reglas de negocio
    dias_sin_seguimiento: int = 3          # lead sin toque humano en N días → alerta
    dias_conversacion_abandonada: int = 7  # conversación abierta sin actividad → abandonada
    umbral_caliente: int = 50              # score >= → CALIENTE
    umbral_tibio: int = 20                 # score >= → TIBIA
    dias_inactivo: int = 30                # contacto sin interacción → inactivo

    # Contraseña simple para el panel (vacía = sin login; ponla al desplegar en la nube)
    panel_password: str = ""


settings = Settings()
# Railway/Render entregan "postgresql://…"; SQLAlchemy necesita el driver explícito.
if settings.database_url.startswith(("postgres://", "postgresql://")):
    settings.database_url = "postgresql+psycopg://" + settings.database_url.split("://", 1)[1]
os.makedirs(BASE_DIR / "data", exist_ok=True)
