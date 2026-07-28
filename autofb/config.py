"""Validated, environment-selectable configuration for legacy publishing workers."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the application configuration is missing or malformed."""


@dataclass(frozen=True)
class ExcelConfig:
    path: str
    caption_file: str


@dataclass(frozen=True)
class PagesConfig:
    access_tokens: tuple[str, ...]
    page_ids: tuple[str, ...]
    page_names: tuple[str, ...]
    act_id: str

    def page_tokens(self) -> tuple[tuple[str, str], ...]:
        return tuple(zip(self.page_ids, self.access_tokens, strict=True))


@dataclass(frozen=True)
class AppConfig:
    excel: ExcelConfig
    pages: PagesConfig


def config_path() -> Path:
    """Return config path, overridable for local development and tests."""
    return Path(os.environ.get("AUTOFB_CONFIG_PATH", "config.json"))


def _as_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{field} must be a non-empty string")
    return value.strip()


def _as_string_list(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"{field} must be a list")
    return tuple(_as_nonempty_string(item, f"{field}[{index}]") for index, item in enumerate(value))


def load_config(path: Path | None = None) -> AppConfig:
    """Load and validate the subset of configuration needed by publishing workers."""
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Configuration file is not valid JSON: {path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Configuration root must be an object")
    excel = raw.get("excel")
    pages = raw.get("pages")
    if not isinstance(excel, dict) or not isinstance(pages, dict):
        raise ConfigError("Configuration must contain excel and pages objects")

    page_ids = _as_string_list(pages.get("page_id"), "pages.page_id")
    access_tokens = _as_string_list(pages.get("access_token"), "pages.access_token")
    page_names_value = pages.get("page_name", [])
    page_names = _as_string_list(page_names_value, "pages.page_name") if page_names_value else ()
    if len(page_ids) != len(access_tokens):
        raise ConfigError("pages.page_id and pages.access_token must have the same length")
    if page_names and len(page_names) != len(page_ids):
        raise ConfigError("pages.page_name must be empty or have the same length as pages.page_id")

    return AppConfig(
        excel=ExcelConfig(
            path=_as_nonempty_string(excel.get("path"), "excel.path"),
            caption_file=_as_nonempty_string(excel.get("caption_file"), "excel.caption_file"),
        ),
        pages=PagesConfig(
            access_tokens=access_tokens,
            page_ids=page_ids,
            page_names=page_names,
            act_id=str(pages.get("act_id", "")).strip(),
        ),
    )
