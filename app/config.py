from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = BASE_DIR / ".env") -> None:
    """Small .env loader so production has no extra configuration dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


load_dotenv()


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    data_dir: Path = Path(os.getenv("CHAT_DATA_DIR", BASE_DIR / "data"))
    secret_key: str = os.getenv("CHAT_SECRET_KEY", "")
    host: str = os.getenv("CHAT_HOST", "0.0.0.0")
    port: int = int(os.getenv("CHAT_PORT", "8000"))
    cookie_secure: bool = os.getenv("CHAT_COOKIE_SECURE", "false").lower() == "true"
    max_image_mb: int = int(os.getenv("CHAT_MAX_IMAGE_MB", "8"))
    history_page_size: int = int(os.getenv("CHAT_HISTORY_PAGE_SIZE", "50"))

    @property
    def database_path(self) -> Path:
        return self.data_dir / "chat.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"


settings = Settings()


def ensure_directories() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)


def validate_production_settings() -> None:
    if len(settings.secret_key) < 32 or settings.secret_key.startswith("请替换"):
        raise RuntimeError("CHAT_SECRET_KEY 未设置或少于 32 个字符，请检查项目根目录的 .env")

