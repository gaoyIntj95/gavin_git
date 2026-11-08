from dataclasses import dataclass
from pathlib import Path
import os
import shutil
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_version: str
    database_url: str
    project_root: Path
    storage_root: Path
    data_dir: Path
    vector_dir: Path
    log_dir: Path
    upload_dir: Path
    report_dir: Path
    template_dir: Path


def _load_env_file(path: Path) -> None:
    if not path.exists() or not path.is_file():
        return
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and (
                (value.startswith('"') and value.endswith('"'))
                or (value.startswith("'") and value.endswith("'"))
            ):
                value = value[1:-1]
            os.environ[key] = value
    except Exception:
        # Keep startup resilient if env parsing fails.
        pass


def _load_local_env_files() -> None:
    current_file = Path(__file__).resolve()
    project_root = current_file.parents[3]
    backend_root = current_file.parents[2]
    for candidate in (backend_root / ".env", project_root / ".env"):
        _load_env_file(candidate)


def _build_database_url() -> str:
    explicit_url = os.getenv("DATABASE_URL", "").strip()
    if explicit_url:
        if not explicit_url.startswith("mysql"):
            raise RuntimeError(
                "Only MySQL is supported. DATABASE_URL must start with 'mysql'."
            )
        return explicit_url

    backend = os.getenv("DB_BACKEND", "mysql").strip().lower()
    if backend != "mysql":
        raise RuntimeError("Only MySQL is supported. Set DB_BACKEND=mysql.")

    host = os.getenv("MYSQL_HOST", "127.0.0.1").strip()
    port = os.getenv("MYSQL_PORT", "3306").strip()
    database = os.getenv("MYSQL_DATABASE", "carbon_ai").strip()
    user = quote_plus(os.getenv("MYSQL_USER", "root").strip())
    password = quote_plus(os.getenv("MYSQL_PASSWORD", "").strip())
    charset = os.getenv("MYSQL_CHARSET", "utf8mb4").strip()
    auth = f"{user}:{password}" if password else user
    return f"mysql+pymysql://{auth}@{host}:{port}/{database}?charset={charset}"


def _build_settings() -> Settings:
    _load_local_env_files()

    current_file = Path(__file__).resolve()
    project_root = current_file.parents[3]
    storage_root = Path(os.getenv("CARBONAI_STORAGE_ROOT", str(project_root / "runtime"))).resolve()
    data_dir = (storage_root / "data").resolve()
    log_dir = (storage_root / "logs").resolve()
    vector_dir = (data_dir / "vector_store").resolve()
    upload_dir = data_dir / "uploads"
    report_dir = data_dir / "reports"
    template_dir = data_dir / "templates"

    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    vector_dir.mkdir(parents=True, exist_ok=True)
    upload_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    template_dir.mkdir(parents=True, exist_ok=True)

    database_url = _build_database_url()
    legacy_data_dir = (project_root / "data").resolve()
    if legacy_data_dir.exists() and legacy_data_dir != data_dir:
        for child in legacy_data_dir.iterdir():
            target = data_dir / child.name
            if target.exists():
                continue
            try:
                if child.is_dir():
                    shutil.copytree(child, target)
                else:
                    shutil.copy2(child, target)
            except Exception:
                # Keep startup resilient if a file is locked.
                continue

    return Settings(
        app_name=os.getenv("APP_NAME", "Carbon AI Project"),
        app_version=os.getenv("APP_VERSION", "0.1.0"),
        database_url=database_url,
        project_root=project_root,
        storage_root=storage_root,
        data_dir=data_dir,
        vector_dir=vector_dir,
        log_dir=log_dir,
        upload_dir=upload_dir,
        report_dir=report_dir,
        template_dir=template_dir,
    )


settings = _build_settings()
