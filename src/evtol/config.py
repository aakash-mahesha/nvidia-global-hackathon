"""Typed settings loaded from .env via pydantic-settings.

Usage:
    from evtol.config import load_settings
    settings = load_settings()              # raises MissingConfigError w/ list
    settings = load_settings(strict=False)  # warns, returns partial settings

Layering (lowest → highest precedence): committed `.env.shared` (team
resource IDs, no secrets) < personal `.env` (secrets + overrides, gitignored)
< real environment variables. All names mirror .env.example exactly.
Anything not yet decided at the day-1 contract freeze is Optional with a
sane default where one exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_TOKEN_FACTORY_BASE_URL = "https://api.tokenfactory.us-central1.nebius.com/v1/"
DEFAULT_PERMIT_MODEL_ID = "nvidia/nemotron-3-super-120b-a12b"  # placeholder
DEFAULT_NEBIUS_S3_ENDPOINT = "https://storage.eu-north1.nebius.cloud"

# Vars that must be present before real cloud/robot work can run —
# i.e. the ones with no sane default. (Vars with defaults like
# TOKEN_FACTORY_BASE_URL / JOB_KILL_TIMEOUT never report missing.)
REQUIRED_VARS: tuple[str, ...] = (
    "NEBIUS_PROJECT_ID",
    "EVDATA_BUCKET",
    "TOKEN_FACTORY_API_KEY",
    "NGC_API_KEY",
    "HF_TOKEN",
    "EVENT_BUS_URL",
)


class MissingConfigError(RuntimeError):
    """Raised when required env vars are absent. Message lists every gap."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        listing = "\n".join(f"  - {v}" for v in missing)
        super().__init__(
            f"Missing required configuration ({len(missing)} var(s)):\n{listing}\n"
            "Fill them into .env — see .env.example and docs/SETUP.md, then run "
            "scripts/check_credentials.py."
        )


class Settings(BaseSettings):
    """All project configuration, typed. Optional fields may be None until
    the corresponding account/credential is set up (docs/SETUP.md)."""

    # Layered config: committed team values first, personal secrets/overrides
    # second, real env vars always win. .env.shared holds non-secret team
    # resource IDs (one Nebius tenant — billing cannot merge across tenants);
    # .env holds each developer's personal keys (gitignored).
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env.shared", REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    # --- Nebius Cloud (preemptible VMs only; npa owns cluster lifecycle) ---
    nebius_project_id: Optional[str] = Field(default=None, alias="NEBIUS_PROJECT_ID")
    nebius_iam_token: Optional[str] = Field(default=None, alias="NEBIUS_IAM_TOKEN")
    evdata_bucket: Optional[str] = Field(default=None, alias="EVDATA_BUCKET")
    nebius_s3_endpoint: str = Field(default=DEFAULT_NEBIUS_S3_ENDPOINT, alias="NEBIUS_S3_ENDPOINT")

    # --- Token Factory (key is SEPARATE from the Nebius IAM token) ---
    token_factory_api_key: Optional[str] = Field(default=None, alias="TOKEN_FACTORY_API_KEY")
    token_factory_base_url: str = Field(
        default=DEFAULT_TOKEN_FACTORY_BASE_URL, alias="TOKEN_FACTORY_BASE_URL"
    )
    permit_model_id: str = Field(default=DEFAULT_PERMIT_MODEL_ID, alias="PERMIT_MODEL_ID")

    # --- NGC / Hugging Face ---
    ngc_api_key: Optional[str] = Field(default=None, alias="NGC_API_KEY")
    hf_token: Optional[str] = Field(default=None, alias="HF_TOKEN")

    # --- Remote rig access ---
    tailscale_authkey: Optional[str] = Field(default=None, alias="TAILSCALE_AUTHKEY")

    # --- Event bus (technology TBD at day-1 freeze; topics in topics.py) ---
    event_bus_url: Optional[str] = Field(default=None, alias="EVENT_BUS_URL")

    # --- Data ---
    lerobot_dataset_root: Path = Field(
        default=REPO_ROOT / "data" / "lerobot", alias="LEROBOT_DATASET_ROOT"
    )

    # --- Ops safety: hard kill-timer on every scheduled job ---
    job_kill_timeout: int = Field(default=3600, alias="JOB_KILL_TIMEOUT")

    def missing_required(self) -> list[str]:
        """Env-var names among REQUIRED_VARS that are still unset/empty."""
        missing: list[str] = []
        for var in REQUIRED_VARS:
            field_name = var.lower()
            value = getattr(self, field_name, None)
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(var)
        return missing


def load_settings(env_file: Optional[Path] = None, strict: bool = True) -> Settings:
    """Build Settings from env vars + .env.shared + .env.

    env_file    → extra file layered on top of .env.shared (e.g. a test env).
    strict=True → raise MissingConfigError listing every missing required var.
    strict=False → return a partial Settings; caller can inspect
                   settings.missing_required() (e.g. early-bootstrap code).
    """
    files: tuple[Path, ...] = (
        REPO_ROOT / ".env.shared",
        env_file or REPO_ROOT / ".env",
    )
    settings = Settings(_env_file=files)
    missing = settings.missing_required()
    if strict and missing:
        raise MissingConfigError(missing)
    return settings
