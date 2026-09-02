# Dashboard e-ink Lyon — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire un backend Python conteneurisé qui agrège les prochains passages TCL et la disponibilité Vélo'v, en fait une image BMP 1 bit 800x480, et la sert à un panneau XIAO 7.5" ePaper via le protocole serveur TRMNL.

**Architecture:** Des boucles asyncio indépendantes, une par fournisseur, alimentent un état en mémoire daté par source. Un service transforme cet état en ViewModel purement textuel, que Pillow dessine. Le panneau vient chercher l'image par HTTP et se rendort. Aucune base de données, aucun volume de persistance.

**Tech Stack:** Python 3.12, FastAPI, httpx, Pydantic v2, pydantic-settings, tomllib, Pillow, structlog, pytest, pytest-asyncio, respx, ruff, mypy, Docker.

**Spec:** `docs/superpowers/specs/2026-09-02-eink-dashboard-lyon-design.md`

## Global Constraints

- Python `>=3.12`. Le code utilise la syntaxe de génériques PEP 695 (`class Foo[T]`) et `tomllib` de la stdlib.
- Dépendances runtime autorisées, et aucune autre : `fastapi`, `uvicorn[standard]`, `httpx`, `pydantic`, `pydantic-settings`, `pillow`, `structlog`.
- Dépendances de développement autorisées : `pytest`, `pytest-asyncio`, `respx`, `ruff`, `mypy`.
- Interdits explicites : PostgreSQL, Redis, Celery, Kafka, Airflow, SQLite, SQLAlchemy, APScheduler, pandas, toute bibliothèque de retry.
- Aucun test de la suite par défaut ne fait d'appel réseau réel. Les tests réseau portent la marque `@pytest.mark.network` et sont exclus par `addopts = "-m 'not network'"`.
- `mypy --strict` passe sur `src/`. `ruff check` et `ruff format --check` passent sur tout le dépôt.
- Aucun secret versionné. `.env` est dans `.gitignore`, `.env.example` ne contient que des noms.
- Le seul volume autorisé dans `compose.yaml` est un montage en lecture seule de `./config`. Ce n'est pas de la persistance.
- Résolution cible du rendu : 800 x 480, mode Pillow `"1"`, sortie BMP.
- Fuseau : `Europe/Paris`, via `zoneinfo`. Aucun `datetime.now()` sans fuseau dans le code métier.
- Toutes les fonctions de formatage d'affichage sont pures et testées sans Pillow.

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `pyproject.toml` | Dépendances, ruff, mypy, pytest |
| `Dockerfile`, `compose.yaml`, `.env.example` | Déploiement |
| `config/dashboard.toml` | Arrêts TCL et stations Vélo'v suivis |
| `src/eink_dashboard/main.py` | Application FastAPI, lifespan, câblage |
| `src/eink_dashboard/core/config.py` | `Settings` (env) et `DashboardConfig` (TOML) |
| `src/eink_dashboard/core/logging.py` | Configuration structlog |
| `src/eink_dashboard/domain/transit.py` | `Departure`, `StopBoard` |
| `src/eink_dashboard/domain/bikes.py` | `BikeStation` |
| `src/eink_dashboard/state.py` | `ProviderResult`, `DashboardState`, `Store` |
| `src/eink_dashboard/providers/base.py` | `Provider` protocol |
| `src/eink_dashboard/providers/velov/schemas.py` | Modèles GBFS v3 bruts |
| `src/eink_dashboard/providers/velov/mapper.py` | GBFS vers `BikeStation` |
| `src/eink_dashboard/providers/velov/client.py` | Appels HTTP GBFS |
| `src/eink_dashboard/providers/tcl/schemas.py` | Modèles datapusher bruts |
| `src/eink_dashboard/providers/tcl/mapper.py` | Datapusher vers `StopBoard` |
| `src/eink_dashboard/providers/tcl/client.py` | Appels HTTP Basic auth |
| `src/eink_dashboard/scheduler.py` | Boucles asyncio par fournisseur |
| `src/eink_dashboard/services/dashboard.py` | Assemblage, cadence, hachage |
| `src/eink_dashboard/render/viewmodel.py` | Vue purement textuelle |
| `src/eink_dashboard/render/layout.py` | Dessin Pillow |
| `src/eink_dashboard/render/images.py` | Cache mémoire des images rendues |
| `src/eink_dashboard/api/deps.py` | Dépendances FastAPI |
| `src/eink_dashboard/api/routes/health.py` | `/health` |
| `src/eink_dashboard/api/routes/dashboard.py` | `/api/v1/dashboard`, `/preview.png` |
| `src/eink_dashboard/api/routes/device.py` | `/api/setup`, `/api/display`, `/api/log`, `/image/{name}.bmp` |

---

## Task 1: Squelette, outillage, `/health` statique, Docker

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`
- Create: `src/eink_dashboard/__init__.py`, `src/eink_dashboard/main.py`
- Create: `src/eink_dashboard/core/__init__.py`, `src/eink_dashboard/core/logging.py`
- Create: `src/eink_dashboard/api/__init__.py`, `src/eink_dashboard/api/routes/__init__.py`, `src/eink_dashboard/api/routes/health.py`
- Create: `Dockerfile`, `compose.yaml`
- Test: `tests/unit/test_health.py`

**Interfaces:**
- Consumes: rien.
- Produces: `eink_dashboard.main:app` (`fastapi.FastAPI`), `eink_dashboard.core.logging.configure_logging(level: str) -> None`.

- [ ] **Step 1: Écrire le test qui échoue**

`tests/unit/test_health.py` :

```python
from fastapi.testclient import TestClient

from eink_dashboard.main import app


def test_health_returns_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

- [ ] **Step 2: Lancer le test et vérifier qu'il échoue**

Run: `pytest tests/unit/test_health.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard'`

- [ ] **Step 3: Créer `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "eink-dashboard"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "httpx>=0.27",
    "pydantic>=2.9",
    "pydantic-settings>=2.6",
    "pillow>=11.0",
    "structlog>=24.4",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "respx>=0.21",
    "ruff>=0.7",
    "mypy>=1.13",
]

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
eink_dashboard = ["render/fonts/*.ttf"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-m 'not network'"
markers = ["network: touche le vrai réseau, exclu par défaut"]
```

- [ ] **Step 4: Créer le package minimal**

`src/eink_dashboard/__init__.py` : fichier vide.

`src/eink_dashboard/core/__init__.py` : fichier vide.

`src/eink_dashboard/core/logging.py` :

```python
import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", level=getattr(logging, level.upper(), logging.INFO))
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
```

`src/eink_dashboard/api/__init__.py` et `src/eink_dashboard/api/routes/__init__.py` : fichiers vides.

`src/eink_dashboard/api/routes/health.py` :

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

`src/eink_dashboard/main.py` :

```python
from fastapi import FastAPI

from eink_dashboard.api.routes import health
from eink_dashboard.core.logging import configure_logging

configure_logging()

app = FastAPI(title="eink-dashboard")
app.include_router(health.router)
```

- [ ] **Step 5: Installer et lancer le test**

Run: `pip install -e ".[dev]" && pytest tests/unit/test_health.py -v`
Expected: PASS

- [ ] **Step 6: Vérifier lint et typage**

Run: `ruff check . && ruff format --check . && mypy`
Expected: aucune erreur. Si `ruff format --check` échoue, lancer `ruff format .` puis relancer.

- [ ] **Step 7: Créer `.gitignore`, `.env.example`, `README.md`**

`.gitignore` :

```
__pycache__/
*.egg-info/
.venv/
.env
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

`.env.example` :

```
GRANDLYON_USERNAME=
GRANDLYON_PASSWORD=
DEVICE_MAC=
DEVICE_API_KEY=
PUBLIC_BASE_URL=http://192.168.1.10:8000
TZ=Europe/Paris
LOG_LEVEL=INFO
TCL_REFRESH_SECONDS=60
VELOV_REFRESH_SECONDS=60
CONFIG_PATH=config/dashboard.toml
```

`README.md` : trois lignes décrivant le projet et la commande `docker compose up -d`.

- [ ] **Step 8: Créer `Dockerfile`**

```dockerfile
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

CMD ["uvicorn", "eink_dashboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 9: Créer `compose.yaml`**

```yaml
services:
  dashboard:
    build: .
    image: eink-dashboard:latest
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file:
      - .env
    volumes:
      - ./config:/app/config:ro
```

- [ ] **Step 10: Valider le conteneur**

Run: `cp .env.example .env && mkdir -p config && touch config/dashboard.toml && docker compose up -d --build`
Puis: `curl -sf http://localhost:8000/health`
Expected: `{"status":"ok"}`
Puis: `docker compose ps` montre l'état `healthy` au bout d'une minute.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "feat: squelette FastAPI, outillage et conteneur"
```

---

## Task 2: Configuration par environnement et TOML

**Files:**
- Create: `src/eink_dashboard/core/config.py`
- Create: `config/dashboard.toml`
- Test: `tests/unit/test_config.py`, `tests/fixtures/dashboard_ok.toml`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `Settings` (pydantic-settings) avec les attributs `grandlyon_username: str`, `grandlyon_password: str`, `device_mac: str`, `device_api_key: str`, `public_base_url: str`, `tz: str`, `log_level: str`, `tcl_refresh_seconds: int`, `velov_refresh_seconds: int`, `config_path: Path`.
  - `TclStop(name: str, stop_id: str, lines: list[str], directions: list[str])`
  - `VelovStation(station_id: str, label: str)`
  - `DashboardConfig(tcl_stops: list[TclStop], velov_stations: list[VelovStation])`
  - `load_dashboard_config(path: Path) -> DashboardConfig`
  - `get_settings() -> Settings` (mis en cache par `functools.lru_cache`)

- [ ] **Step 1: Créer la fixture TOML**

`tests/fixtures/dashboard_ok.toml` :

```toml
[[tcl.stops]]
name = "Bellecour"
stop_id = "1234"
lines = ["A", "D"]
directions = ["Vaulx-en-Velin La Soie"]

[[tcl.stops]]
name = "Part-Dieu"
stop_id = "5678"
lines = ["B"]
directions = []

[[velov.stations]]
station_id = "1032"
label = "Pizay"

[[velov.stations]]
station_id = "1024"
label = "Rouville"
```

- [ ] **Step 2: Écrire les tests qui échouent**

`tests/unit/test_config.py` :

```python
from pathlib import Path

import pytest
from pydantic import ValidationError

from eink_dashboard.core.config import Settings, load_dashboard_config

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_load_dashboard_config_reads_stops_and_stations() -> None:
    config = load_dashboard_config(FIXTURES / "dashboard_ok.toml")

    assert [stop.name for stop in config.tcl_stops] == ["Bellecour", "Part-Dieu"]
    assert config.tcl_stops[0].lines == ["A", "D"]
    assert config.tcl_stops[1].directions == []
    assert [station.station_id for station in config.velov_stations] == ["1032", "1024"]


def test_load_dashboard_config_rejects_missing_stop_id(tmp_path: Path) -> None:
    bad = tmp_path / "bad.toml"
    bad.write_text('[[tcl.stops]]\nname = "Sans identifiant"\n', encoding="utf-8")

    with pytest.raises(ValidationError):
        load_dashboard_config(bad)


def test_load_dashboard_config_accepts_empty_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.toml"
    empty.write_text("", encoding="utf-8")

    config = load_dashboard_config(empty)

    assert config.tcl_stops == []
    assert config.velov_stations == []


def test_settings_read_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRANDLYON_USERNAME", "alice")
    monkeypatch.setenv("TCL_REFRESH_SECONDS", "90")

    settings = Settings(_env_file=None)

    assert settings.grandlyon_username == "alice"
    assert settings.tcl_refresh_seconds == 90
    assert settings.velov_refresh_seconds == 60
```

- [ ] **Step 3: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_config.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.core.config'`

- [ ] **Step 4: Écrire l'implémentation**

`src/eink_dashboard/core/config.py` :

```python
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TclStop(BaseModel):
    name: str
    stop_id: str
    lines: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)


class VelovStation(BaseModel):
    station_id: str
    label: str


class DashboardConfig(BaseModel):
    tcl_stops: list[TclStop] = Field(default_factory=list)
    velov_stations: list[VelovStation] = Field(default_factory=list)


def load_dashboard_config(path: Path) -> DashboardConfig:
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return DashboardConfig(
        tcl_stops=raw.get("tcl", {}).get("stops", []),
        velov_stations=raw.get("velov", {}).get("stations", []),
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    grandlyon_username: str = ""
    grandlyon_password: str = ""
    device_mac: str = ""
    device_api_key: str = ""
    public_base_url: str = "http://localhost:8000"
    tz: str = "Europe/Paris"
    log_level: str = "INFO"
    tcl_refresh_seconds: int = 60
    velov_refresh_seconds: int = 60
    config_path: Path = Path("config/dashboard.toml")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: Lancer les tests et vérifier qu'ils passent**

Run: `pytest tests/unit/test_config.py -v && mypy && ruff check .`
Expected: PASS, aucune erreur

- [ ] **Step 6: Créer le fichier de configuration réel**

`config/dashboard.toml` : copier `tests/fixtures/dashboard_ok.toml` en remplaçant les valeurs par les arrêts réellement suivis. Les identifiants d'arrêt TCL seront corrigés à la Task 6, une fois la capture faite.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: configuration par environnement et fichier TOML"
```

---

## Task 3: Modèles de domaine, état et protocole fournisseur

**Files:**
- Create: `src/eink_dashboard/domain/__init__.py`, `domain/transit.py`, `domain/bikes.py`
- Create: `src/eink_dashboard/state.py`
- Create: `src/eink_dashboard/providers/__init__.py`, `providers/base.py`
- Test: `tests/unit/test_state.py`

**Interfaces:**
- Consumes: rien.
- Produces:
  - `Departure(line: str, direction: str, expected_at: datetime, is_realtime: bool)`, frozen dataclass, avec `minutes_until(now: datetime) -> int`.
  - `StopBoard(stop_name: str, departures: tuple[Departure, ...])`, frozen dataclass.
  - `BikeStation(station_id: str, label: str, bikes_available: int, bikes_mechanical: int, bikes_electric: int, docks_available: int, capacity: int, is_renting: bool, reported_at: datetime)`, frozen dataclass.
  - `ProviderStatus = Literal["ok", "stale", "error", "unknown"]`
  - `ProviderResult[T]` avec `name`, `status`, `data`, `updated_at`, `error`, et `age_seconds(now) -> float | None`.
  - `DashboardState(tcl: ProviderResult[tuple[StopBoard, ...]], velov: ProviderResult[tuple[BikeStation, ...]])`
  - `Store` avec `state -> DashboardState`, `record_success(name, data, now)`, `record_failure(name, error, now)`, `mark_stale_if_old(now, max_age_seconds)`.
  - `Provider[T]` protocol avec `name: str`, `interval: float`, `async fetch() -> T`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/unit/test_state.py` :

```python
from datetime import UTC, datetime, timedelta

from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.state import Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def board() -> tuple[StopBoard, ...]:
    return (
        StopBoard(
            stop_name="Bellecour",
            departures=(
                Departure("A", "Vaulx", T0 + timedelta(minutes=3), is_realtime=True),
            ),
        ),
    )


def station() -> tuple[BikeStation, ...]:
    return (
        BikeStation("1032", "Pizay", 12, 8, 4, 8, 20, True, T0),
    )


def test_departure_minutes_until_rounds_down() -> None:
    departure = Departure("A", "Vaulx", T0 + timedelta(seconds=209), is_realtime=True)
    assert departure.minutes_until(T0) == 3


def test_departure_minutes_until_never_negative() -> None:
    departure = Departure("A", "Vaulx", T0 - timedelta(minutes=5), is_realtime=True)
    assert departure.minutes_until(T0) == 0


def test_new_store_reports_unknown() -> None:
    store = Store()
    assert store.state.tcl.status == "unknown"
    assert store.state.tcl.data is None
    assert store.state.velov.status == "unknown"


def test_record_success_sets_ok_and_timestamp() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)

    assert store.state.tcl.status == "ok"
    assert store.state.tcl.updated_at == T0
    assert store.state.tcl.data is not None
    assert store.state.tcl.error is None


def test_record_failure_keeps_last_good_data() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)
    store.record_failure("tcl", "timeout", T0 + timedelta(seconds=60))

    assert store.state.tcl.status == "error"
    assert store.state.tcl.error == "timeout"
    assert store.state.tcl.data is not None
    assert store.state.tcl.updated_at == T0


def test_failure_on_one_provider_leaves_the_other_untouched() -> None:
    store = Store()
    store.record_success("tcl", board(), T0)
    store.record_success("velov", station(), T0)
    store.record_failure("tcl", "boom", T0 + timedelta(seconds=60))

    assert store.state.tcl.status == "error"
    assert store.state.velov.status == "ok"


def test_mark_stale_if_old_flips_ok_to_stale() -> None:
    store = Store()
    store.record_success("velov", station(), T0)
    store.mark_stale_if_old(T0 + timedelta(seconds=181), max_age_seconds=180)

    assert store.state.velov.status == "stale"


def test_mark_stale_if_old_leaves_fresh_data_alone() -> None:
    store = Store()
    store.record_success("velov", station(), T0)
    store.mark_stale_if_old(T0 + timedelta(seconds=100), max_age_seconds=180)

    assert store.state.velov.status == "ok"


def test_age_seconds_is_none_without_data() -> None:
    store = Store()
    assert store.state.tcl.age_seconds(T0) is None
```

- [ ] **Step 2: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_state.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.domain'`

- [ ] **Step 3: Écrire les modèles de domaine**

`src/eink_dashboard/domain/__init__.py` : fichier vide.

`src/eink_dashboard/domain/transit.py` :

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Departure:
    line: str
    direction: str
    expected_at: datetime
    is_realtime: bool

    def minutes_until(self, now: datetime) -> int:
        delta = (self.expected_at - now).total_seconds()
        return max(0, int(delta // 60))


@dataclass(frozen=True, slots=True)
class StopBoard:
    stop_name: str
    departures: tuple[Departure, ...]
```

`src/eink_dashboard/domain/bikes.py` :

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class BikeStation:
    station_id: str
    label: str
    bikes_available: int
    bikes_mechanical: int
    bikes_electric: int
    docks_available: int
    capacity: int
    is_renting: bool
    reported_at: datetime
```

- [ ] **Step 4: Écrire l'état**

`src/eink_dashboard/state.py` :

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.transit import StopBoard

ProviderStatus = Literal["ok", "stale", "error", "unknown"]


@dataclass(slots=True)
class ProviderResult[T]:
    name: str
    status: ProviderStatus = "unknown"
    data: T | None = None
    updated_at: datetime | None = None
    error: str | None = None

    def age_seconds(self, now: datetime) -> float | None:
        if self.updated_at is None:
            return None
        return (now - self.updated_at).total_seconds()


@dataclass(slots=True)
class DashboardState:
    tcl: ProviderResult[tuple[StopBoard, ...]] = field(
        default_factory=lambda: ProviderResult[tuple[StopBoard, ...]](name="tcl")
    )
    velov: ProviderResult[tuple[BikeStation, ...]] = field(
        default_factory=lambda: ProviderResult[tuple[BikeStation, ...]](name="velov")
    )


class Store:
    def __init__(self) -> None:
        self._state = DashboardState()

    @property
    def state(self) -> DashboardState:
        return self._state

    def _slot(self, name: str) -> ProviderResult[object]:
        slot = getattr(self._state, name, None)
        if slot is None:
            raise KeyError(f"fournisseur inconnu: {name}")
        return slot

    def record_success(self, name: str, data: object, now: datetime) -> None:
        slot = self._slot(name)
        slot.data = data
        slot.status = "ok"
        slot.updated_at = now
        slot.error = None

    def record_failure(self, name: str, error: str, now: datetime) -> None:
        slot = self._slot(name)
        slot.status = "error"
        slot.error = error

    def mark_stale_if_old(self, now: datetime, max_age_seconds: float) -> None:
        for name in ("tcl", "velov"):
            slot = self._slot(name)
            age = slot.age_seconds(now)
            if slot.status == "ok" and age is not None and age > max_age_seconds:
                slot.status = "stale"
```

Note sur le typage : `_slot` renvoie `ProviderResult[object]` pour permettre l'accès générique par nom. Si `mypy --strict` proteste sur la variance, annoter le retour `ProviderResult[Any]` et ajouter `# type: ignore[misc]` uniquement sur cette ligne. Le reste du fichier reste strictement typé.

- [ ] **Step 5: Écrire le protocole fournisseur**

`src/eink_dashboard/providers/__init__.py` : fichier vide.

`src/eink_dashboard/providers/base.py` :

```python
from typing import Protocol


class Provider[T](Protocol):
    name: str
    interval: float

    async def fetch(self) -> T: ...
```

- [ ] **Step 6: Lancer les tests et vérifier qu'ils passent**

Run: `pytest tests/unit/test_state.py -v && mypy && ruff check .`
Expected: PASS, aucune erreur

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: modeles de domaine, etat en memoire et protocole fournisseur"
```

---

## Task 4: Vélo'v, schémas et transformation

**Files:**
- Create: `src/eink_dashboard/providers/velov/__init__.py`, `velov/schemas.py`, `velov/mapper.py`
- Test: `tests/unit/test_velov_mapper.py`
- Test: `tests/fixtures/velov_station_status.json`, `tests/fixtures/velov_station_information.json`

**Interfaces:**
- Consumes: `BikeStation` (Task 3), `VelovStation` (Task 2).
- Produces:
  - `StationStatusFeed`, `StationInformationFeed` (modèles Pydantic).
  - `to_bike_stations(status: StationStatusFeed, information: StationInformationFeed, configured: Sequence[VelovStation]) -> tuple[BikeStation, ...]`

Le format GBFS v3 utilisé ici a été vérifié en direct sur les flux réels le 2026-09-02. Les fixtures sont des extraits fidèles de ces réponses.

- [ ] **Step 1: Créer les fixtures**

`tests/fixtures/velov_station_status.json` :

```json
{
  "last_updated": "2026-09-02T17:37:16.148Z",
  "ttl": 1,
  "version": "3.0",
  "data": {
    "stations": [
      {
        "station_id": "1032",
        "num_vehicles_available": 12,
        "vehicle_types_available": [
          {"vehicle_type_id": "mechanical", "count": 8},
          {"vehicle_type_id": "electrical", "count": 4}
        ],
        "num_vehicles_disabled": 1,
        "num_docks_available": 7,
        "num_docks_disabled": 0,
        "is_installed": true,
        "is_renting": true,
        "is_returning": true,
        "last_reported": "2026-09-02T17:36:00Z"
      },
      {
        "station_id": "1024",
        "num_vehicles_available": 5,
        "vehicle_types_available": [
          {"vehicle_type_id": "mechanical", "count": 0},
          {"vehicle_type_id": "electrical", "count": 5}
        ],
        "num_vehicles_disabled": 5,
        "num_docks_available": 7,
        "num_docks_disabled": 0,
        "is_installed": true,
        "is_renting": true,
        "is_returning": true,
        "last_reported": "2026-09-02T16:47:33Z"
      },
      {
        "station_id": "1",
        "num_vehicles_available": 0,
        "vehicle_types_available": [],
        "num_vehicles_disabled": 0,
        "num_docks_available": 0,
        "num_docks_disabled": 0,
        "is_installed": false,
        "is_renting": false,
        "is_returning": false,
        "last_reported": "2025-07-15T07:41:26Z"
      }
    ]
  }
}
```

`tests/fixtures/velov_station_information.json` :

```json
{
  "last_updated": "2026-09-02T17:37:16.836Z",
  "ttl": 300,
  "version": "3.0",
  "data": {
    "stations": [
      {
        "station_id": "1032",
        "name": [{"text": "PIZAY", "language": "fr"}],
        "lat": 45.767,
        "lon": 4.836,
        "address": "Rue Pizay",
        "capacity": 20
      },
      {
        "station_id": "1024",
        "name": [{"text": "ROUVILLE", "language": "fr"}],
        "lat": 45.769684,
        "lon": 4.824607,
        "address": "PLACE ROUVILLE",
        "capacity": 17
      }
    ]
  }
}
```

- [ ] **Step 2: Écrire les tests qui échouent**

`tests/unit/test_velov_mapper.py` :

```python
import json
from pathlib import Path

from eink_dashboard.core.config import VelovStation
from eink_dashboard.providers.velov.mapper import to_bike_stations
from eink_dashboard.providers.velov.schemas import StationInformationFeed, StationStatusFeed

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_status() -> StationStatusFeed:
    return StationStatusFeed.model_validate_json(
        (FIXTURES / "velov_station_status.json").read_text(encoding="utf-8")
    )


def load_information() -> StationInformationFeed:
    return StationInformationFeed.model_validate_json(
        (FIXTURES / "velov_station_information.json").read_text(encoding="utf-8")
    )


CONFIGURED = [
    VelovStation(station_id="1032", label="Pizay"),
    VelovStation(station_id="1024", label="Rouville"),
]


def test_schemas_parse_real_payloads() -> None:
    assert len(load_status().data.stations) == 3
    assert len(load_information().data.stations) == 2


def test_mapper_keeps_configured_order() -> None:
    stations = to_bike_stations(load_status(), load_information(), CONFIGURED)
    assert [station.station_id for station in stations] == ["1032", "1024"]


def test_mapper_uses_configured_label_not_provider_name() -> None:
    stations = to_bike_stations(load_status(), load_information(), CONFIGURED)
    assert stations[0].label == "Pizay"


def test_mapper_splits_mechanical_and_electric() -> None:
    stations = to_bike_stations(load_status(), load_information(), CONFIGURED)
    assert stations[0].bikes_mechanical == 8
    assert stations[0].bikes_electric == 4
    assert stations[0].bikes_available == 12


def test_mapper_reads_capacity_from_information_feed() -> None:
    stations = to_bike_stations(load_status(), load_information(), CONFIGURED)
    assert stations[0].capacity == 20
    assert stations[1].capacity == 17


def test_mapper_skips_station_absent_from_status() -> None:
    configured = [*CONFIGURED, VelovStation(station_id="9999", label="Fantome")]
    stations = to_bike_stations(load_status(), load_information(), configured)
    assert [station.station_id for station in stations] == ["1032", "1024"]


def test_mapper_falls_back_to_zero_capacity_when_information_missing() -> None:
    information = load_information()
    information.data.stations = [
        station for station in information.data.stations if station.station_id != "1024"
    ]
    stations = to_bike_stations(load_status(), information, CONFIGURED)
    assert stations[1].capacity == 0


def test_mapper_reports_out_of_service_station() -> None:
    configured = [VelovStation(station_id="1", label="Hors service")]
    stations = to_bike_stations(load_status(), load_information(), configured)
    assert stations[0].is_renting is False
```

- [ ] **Step 3: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_velov_mapper.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.providers.velov'`

- [ ] **Step 4: Écrire les schémas**

`src/eink_dashboard/providers/velov/__init__.py` : fichier vide.

`src/eink_dashboard/providers/velov/schemas.py` :

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class VehicleTypeCount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vehicle_type_id: str
    count: int = 0


class StationStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    station_id: str
    num_vehicles_available: int = 0
    num_docks_available: int = 0
    vehicle_types_available: list[VehicleTypeCount] = Field(default_factory=list)
    is_installed: bool = False
    is_renting: bool = False
    is_returning: bool = False
    last_reported: datetime


class StationStatusData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stations: list[StationStatus] = Field(default_factory=list)


class StationStatusFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    last_updated: datetime
    data: StationStatusData


class LocalizedName(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    language: str = "fr"


class StationInformation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    station_id: str
    name: list[LocalizedName] = Field(default_factory=list)
    address: str | None = None
    capacity: int = 0


class StationInformationData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stations: list[StationInformation] = Field(default_factory=list)


class StationInformationFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    last_updated: datetime
    data: StationInformationData
```

- [ ] **Step 5: Écrire le mapper**

`src/eink_dashboard/providers/velov/mapper.py` :

```python
from collections.abc import Sequence

from eink_dashboard.core.config import VelovStation
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.providers.velov.schemas import StationInformationFeed, StationStatusFeed

MECHANICAL = "mechanical"
ELECTRICAL = "electrical"


def to_bike_stations(
    status: StationStatusFeed,
    information: StationInformationFeed,
    configured: Sequence[VelovStation],
) -> tuple[BikeStation, ...]:
    by_status = {station.station_id: station for station in status.data.stations}
    by_information = {station.station_id: station for station in information.data.stations}

    result: list[BikeStation] = []
    for wanted in configured:
        live = by_status.get(wanted.station_id)
        if live is None:
            continue
        counts = {entry.vehicle_type_id: entry.count for entry in live.vehicle_types_available}
        reference = by_information.get(wanted.station_id)
        result.append(
            BikeStation(
                station_id=wanted.station_id,
                label=wanted.label,
                bikes_available=live.num_vehicles_available,
                bikes_mechanical=counts.get(MECHANICAL, 0),
                bikes_electric=counts.get(ELECTRICAL, 0),
                docks_available=live.num_docks_available,
                capacity=reference.capacity if reference else 0,
                is_renting=live.is_renting,
                reported_at=live.last_reported,
            )
        )
    return tuple(result)
```

- [ ] **Step 6: Lancer les tests et vérifier qu'ils passent**

Run: `pytest tests/unit/test_velov_mapper.py -v && mypy && ruff check .`
Expected: PASS, aucune erreur

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: schemas GBFS et transformation Velov vers le domaine"
```

---

## Task 5: Client HTTP Vélo'v

**Files:**
- Create: `src/eink_dashboard/providers/velov/client.py`
- Test: `tests/unit/test_velov_client.py`
- Test: `tests/integration/test_velov_live.py`

**Interfaces:**
- Consumes: `to_bike_stations`, `StationStatusFeed`, `StationInformationFeed` (Task 4), `VelovStation` (Task 2).
- Produces: `VelovClient(http: httpx.AsyncClient, stations: Sequence[VelovStation], interval: float = 60.0, information_ttl: float = 3600.0)` avec `name = "velov"` et `async fetch() -> tuple[BikeStation, ...]`. Constantes de module `STATUS_URL` et `INFORMATION_URL`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/unit/test_velov_client.py` :

```python
import json
from pathlib import Path

import httpx
import pytest
import respx

from eink_dashboard.core.config import VelovStation
from eink_dashboard.providers.velov.client import INFORMATION_URL, STATUS_URL, VelovClient

FIXTURES = Path(__file__).parent.parent / "fixtures"
STATUS = json.loads((FIXTURES / "velov_station_status.json").read_text(encoding="utf-8"))
INFORMATION = json.loads((FIXTURES / "velov_station_information.json").read_text(encoding="utf-8"))
CONFIGURED = [VelovStation(station_id="1032", label="Pizay")]


@respx.mock
async def test_fetch_returns_domain_objects() -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=STATUS))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with httpx.AsyncClient() as http:
        stations = await VelovClient(http, CONFIGURED).fetch()

    assert len(stations) == 1
    assert stations[0].label == "Pizay"
    assert stations[0].bikes_available == 12


@respx.mock
async def test_information_feed_is_cached_between_calls() -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json=STATUS))
    information_route = respx.get(INFORMATION_URL).mock(
        return_value=httpx.Response(200, json=INFORMATION)
    )

    async with httpx.AsyncClient() as http:
        client = VelovClient(http, CONFIGURED)
        await client.fetch()
        await client.fetch()

    assert information_route.call_count == 1


@respx.mock
async def test_server_error_raises() -> None:
    respx.get(STATUS_URL).mock(return_value=httpx.Response(500))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.HTTPStatusError):
            await VelovClient(http, CONFIGURED).fetch()


@respx.mock
async def test_timeout_propagates() -> None:
    respx.get(STATUS_URL).mock(side_effect=httpx.ConnectTimeout("trop lent"))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.ConnectTimeout):
            await VelovClient(http, CONFIGURED).fetch()


@respx.mock
async def test_malformed_payload_raises_validation_error() -> None:
    from pydantic import ValidationError

    respx.get(STATUS_URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))
    respx.get(INFORMATION_URL).mock(return_value=httpx.Response(200, json=INFORMATION))

    async with httpx.AsyncClient() as http:
        with pytest.raises(ValidationError):
            await VelovClient(http, CONFIGURED).fetch()
```

- [ ] **Step 2: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_velov_client.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.providers.velov.client'`

- [ ] **Step 3: Écrire le client**

`src/eink_dashboard/providers/velov/client.py` :

```python
import time
from collections.abc import Sequence

import httpx

from eink_dashboard.core.config import VelovStation
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.providers.velov.mapper import to_bike_stations
from eink_dashboard.providers.velov.schemas import StationInformationFeed, StationStatusFeed

BASE = "https://api.cyclocity.fr/contracts/lyon/gbfs/v3"
STATUS_URL = f"{BASE}/station_status.json"
INFORMATION_URL = f"{BASE}/station_information.json"


class VelovClient:
    name = "velov"

    def __init__(
        self,
        http: httpx.AsyncClient,
        stations: Sequence[VelovStation],
        interval: float = 60.0,
        information_ttl: float = 3600.0,
    ) -> None:
        self._http = http
        self._stations = stations
        self.interval = interval
        self._information_ttl = information_ttl
        self._information: StationInformationFeed | None = None
        self._information_fetched_at = 0.0

    async def _information_feed(self) -> StationInformationFeed:
        now = time.monotonic()
        cached = self._information
        if cached is not None and now - self._information_fetched_at < self._information_ttl:
            return cached
        response = await self._http.get(INFORMATION_URL)
        response.raise_for_status()
        feed = StationInformationFeed.model_validate_json(response.content)
        self._information = feed
        self._information_fetched_at = now
        return feed

    async def fetch(self) -> tuple[BikeStation, ...]:
        information = await self._information_feed()
        response = await self._http.get(STATUS_URL)
        response.raise_for_status()
        status = StationStatusFeed.model_validate_json(response.content)
        return to_bike_stations(status, information, self._stations)
```

- [ ] **Step 4: Lancer les tests et vérifier qu'ils passent**

Run: `pytest tests/unit/test_velov_client.py -v && mypy && ruff check .`
Expected: PASS, aucune erreur

- [ ] **Step 5: Ajouter le test réseau, exclu par défaut**

`tests/integration/test_velov_live.py` :

```python
import httpx
import pytest

from eink_dashboard.core.config import VelovStation
from eink_dashboard.providers.velov.client import VelovClient


@pytest.mark.network
async def test_live_velov_returns_configured_station() -> None:
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
        stations = await VelovClient(http, [VelovStation(station_id="1024", label="Rouville")]).fetch()

    assert len(stations) == 1
    assert stations[0].capacity > 0
```

- [ ] **Step 6: Valider contre le vrai flux**

Run: `pytest tests/integration/test_velov_live.py -m network -v`
Expected: PASS. C'est le critère de validation de la phase Vélo'v.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: client HTTP Velov avec cache du referentiel"
```

---

## Task 6: TCL, capture du format réel puis schémas et transformation

**Files:**
- Create: `tests/fixtures/tcl_passages.json`
- Create: `docs/tcl-api-notes.md`
- Create: `src/eink_dashboard/providers/tcl/__init__.py`, `tcl/schemas.py`, `tcl/mapper.py`
- Test: `tests/unit/test_tcl_mapper.py`

**Interfaces:**
- Consumes: `Departure`, `StopBoard` (Task 3), `TclStop` (Task 2).
- Produces:
  - `TCL_FIELDS: dict[str, str]`, table de correspondance entre les noms de champs de l'API et les noms internes `stop_id`, `line`, `direction`, `expected_at`, `is_realtime`.
  - `PassageRecord`, `PassageFeed` (modèles Pydantic).
  - `to_stop_boards(feed: PassageFeed, stop: TclStop, limit: int = 4) -> StopBoard`

**Pourquoi une étape de capture.** Le jeu `tcl_sytral.tclpassagearret` est derrière authentification HTTP Basic. Ses noms de champs n'ont pas pu être vérifiés à l'écriture de ce plan. Un seul point de la base de code en dépend, la constante `TCL_FIELDS`. Les steps 1 à 3 la remplissent à partir d'une capture réelle, tout le reste est écrit une fois pour toutes.

- [ ] **Step 1: Capturer une réponse réelle**

Run, en remplaçant les identifiants et en gardant les guillemets simples :

```bash
curl -s -u "$GRANDLYON_USERNAME:$GRANDLYON_PASSWORD" \
  'https://download.data.grandlyon.com/ws/rdata/tcl_sytral.tclpassagearret/all.json?maxfeatures=20&start=1' \
  > tests/fixtures/tcl_passages.json
```

Expected: un JSON de la forme `{"nb_results": N, "values": [ ... ]}`. Si la réponse est `{"detail": "Informations d'authentification non fournies."}`, les identifiants sont absents de l'environnement.

- [ ] **Step 2: Documenter les champs observés**

Ouvrir la fixture et créer `docs/tcl-api-notes.md` avec la liste des clés d'un enregistrement de `values`, une par ligne, avec un exemple de valeur. Identifier lequel porte l'identifiant du point d'arrêt, le numéro de ligne, le libellé de destination, l'heure de passage attendue, et l'indicateur temps réel contre théorique.

- [ ] **Step 3: Écrire le test qui échoue sur la table de correspondance**

`tests/unit/test_tcl_mapper.py`, première partie :

```python
import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_fixture_contains_every_mapped_field() -> None:
    from eink_dashboard.providers.tcl.schemas import TCL_FIELDS

    payload = json.loads((FIXTURES / "tcl_passages.json").read_text(encoding="utf-8"))
    record = payload["values"][0]

    missing = [api_name for api_name in TCL_FIELDS.values() if api_name not in record]
    assert missing == [], f"champs absents de la capture: {missing}"
```

Ce test est le garde-fou : il échoue si la table de correspondance ne colle pas à la réalité de l'API, aujourd'hui comme après un changement de format.

- [ ] **Step 4: Écrire les schémas avec la table de correspondance**

`src/eink_dashboard/providers/tcl/__init__.py` : fichier vide.

`src/eink_dashboard/providers/tcl/schemas.py` :

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Rempli à partir de docs/tcl-api-notes.md, vérifié par
# tests/unit/test_tcl_mapper.py::test_fixture_contains_every_mapped_field.
# Clé = nom interne, valeur = nom du champ dans la réponse de l'API.
TCL_FIELDS: dict[str, str] = {
    "stop_id": "id",
    "line": "ligne",
    "direction": "direction",
    "expected_at": "heurepassage",
    "kind": "type",
}


class PassageRecord(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    stop_id: str = Field(alias=TCL_FIELDS["stop_id"])
    line: str = Field(alias=TCL_FIELDS["line"])
    direction: str = Field(default="", alias=TCL_FIELDS["direction"])
    expected_at: datetime = Field(alias=TCL_FIELDS["expected_at"])
    kind: str = Field(default="", alias=TCL_FIELDS["kind"])


class PassageFeed(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nb_results: int = 0
    values: list[PassageRecord] = Field(default_factory=list)
```

Corriger les valeurs de `TCL_FIELDS` pour qu'elles correspondent exactement aux clés relevées au Step 2. Si un champ n'existe pas dans la capture, le retirer de la table et donner une valeur par défaut au champ Pydantic correspondant.

- [ ] **Step 5: Lancer le test de correspondance**

Run: `pytest tests/unit/test_tcl_mapper.py::test_fixture_contains_every_mapped_field -v`
Expected: PASS. Tant qu'il échoue, corriger `TCL_FIELDS`, pas le test.

- [ ] **Step 6: Écrire les tests du mapper**

`tests/unit/test_tcl_mapper.py`, suite du fichier :

```python
from datetime import UTC, datetime, timedelta

from eink_dashboard.core.config import TclStop
from eink_dashboard.providers.tcl.mapper import to_stop_boards
from eink_dashboard.providers.tcl.schemas import PassageFeed, PassageRecord

NOW = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def record(line: str, direction: str, minutes: int, kind: str = "E") -> PassageRecord:
    return PassageRecord(
        stop_id="1234",
        line=line,
        direction=direction,
        expected_at=NOW + timedelta(minutes=minutes),
        kind=kind,
    )


def test_departures_are_sorted_by_time() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 9), record("A", "Vaulx", 2)])
    board = to_stop_boards(feed, TclStop(name="Bellecour", stop_id="1234"))

    assert [departure.minutes_until(NOW) for departure in board.departures] == [2, 9]


def test_stop_name_comes_from_configuration() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2)])
    board = to_stop_boards(feed, TclStop(name="Bellecour", stop_id="1234"))

    assert board.stop_name == "Bellecour"


def test_line_filter_excludes_other_lines() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2), record("D", "Venissieux", 3)])
    board = to_stop_boards(feed, TclStop(name="Bellecour", stop_id="1234", lines=["A"]))

    assert [departure.line for departure in board.departures] == ["A"]


def test_direction_filter_is_a_case_insensitive_substring() -> None:
    feed = PassageFeed(values=[record("A", "VAULX-EN-VELIN LA SOIE", 2), record("A", "Perrache", 3)])
    board = to_stop_boards(feed, TclStop(name="Bellecour", stop_id="1234", directions=["vaulx"]))

    assert [departure.direction for departure in board.departures] == ["VAULX-EN-VELIN LA SOIE"]


def test_empty_filters_keep_everything() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2), record("D", "Venissieux", 3)])
    board = to_stop_boards(feed, TclStop(name="Bellecour", stop_id="1234"))

    assert len(board.departures) == 2


def test_limit_caps_the_number_of_departures() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", minutes) for minutes in (1, 2, 3, 4, 5, 6)])
    board = to_stop_boards(feed, TclStop(name="Bellecour", stop_id="1234"), limit=4)

    assert len(board.departures) == 4


def test_no_passage_produces_an_empty_board() -> None:
    board = to_stop_boards(PassageFeed(), TclStop(name="Bellecour", stop_id="1234"))

    assert board.stop_name == "Bellecour"
    assert board.departures == ()


def test_theoretical_passage_is_not_realtime() -> None:
    feed = PassageFeed(values=[record("A", "Vaulx", 2, kind="T")])
    board = to_stop_boards(feed, TclStop(name="Bellecour", stop_id="1234"))

    assert board.departures[0].is_realtime is False
```

Ajuster `kind="E"` et `kind="T"` aux valeurs réellement observées au Step 2. Si le champ n'existe pas, supprimer le dernier test et fixer `is_realtime=True`.

- [ ] **Step 7: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_tcl_mapper.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.providers.tcl.mapper'`

- [ ] **Step 8: Écrire le mapper**

`src/eink_dashboard/providers/tcl/mapper.py` :

```python
from eink_dashboard.core.config import TclStop
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.providers.tcl.schemas import PassageFeed, PassageRecord

REALTIME_KIND = "E"


def _matches(record: PassageRecord, stop: TclStop) -> bool:
    if stop.lines and record.line not in stop.lines:
        return False
    if stop.directions:
        haystack = record.direction.casefold()
        return any(wanted.casefold() in haystack for wanted in stop.directions)
    return True


def to_stop_boards(feed: PassageFeed, stop: TclStop, limit: int = 4) -> StopBoard:
    departures = [
        Departure(
            line=record.line,
            direction=record.direction,
            expected_at=record.expected_at,
            is_realtime=record.kind == REALTIME_KIND,
        )
        for record in feed.values
        if _matches(record, stop)
    ]
    departures.sort(key=lambda departure: departure.expected_at)
    return StopBoard(stop_name=stop.name, departures=tuple(departures[:limit]))
```

- [ ] **Step 9: Lancer les tests et vérifier qu'ils passent**

Run: `pytest tests/unit/test_tcl_mapper.py -v && mypy && ruff check .`
Expected: PASS, aucune erreur

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: schemas et transformation TCL avec table de correspondance verifiee"
```

---

## Task 7: Client HTTP TCL

**Files:**
- Create: `src/eink_dashboard/providers/tcl/client.py`
- Test: `tests/unit/test_tcl_client.py`
- Test: `tests/integration/test_tcl_live.py`

**Interfaces:**
- Consumes: `PassageFeed`, `to_stop_boards`, `TCL_FIELDS` (Task 6), `TclStop` (Task 2), `StopBoard` (Task 3).
- Produces: `TclClient(http: httpx.AsyncClient, stops: Sequence[TclStop], username: str, password: str, interval: float = 60.0)` avec `name = "tcl"` et `async fetch() -> tuple[StopBoard, ...]`. Constante de module `PASSAGES_URL`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/unit/test_tcl_client.py` :

```python
import base64

import httpx
import pytest
import respx
from pydantic import ValidationError

from eink_dashboard.core.config import TclStop
from eink_dashboard.providers.tcl.client import PASSAGES_URL, TclClient
from eink_dashboard.providers.tcl.schemas import TCL_FIELDS

STOPS = [TclStop(name="Bellecour", stop_id="1234", lines=["A"])]


def payload(stop_id: str = "1234") -> dict[str, object]:
    return {
        "nb_results": 1,
        "values": [
            {
                TCL_FIELDS["stop_id"]: stop_id,
                TCL_FIELDS["line"]: "A",
                TCL_FIELDS["direction"]: "Vaulx-en-Velin",
                TCL_FIELDS["expected_at"]: "2026-09-02T08:05:00+02:00",
                TCL_FIELDS["kind"]: "E",
            }
        ],
    }


def client(http: httpx.AsyncClient) -> TclClient:
    return TclClient(http, STOPS, username="alice", password="secret")


@respx.mock
async def test_fetch_returns_one_board_per_configured_stop() -> None:
    respx.get(PASSAGES_URL).mock(return_value=httpx.Response(200, json=payload()))

    async with httpx.AsyncClient() as http:
        boards = await client(http).fetch()

    assert len(boards) == 1
    assert boards[0].stop_name == "Bellecour"
    assert boards[0].departures[0].line == "A"


@respx.mock
async def test_fetch_sends_basic_authentication() -> None:
    route = respx.get(PASSAGES_URL).mock(return_value=httpx.Response(200, json=payload()))

    async with httpx.AsyncClient() as http:
        await client(http).fetch()

    expected = base64.b64encode(b"alice:secret").decode()
    assert route.calls[0].request.headers["authorization"] == f"Basic {expected}"


@respx.mock
async def test_fetch_filters_on_the_configured_stop_id() -> None:
    route = respx.get(PASSAGES_URL).mock(return_value=httpx.Response(200, json=payload()))

    async with httpx.AsyncClient() as http:
        await client(http).fetch()

    assert "1234" in str(route.calls[0].request.url)


@respx.mock
async def test_unauthorized_raises() -> None:
    respx.get(PASSAGES_URL).mock(return_value=httpx.Response(401, json={"detail": "non fourni"}))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.HTTPStatusError):
            await client(http).fetch()


@respx.mock
async def test_timeout_propagates() -> None:
    respx.get(PASSAGES_URL).mock(side_effect=httpx.ReadTimeout("trop lent"))

    async with httpx.AsyncClient() as http:
        with pytest.raises(httpx.ReadTimeout):
            await client(http).fetch()


@respx.mock
async def test_changed_payload_shape_raises_validation_error() -> None:
    respx.get(PASSAGES_URL).mock(
        return_value=httpx.Response(200, json={"nb_results": 1, "values": [{"surprise": 1}]})
    )

    async with httpx.AsyncClient() as http:
        with pytest.raises(ValidationError):
            await client(http).fetch()


@respx.mock
async def test_one_failing_stop_does_not_hide_the_others() -> None:
    stops = [
        TclStop(name="Bellecour", stop_id="1234"),
        TclStop(name="Part-Dieu", stop_id="5678"),
    ]
    respx.get(PASSAGES_URL, params={"value": "1234"}).mock(
        return_value=httpx.Response(200, json=payload("1234"))
    )
    respx.get(PASSAGES_URL, params={"value": "5678"}).mock(return_value=httpx.Response(500))

    async with httpx.AsyncClient() as http:
        boards = await TclClient(http, stops, username="a", password="b").fetch()

    assert [board.stop_name for board in boards] == ["Bellecour", "Part-Dieu"]
    assert boards[1].departures == ()
```

- [ ] **Step 2: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_tcl_client.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.providers.tcl.client'`

- [ ] **Step 3: Écrire le client**

`src/eink_dashboard/providers/tcl/client.py` :

```python
import asyncio
from collections.abc import Sequence

import httpx
import structlog

from eink_dashboard.core.config import TclStop
from eink_dashboard.domain.transit import StopBoard
from eink_dashboard.providers.tcl.mapper import to_stop_boards
from eink_dashboard.providers.tcl.schemas import TCL_FIELDS, PassageFeed

PASSAGES_URL = "https://download.data.grandlyon.com/ws/rdata/tcl_sytral.tclpassagearret/all.json"

log = structlog.get_logger()


class TclClient:
    name = "tcl"

    def __init__(
        self,
        http: httpx.AsyncClient,
        stops: Sequence[TclStop],
        username: str,
        password: str,
        interval: float = 60.0,
    ) -> None:
        self._http = http
        self._stops = stops
        self._auth = httpx.BasicAuth(username, password)
        self.interval = interval

    async def _board(self, stop: TclStop) -> StopBoard:
        response = await self._http.get(
            PASSAGES_URL,
            auth=self._auth,
            params={"field": TCL_FIELDS["stop_id"], "value": stop.stop_id, "maxfeatures": 40},
        )
        response.raise_for_status()
        feed = PassageFeed.model_validate_json(response.content)
        return to_stop_boards(feed, stop)

    async def fetch(self) -> tuple[StopBoard, ...]:
        results = await asyncio.gather(
            *(self._board(stop) for stop in self._stops), return_exceptions=True
        )
        boards: list[StopBoard] = []
        failures = 0
        for stop, result in zip(self._stops, results, strict=True):
            if isinstance(result, StopBoard):
                boards.append(result)
            else:
                failures += 1
                log.warning("tcl.stop_failed", stop=stop.name, error=str(result))
                boards.append(StopBoard(stop_name=stop.name, departures=()))
        if self._stops and failures == len(self._stops):
            raise RuntimeError(f"aucun arret TCL joignable ({failures} echecs)")
        return tuple(boards)
```

Le comportement voulu est explicite : un arrêt en échec devient un tableau vide, mais si tous les arrêts échouent la méthode lève, ce qui fait basculer le fournisseur en `error` et conserve le dernier bon état.

- [ ] **Step 4: Ajuster le test de propagation d'erreur**

Les tests `test_unauthorized_raises`, `test_timeout_propagates` et `test_changed_payload_shape_raises_validation_error` portent sur un seul arrêt configuré, donc tous les arrêts échouent et `fetch` lève. Remplacer l'exception attendue par `RuntimeError` dans ces trois tests, et vérifier la cause dans les logs plutôt que le type exact :

```python
    async with httpx.AsyncClient() as http:
        with pytest.raises(RuntimeError):
            await client(http).fetch()
```

- [ ] **Step 5: Lancer les tests et vérifier qu'ils passent**

Run: `pytest tests/unit/test_tcl_client.py -v && mypy && ruff check .`
Expected: PASS, aucune erreur

- [ ] **Step 6: Ajouter le test réseau**

`tests/integration/test_tcl_live.py` :

```python
import os

import httpx
import pytest

from eink_dashboard.core.config import load_dashboard_config
from eink_dashboard.providers.tcl.client import TclClient


@pytest.mark.network
async def test_live_tcl_returns_departures() -> None:
    username = os.environ["GRANDLYON_USERNAME"]
    password = os.environ["GRANDLYON_PASSWORD"]
    from pathlib import Path

    stops = load_dashboard_config(Path("config/dashboard.toml")).tcl_stops
    assert stops, "config/dashboard.toml doit contenir au moins un arret"

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
        boards = await TclClient(http, stops, username, password).fetch()

    assert len(boards) == len(stops)
    assert any(board.departures for board in boards)
```

- [ ] **Step 7: Valider contre la vraie API**

Run: `pytest tests/integration/test_tcl_live.py -m network -v`
Expected: PASS. Si le test ne renvoie aucun passage, les identifiants d'arrêt de `config/dashboard.toml` sont faux. Les corriger à partir du jeu de référence des arrêts avant de continuer.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: client HTTP TCL avec isolation par arret"
```

---

## Task 8: Scheduler et câblage applicatif

**Files:**
- Create: `src/eink_dashboard/scheduler.py`
- Create: `src/eink_dashboard/api/deps.py`
- Modify: `src/eink_dashboard/main.py`
- Test: `tests/unit/test_scheduler.py`

**Interfaces:**
- Consumes: `Provider` (Task 3), `Store` (Task 3), `VelovClient` (Task 5), `TclClient` (Task 7), `Settings`, `load_dashboard_config` (Task 2).
- Produces:
  - `async run_provider_loop(provider: Provider[Any], store: Store, clock: Callable[[], datetime], sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, stop_after: int | None = None) -> None`
  - `app.state.store: Store` et `app.state.settings: Settings` posés par le lifespan.
  - `get_store(request: Request) -> Store` et `get_settings_dep(request: Request) -> Settings` dans `api/deps.py`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/unit/test_scheduler.py` :

```python
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from eink_dashboard.scheduler import run_provider_loop
from eink_dashboard.state import Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


async def no_sleep(_seconds: float) -> None:
    return None


class FlakyProvider:
    name = "velov"
    interval = 60.0

    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    async def fetch(self) -> object:
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_loop_records_success() -> None:
    store = Store()
    provider = FlakyProvider(["données"])

    await run_provider_loop(provider, store, FakeClock(), no_sleep, stop_after=1)

    assert store.state.velov.status == "ok"
    assert store.state.velov.data == "données"


async def test_loop_records_failure_and_keeps_running() -> None:
    store = Store()
    provider = FlakyProvider([RuntimeError("boum"), "données"])

    await run_provider_loop(provider, store, FakeClock(), no_sleep, stop_after=2)

    assert provider.calls == 2
    assert store.state.velov.status == "ok"


async def test_loop_keeps_last_good_data_after_a_failure() -> None:
    store = Store()
    provider = FlakyProvider(["données", RuntimeError("boum")])

    await run_provider_loop(provider, store, FakeClock(), no_sleep, stop_after=2)

    assert store.state.velov.status == "error"
    assert store.state.velov.data == "données"


async def test_loop_marks_stale_when_data_gets_old() -> None:
    store = Store()
    clock = FakeClock()
    provider = FlakyProvider(["données", RuntimeError("boum"), RuntimeError("boum")])

    async def advancing_sleep(_seconds: float) -> None:
        clock.now += timedelta(seconds=120)

    await run_provider_loop(provider, store, clock, advancing_sleep, stop_after=3)

    assert store.state.velov.data == "données"
    assert store.state.velov.status in {"error", "stale"}
```

- [ ] **Step 2: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_scheduler.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.scheduler'`

- [ ] **Step 3: Écrire le scheduler**

`src/eink_dashboard/scheduler.py` :

```python
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import structlog

from eink_dashboard.providers.base import Provider
from eink_dashboard.state import Store

log = structlog.get_logger()

STALE_FACTOR = 3.0
RETRY_DELAY_SECONDS = 2.0


async def _fetch_with_one_retry(provider: Provider[Any]) -> Any:
    try:
        return await provider.fetch()
    except Exception as first_error:
        log.info("provider.retry", provider=provider.name, error=str(first_error))
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        return await provider.fetch()


async def run_provider_loop(
    provider: Provider[Any],
    store: Store,
    clock: Callable[[], datetime],
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    stop_after: int | None = None,
) -> None:
    iterations = 0
    while stop_after is None or iterations < stop_after:
        iterations += 1
        try:
            data = await _fetch_with_one_retry(provider)
        except Exception as error:
            store.record_failure(provider.name, str(error), clock())
            log.warning("provider.failed", provider=provider.name, error=str(error))
        else:
            store.record_success(provider.name, data, clock())
            log.info("provider.refreshed", provider=provider.name)

        store.mark_stale_if_old(clock(), provider.interval * STALE_FACTOR)
        await sleep(provider.interval)
```

Le retry immédiat de `_fetch_with_one_retry` utilise `asyncio.sleep` réel. Dans les tests, `FlakyProvider` échoue puis réussit à l'itération suivante, donc le retry consomme une entrée de `outcomes`. Ajuster les listes `outcomes` des tests pour tenir compte des deux appels par itération en cas d'échec : `[RuntimeError("boum"), RuntimeError("boum"), "données"]` pour le deuxième test.

- [ ] **Step 4: Corriger les tests pour le retry, puis les lancer**

Mettre à jour `test_loop_records_failure_and_keeps_running` en `FlakyProvider([RuntimeError("boum"), RuntimeError("boum"), "données"])` avec `provider.calls == 3`, et `test_loop_keeps_last_good_data_after_a_failure` en `["données", RuntimeError("boum"), RuntimeError("boum")]`.

Run: `pytest tests/unit/test_scheduler.py -v`
Expected: PASS

- [ ] **Step 5: Écrire les dépendances FastAPI**

`src/eink_dashboard/api/deps.py` :

```python
from typing import Annotated

from fastapi import Depends, Request

from eink_dashboard.core.config import Settings
from eink_dashboard.state import Store


def get_store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


StoreDep = Annotated[Store, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
```

- [ ] **Step 6: Câbler le lifespan**

`src/eink_dashboard/main.py`, contenu complet :

```python
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

from eink_dashboard.api.routes import health
from eink_dashboard.core.config import get_settings, load_dashboard_config
from eink_dashboard.core.logging import configure_logging
from eink_dashboard.providers.tcl.client import TclClient
from eink_dashboard.providers.velov.client import VelovClient
from eink_dashboard.scheduler import run_provider_loop
from eink_dashboard.state import Store

TIMEOUT = httpx.Timeout(10.0, connect=5.0)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    config = load_dashboard_config(settings.config_path)
    tz = ZoneInfo(settings.tz)

    store = Store()
    http = httpx.AsyncClient(timeout=TIMEOUT)
    app.state.settings = settings
    app.state.store = store
    app.state.tz = tz

    providers = [
        VelovClient(http, config.velov_stations, interval=settings.velov_refresh_seconds),
        TclClient(
            http,
            config.tcl_stops,
            settings.grandlyon_username,
            settings.grandlyon_password,
            interval=settings.tcl_refresh_seconds,
        ),
    ]
    tasks = [
        asyncio.create_task(run_provider_loop(provider, store, lambda: datetime.now(tz)))
        for provider in providers
    ]

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await http.aclose()


app = FastAPI(title="eink-dashboard", lifespan=lifespan)
app.include_router(health.router)
```

- [ ] **Step 7: Vérifier que rien n'est cassé**

Run: `pytest -v && mypy && ruff check .`
Expected: PASS

- [ ] **Step 8: Valider la résilience réseau**

Run: `docker compose up -d --build`, attendre une minute, puis `docker compose logs --tail 30`
Expected: des lignes JSON `provider.refreshed` pour `velov` et `tcl`.
Puis couper le réseau du conteneur : `docker network disconnect $(docker network ls --filter name=eink --format '{{.Name}}' | head -1) $(docker compose ps -q dashboard)`
Expected: des lignes `provider.failed`, et `curl -sf http://localhost:8000/health` répond toujours 200. Reconnecter le réseau ensuite.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: boucles de rafraichissement independantes et cablage applicatif"
```

---

## Task 9: `/health` réel et `/api/v1/dashboard`

**Files:**
- Modify: `src/eink_dashboard/api/routes/health.py`
- Create: `src/eink_dashboard/api/routes/dashboard.py`
- Create: `src/eink_dashboard/services/__init__.py`, `services/dashboard.py`
- Modify: `src/eink_dashboard/main.py`
- Test: `tests/unit/test_api_dashboard.py`

**Interfaces:**
- Consumes: `Store`, `DashboardState` (Task 3), `StoreDep` (Task 8).
- Produces:
  - `provider_health(result: ProviderResult[Any], now: datetime) -> dict[str, Any]` dans `services/dashboard.py`, renvoyant les clés `status`, `updated_at`, `age_seconds`.
  - Route `GET /health` renvoyant `{"status": ..., "providers": {"tcl": {...}, "velov": {...}}}`.
  - Route `GET /api/v1/dashboard` renvoyant l'état normalisé.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/unit/test_api_dashboard.py` :

```python
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eink_dashboard.api.routes import dashboard, health
from eink_dashboard.core.config import Settings
from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.state import Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def build_client(store: Store) -> TestClient:
    app = FastAPI()
    app.include_router(health.router)
    app.include_router(dashboard.router)
    app.state.store = store
    app.state.settings = Settings(_env_file=None)
    app.state.tz = ZoneInfo("Europe/Paris")
    return TestClient(app)


def filled_store() -> Store:
    store = Store()
    store.record_success(
        "tcl",
        (
            StopBoard(
                stop_name="Bellecour",
                departures=(Departure("A", "Vaulx", T0 + timedelta(minutes=3), True),),
            ),
        ),
        T0,
    )
    store.record_success(
        "velov", (BikeStation("1032", "Pizay", 12, 8, 4, 7, 20, True, T0),), T0
    )
    return store


def test_health_reports_each_provider() -> None:
    response = build_client(filled_store()).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["tcl"]["status"] == "ok"
    assert body["providers"]["velov"]["status"] == "ok"
    assert body["providers"]["tcl"]["age_seconds"] is not None


def test_health_still_returns_200_when_everything_failed() -> None:
    store = Store()
    store.record_failure("tcl", "timeout", T0)
    store.record_failure("velov", "timeout", T0)

    response = build_client(store).get("/health")

    assert response.status_code == 200
    assert response.json()["providers"]["tcl"]["status"] == "error"


def test_health_reports_unknown_on_a_fresh_store() -> None:
    body = build_client(Store()).get("/health").json()

    assert body["providers"]["tcl"]["status"] == "unknown"
    assert body["providers"]["tcl"]["age_seconds"] is None


def test_dashboard_returns_both_sources() -> None:
    body = build_client(filled_store()).get("/api/v1/dashboard").json()

    assert body["tcl"]["status"] == "ok"
    assert body["tcl"]["stops"][0]["stop_name"] == "Bellecour"
    assert body["tcl"]["stops"][0]["departures"][0]["line"] == "A"
    assert body["velov"]["stations"][0]["label"] == "Pizay"
    assert body["velov"]["stations"][0]["capacity"] == 20


def test_dashboard_returns_empty_lists_without_data() -> None:
    body = build_client(Store()).get("/api/v1/dashboard").json()

    assert body["tcl"]["stops"] == []
    assert body["velov"]["stations"] == []
```

- [ ] **Step 2: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_api_dashboard.py -v`
Expected: FAIL avec `ImportError: cannot import name 'dashboard'`

- [ ] **Step 3: Écrire le service**

`src/eink_dashboard/services/__init__.py` : fichier vide.

`src/eink_dashboard/services/dashboard.py` :

```python
from dataclasses import asdict
from datetime import datetime
from typing import Any

from eink_dashboard.state import DashboardState, ProviderResult


def provider_health(result: ProviderResult[Any], now: datetime) -> dict[str, Any]:
    return {
        "status": result.status,
        "updated_at": result.updated_at.isoformat() if result.updated_at else None,
        "age_seconds": result.age_seconds(now),
        "error": result.error,
    }


def dashboard_payload(state: DashboardState, now: datetime) -> dict[str, Any]:
    boards = state.tcl.data or ()
    stations = state.velov.data or ()
    return {
        "tcl": {
            **provider_health(state.tcl, now),
            "stops": [
                {
                    "stop_name": board.stop_name,
                    "departures": [
                        {
                            "line": departure.line,
                            "direction": departure.direction,
                            "expected_at": departure.expected_at.isoformat(),
                            "minutes": departure.minutes_until(now),
                            "is_realtime": departure.is_realtime,
                        }
                        for departure in board.departures
                    ],
                }
                for board in boards
            ],
        },
        "velov": {
            **provider_health(state.velov, now),
            "stations": [
                {**asdict(station), "reported_at": station.reported_at.isoformat()}
                for station in stations
            ],
        },
    }
```

- [ ] **Step 4: Réécrire `/health`**

`src/eink_dashboard/api/routes/health.py` :

```python
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from eink_dashboard.api.deps import StoreDep
from eink_dashboard.services.dashboard import provider_health

router = APIRouter()


@router.get("/health")
async def health(request: Request, store: StoreDep) -> dict[str, Any]:
    now = datetime.now(request.app.state.tz)
    return {
        "status": "ok",
        "providers": {
            "tcl": provider_health(store.state.tcl, now),
            "velov": provider_health(store.state.velov, now),
        },
    }
```

- [ ] **Step 5: Écrire la route dashboard**

`src/eink_dashboard/api/routes/dashboard.py` :

```python
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request

from eink_dashboard.api.deps import StoreDep
from eink_dashboard.services.dashboard import dashboard_payload

router = APIRouter()


@router.get("/api/v1/dashboard")
async def dashboard(request: Request, store: StoreDep) -> dict[str, Any]:
    now = datetime.now(request.app.state.tz)
    return dashboard_payload(store.state, now)
```

- [ ] **Step 6: Enregistrer la route dans `main.py`**

Dans `src/eink_dashboard/main.py`, remplacer la ligne d'import des routes par :

```python
from eink_dashboard.api.routes import dashboard as dashboard_routes
from eink_dashboard.api.routes import health
```

et ajouter après `app.include_router(health.router)` :

```python
app.include_router(dashboard_routes.router)
```

- [ ] **Step 7: Lancer les tests et vérifier qu'ils passent**

Run: `pytest -v && mypy && ruff check .`
Expected: PASS

- [ ] **Step 8: Valider en conteneur**

Run: `docker compose up -d --build && sleep 90 && curl -s http://localhost:8000/api/v1/dashboard | head -c 600`
Expected: un JSON contenant les deux sources, avec des passages TCL et des stations Vélo'v réels.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: health detaille et endpoint dashboard JSON"
```

---

## Task 10: ViewModel purement textuel

**Files:**
- Create: `src/eink_dashboard/render/__init__.py`, `render/viewmodel.py`
- Test: `tests/unit/test_viewmodel.py`

**Interfaces:**
- Consumes: `DashboardState` (Task 3).
- Produces:
  - `DepartureLine(line: str, direction: str, waits: tuple[str, ...])`
  - `StopBlock(title: str, lines: tuple[DepartureLine, ...], stale: bool, note: str)`
  - `BikeBlock(label: str, bikes: int, docks: int, capacity: int, stale: bool, note: str)`
  - `DashboardView(as_of: str, stops: tuple[StopBlock, ...], bikes: tuple[BikeBlock, ...])` avec `content_hash() -> str`.
  - `build_view(state: DashboardState, now: datetime) -> DashboardView`
  - `format_wait(minutes: int) -> str`

**Règle de hachage.** `content_hash` couvre tous les champs sauf `as_of`. L'horodatage affiché n'est donc pas du contenu : à données identiques, l'image est identique et le panneau ne redessine pas. Conséquence assumée et documentée : quand rien ne change pendant une heure, l'heure affichée reste celle du dernier changement, ce qui se lit comme un indicateur de fraîcheur.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/unit/test_viewmodel.py` :

```python
from datetime import UTC, datetime, timedelta

from eink_dashboard.domain.bikes import BikeStation
from eink_dashboard.domain.transit import Departure, StopBoard
from eink_dashboard.render.viewmodel import build_view, format_wait
from eink_dashboard.state import Store

T0 = datetime(2026, 9, 2, 8, 0, tzinfo=UTC)


def store_with(tcl_status: str = "ok", velov_status: str = "ok") -> Store:
    store = Store()
    boards = (
        StopBoard(
            stop_name="Bellecour",
            departures=(
                Departure("A", "Vaulx-en-Velin La Soie", T0 + timedelta(minutes=2), True),
                Departure("A", "Vaulx-en-Velin La Soie", T0 + timedelta(minutes=9), True),
                Departure("D", "Gare de Venissieux", T0 + timedelta(minutes=4), True),
            ),
        ),
    )
    stations = (BikeStation("1032", "Pizay", 12, 8, 4, 7, 20, True, T0),)
    store.record_success("tcl", boards, T0)
    store.record_success("velov", stations, T0)
    if tcl_status != "ok":
        store.record_failure("tcl", "timeout", T0)
    if velov_status != "ok":
        store.record_failure("velov", "timeout", T0)
    return store


def test_format_wait_zero_is_a_quai() -> None:
    assert format_wait(0) == "à quai"


def test_format_wait_uses_minutes() -> None:
    assert format_wait(3) == "3 min"


def test_format_wait_caps_long_waits() -> None:
    assert format_wait(75) == "+60 min"


def test_departures_are_grouped_by_line_and_direction() -> None:
    view = build_view(store_with().state, T0)
    block = view.stops[0]

    assert block.title == "Bellecour"
    assert [line.line for line in block.lines] == ["A", "D"]
    assert block.lines[0].waits == ("2 min", "9 min")
    assert block.lines[1].waits == ("4 min",)


def test_bike_block_carries_counts_and_capacity() -> None:
    view = build_view(store_with().state, T0)

    assert view.bikes[0].label == "Pizay"
    assert view.bikes[0].bikes == 12
    assert view.bikes[0].docks == 7
    assert view.bikes[0].capacity == 20


def test_stale_provider_sets_the_flag_and_a_note() -> None:
    view = build_view(store_with(tcl_status="error").state, T0)

    assert view.stops[0].stale is True
    assert view.stops[0].note != ""
    assert view.bikes[0].stale is False


def test_empty_state_still_produces_a_view() -> None:
    view = build_view(Store().state, T0)

    assert view.stops == ()
    assert view.bikes == ()
    assert view.as_of != ""


def test_hash_is_stable_for_identical_content() -> None:
    first = build_view(store_with().state, T0)
    second = build_view(store_with().state, T0)

    assert first.content_hash() == second.content_hash()


def test_hash_ignores_the_as_of_label() -> None:
    first = build_view(store_with().state, T0)
    second = build_view(store_with().state, T0)
    shifted = type(second)(as_of="23:59", stops=second.stops, bikes=second.bikes)

    assert first.content_hash() == shifted.content_hash()


def test_hash_changes_when_a_wait_changes() -> None:
    first = build_view(store_with().state, T0)
    second = build_view(store_with().state, T0 + timedelta(minutes=1))

    assert first.content_hash() != second.content_hash()
```

- [ ] **Step 2: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_viewmodel.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.render'`

- [ ] **Step 3: Écrire le ViewModel**

`src/eink_dashboard/render/__init__.py` : fichier vide.

`src/eink_dashboard/render/viewmodel.py` :

```python
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from eink_dashboard.state import DashboardState

MAX_WAIT_MINUTES = 60
STALE_STATUSES = {"stale", "error", "unknown"}


def format_wait(minutes: int) -> str:
    if minutes <= 0:
        return "à quai"
    if minutes > MAX_WAIT_MINUTES:
        return f"+{MAX_WAIT_MINUTES} min"
    return f"{minutes} min"


@dataclass(frozen=True, slots=True)
class DepartureLine:
    line: str
    direction: str
    waits: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StopBlock:
    title: str
    lines: tuple[DepartureLine, ...]
    stale: bool
    note: str


@dataclass(frozen=True, slots=True)
class BikeBlock:
    label: str
    bikes: int
    docks: int
    capacity: int
    stale: bool
    note: str


@dataclass(frozen=True, slots=True)
class DashboardView:
    as_of: str
    stops: tuple[StopBlock, ...]
    bikes: tuple[BikeBlock, ...]

    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "stops": [
                    [
                        block.title,
                        block.stale,
                        block.note,
                        [[line.line, line.direction, list(line.waits)] for line in block.lines],
                    ]
                    for block in self.stops
                ],
                "bikes": [
                    [block.label, block.bikes, block.docks, block.capacity, block.stale, block.note]
                    for block in self.bikes
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _note(updated_at: datetime | None) -> str:
    return f"maj {updated_at:%H:%M}" if updated_at else "aucune donnée"


def build_view(state: DashboardState, now: datetime) -> DashboardView:
    tcl_stale = state.tcl.status in STALE_STATUSES
    velov_stale = state.velov.status in STALE_STATUSES

    stops: list[StopBlock] = []
    for board in state.tcl.data or ():
        grouped: dict[tuple[str, str], list[str]] = {}
        for departure in board.departures:
            grouped.setdefault((departure.line, departure.direction), []).append(
                format_wait(departure.minutes_until(now))
            )
        stops.append(
            StopBlock(
                title=board.stop_name,
                lines=tuple(
                    DepartureLine(line=line, direction=direction, waits=tuple(waits))
                    for (line, direction), waits in grouped.items()
                ),
                stale=tcl_stale,
                note=_note(state.tcl.updated_at) if tcl_stale else "",
            )
        )

    bikes = tuple(
        BikeBlock(
            label=station.label,
            bikes=station.bikes_available,
            docks=station.docks_available,
            capacity=station.capacity,
            stale=velov_stale,
            note=_note(state.velov.updated_at) if velov_stale else "",
        )
        for station in state.velov.data or ()
    )

    return DashboardView(as_of=f"{now:%H:%M}", stops=tuple(stops), bikes=bikes)
```

- [ ] **Step 4: Lancer les tests et vérifier qu'ils passent**

Run: `pytest tests/unit/test_viewmodel.py -v && mypy && ruff check .`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: viewmodel textuel pur avec hachage de contenu"
```

---

## Task 11: Rendu Pillow, `/preview.png` et service des BMP

**Files:**
- Create: `src/eink_dashboard/render/layout.py`, `render/images.py`
- Create: `src/eink_dashboard/render/fonts/DejaVuSans.ttf`, `render/fonts/DejaVuSans-Bold.ttf`
- Modify: `src/eink_dashboard/api/routes/dashboard.py`
- Test: `tests/unit/test_layout.py`

**Interfaces:**
- Consumes: `DashboardView` (Task 10).
- Produces:
  - `WIDTH = 800`, `HEIGHT = 480` dans `layout.py`.
  - `render(view: DashboardView) -> Image.Image`, image en mode `"1"`.
  - `to_bmp_bytes(image: Image.Image) -> bytes` et `to_png_bytes(image: Image.Image) -> bytes` dans `images.py`.
  - `ImageCache(max_entries: int = 4)` avec `get(name) -> bytes | None` et `put(name, payload) -> None`.
  - Route `GET /preview.png`.

- [ ] **Step 1: Installer les polices**

Run: `mkdir -p src/eink_dashboard/render/fonts && cp /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf /usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf src/eink_dashboard/render/fonts/`

Si les polices ne sont pas présentes sur la machine, les télécharger depuis le dépôt officiel DejaVu et les placer dans le même dossier. Elles sont sous licence libre et doivent être versionnées, parce que le conteneur `python:3.12-slim` n'embarque aucune police.

- [ ] **Step 2: Écrire les tests qui échouent**

`tests/unit/test_layout.py` :

```python
from eink_dashboard.render.images import ImageCache, to_bmp_bytes
from eink_dashboard.render.layout import HEIGHT, WIDTH, render
from eink_dashboard.render.viewmodel import BikeBlock, DashboardView, DepartureLine, StopBlock

VIEW = DashboardView(
    as_of="08:00",
    stops=(
        StopBlock(
            title="Bellecour",
            lines=(
                DepartureLine("A", "Vaulx-en-Velin La Soie", ("2 min", "9 min")),
                DepartureLine("D", "Gare de Venissieux", ("4 min",)),
            ),
            stale=False,
            note="",
        ),
    ),
    bikes=(BikeBlock("Pizay", 12, 7, 20, False, ""),),
)

EMPTY = DashboardView(as_of="08:00", stops=(), bikes=())


def test_render_produces_a_one_bit_image_of_the_right_size() -> None:
    image = render(VIEW)

    assert image.size == (WIDTH, HEIGHT)
    assert image.mode == "1"


def test_render_handles_an_empty_view() -> None:
    image = render(EMPTY)

    assert image.size == (WIDTH, HEIGHT)


def test_render_is_deterministic() -> None:
    assert to_bmp_bytes(render(VIEW)) == to_bmp_bytes(render(VIEW))


def test_different_content_produces_different_bytes() -> None:
    other = DashboardView(as_of="08:00", stops=VIEW.stops, bikes=(BikeBlock("Pizay", 3, 16, 20, False, ""),))

    assert to_bmp_bytes(render(VIEW)) != to_bmp_bytes(render(other))


def test_bmp_output_is_one_bit_per_pixel() -> None:
    payload = to_bmp_bytes(render(VIEW))

    assert payload[:2] == b"BM"
    assert int.from_bytes(payload[28:30], "little") == 1


def test_render_survives_a_very_long_direction_label() -> None:
    long_view = DashboardView(
        as_of="08:00",
        stops=(
            StopBlock(
                title="Un nom d arret particulierement long",
                lines=(DepartureLine("A", "Une destination vraiment tres longue" * 3, ("2 min",)),),
                stale=True,
                note="maj 07:12",
            ),
        ),
        bikes=(),
    )

    assert render(long_view).size == (WIDTH, HEIGHT)


def test_image_cache_evicts_the_oldest_entry() -> None:
    cache = ImageCache(max_entries=2)
    cache.put("a", b"1")
    cache.put("b", b"2")
    cache.put("c", b"3")

    assert cache.get("a") is None
    assert cache.get("c") == b"3"
```

- [ ] **Step 3: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_layout.py -v`
Expected: FAIL avec `ModuleNotFoundError: No module named 'eink_dashboard.render.layout'`

- [ ] **Step 4: Écrire le module images**

`src/eink_dashboard/render/images.py` :

```python
from collections import OrderedDict
from io import BytesIO

from PIL import Image


def to_bmp_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("1").save(buffer, format="BMP")
    return buffer.getvalue()


def to_png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("1").save(buffer, format="PNG")
    return buffer.getvalue()


class ImageCache:
    def __init__(self, max_entries: int = 4) -> None:
        self._entries: OrderedDict[str, bytes] = OrderedDict()
        self._max_entries = max_entries

    def get(self, name: str) -> bytes | None:
        payload = self._entries.get(name)
        if payload is not None:
            self._entries.move_to_end(name)
        return payload

    def put(self, name: str, payload: bytes) -> None:
        self._entries[name] = payload
        self._entries.move_to_end(name)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
```

- [ ] **Step 5: Écrire le layout**

`src/eink_dashboard/render/layout.py` :

```python
from importlib.resources import files
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from eink_dashboard.render.viewmodel import DashboardView

WIDTH = 800
HEIGHT = 480
MARGIN = 20
BLACK = 0
WHITE = 1

FONT_DIR = Path(str(files("eink_dashboard") / "render" / "fonts"))


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _truncate(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text + ellipsis


def render(view: DashboardView) -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    header = _font("DejaVuSans-Bold.ttf", 26)
    title = _font("DejaVuSans-Bold.ttf", 34)
    body = _font("DejaVuSans.ttf", 30)
    small = _font("DejaVuSans.ttf", 20)

    draw.text((MARGIN, MARGIN), "LYON", font=header, fill=BLACK)
    as_of_width = draw.textlength(view.as_of, font=small)
    draw.text((WIDTH - MARGIN - as_of_width, MARGIN + 6), view.as_of, font=small, fill=BLACK)

    y = MARGIN + 48
    draw.line([(MARGIN, y), (WIDTH - MARGIN, y)], fill=BLACK, width=2)
    y += 14

    for block in view.stops:
        if y > HEIGHT - 160:
            break
        heading = block.title if not block.stale else f"{block.title}   {block.note}"
        draw.text((MARGIN, y), _truncate(draw, heading, title, WIDTH - 2 * MARGIN), font=title, fill=BLACK)
        y += 42
        for line in block.lines:
            if y > HEIGHT - 150:
                break
            waits = "   ".join(line.waits)
            waits_width = draw.textlength(waits, font=body)
            draw.text((MARGIN + 10, y), line.line, font=body, fill=BLACK)
            label = _truncate(
                draw, line.direction, body, WIDTH - 2 * MARGIN - 60 - int(waits_width) - 30
            )
            draw.text((MARGIN + 60, y), label, font=body, fill=BLACK)
            draw.text((WIDTH - MARGIN - waits_width, y), waits, font=body, fill=BLACK)
            y += 38
        y += 10

    footer_top = HEIGHT - 120
    draw.line([(MARGIN, footer_top), (WIDTH - MARGIN, footer_top)], fill=BLACK, width=2)
    y = footer_top + 12
    draw.text((MARGIN, y), "VÉLO'V", font=header, fill=BLACK)
    y += 36

    for block in view.bikes:
        if y > HEIGHT - 30:
            break
        suffix = f"   {block.note}" if block.stale else ""
        text = f"{block.label}   {block.bikes} vélos   {block.docks} places   /{block.capacity}{suffix}"
        draw.text((MARGIN, y), _truncate(draw, text, body, WIDTH - 2 * MARGIN), font=body, fill=BLACK)
        y += 36

    return image
```

- [ ] **Step 6: Lancer les tests et vérifier qu'ils passent**

Run: `pytest tests/unit/test_layout.py -v && mypy && ruff check .`
Expected: PASS

- [ ] **Step 7: Ajouter `/preview.png`**

Dans `src/eink_dashboard/api/routes/dashboard.py`, ajouter en tête des imports :

```python
from fastapi.responses import Response

from eink_dashboard.render.images import to_png_bytes
from eink_dashboard.render.layout import render
from eink_dashboard.render.viewmodel import build_view
```

et à la fin du fichier :

```python
@router.get("/preview.png")
async def preview(request: Request, store: StoreDep) -> Response:
    now = datetime.now(request.app.state.tz)
    view = build_view(store.state, now)
    return Response(content=to_png_bytes(render(view)), media_type="image/png")
```

- [ ] **Step 8: Valider visuellement**

Run: `docker compose up -d --build && sleep 90`
Ouvrir `http://localhost:8000/preview.png` dans un navigateur, l'afficher à taille réelle 800x480.
Expected: les arrêts et les stations sont lisibles à environ deux mètres. Ajuster les tailles de police du Step 5 si ce n'est pas le cas, en gardant les tests verts.

Note : la spec évoquait trois mètres. Sur une dalle de 7,5 pouces, 480 pixels couvrent environ 99 mm, soit à peu près 4,8 pixels par millimètre. Une police de 30 pixels fait donc environ 6 mm de haut, ce qui se lit confortablement à deux mètres et péniblement à trois. Le critère retenu est deux mètres.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat: rendu Pillow 1 bit, cache image et apercu PNG"
```

---

## Task 12: Endpoints du protocole appareil

**Files:**
- Create: `src/eink_dashboard/api/routes/device.py`
- Modify: `src/eink_dashboard/main.py`
- Test: `tests/unit/test_device_api.py`

**Interfaces:**
- Consumes: `build_view`, `render`, `to_bmp_bytes`, `ImageCache`, `Settings`, `Store`.
- Produces:
  - `app.state.images: ImageCache` posé par le lifespan.
  - `GET /api/setup` renvoyant `{"status": 200, "api_key", "friendly_id", "image_url", "filename"}`.
  - `GET /api/display` renvoyant `{"status": 0, "image_url", "filename", "refresh_rate", "update_firmware": False, "firmware_url": None, "reset_firmware": False}`.
  - `POST /api/log` renvoyant 204.
  - `GET /image/{name}.bmp` renvoyant `image/bmp`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/unit/test_device_api.py` :

```python
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.testclient import TestClient

from eink_dashboard.api.routes import device
from eink_dashboard.core.config import Settings
from eink_dashboard.render.images import ImageCache
from eink_dashboard.state import Store

MAC = "AA:BB:CC:DD:EE:FF"
KEY = "cle-de-test"


def build_client() -> TestClient:
    app = FastAPI()
    app.include_router(device.router)
    app.state.store = Store()
    app.state.images = ImageCache()
    app.state.tz = ZoneInfo("Europe/Paris")
    app.state.settings = Settings(
        _env_file=None,
        device_mac=MAC,
        device_api_key=KEY,
        public_base_url="http://server:8000",
    )
    return TestClient(app)


def test_setup_returns_the_api_key_for_the_known_mac() -> None:
    response = build_client().get("/api/setup", headers={"ID": MAC})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == 200
    assert body["api_key"] == KEY
    assert body["image_url"].startswith("http://server:8000/image/")


def test_setup_is_case_insensitive_on_the_mac() -> None:
    response = build_client().get("/api/setup", headers={"ID": MAC.lower()})

    assert response.json()["api_key"] == KEY


def test_setup_rejects_an_unknown_mac() -> None:
    response = build_client().get("/api/setup", headers={"ID": "11:22:33:44:55:66"})

    assert response.status_code == 404


def test_display_returns_an_image_url_and_a_refresh_rate() -> None:
    response = build_client().get(
        "/api/display",
        headers={"ID": MAC, "Access-Token": KEY, "Battery-Voltage": "4.05", "RSSI": "-62"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"].endswith(".bmp")
    assert body["image_url"].endswith(body["filename"])
    assert body["refresh_rate"] > 0
    assert body["update_firmware"] is False


def test_display_rejects_a_bad_token() -> None:
    response = build_client().get(
        "/api/display", headers={"ID": MAC, "Access-Token": "mauvaise-cle"}
    )

    assert response.status_code == 401


def test_display_is_stable_when_the_state_does_not_change() -> None:
    client = build_client()
    first = client.get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()
    second = client.get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()

    assert first["filename"] == second["filename"]


def test_image_is_served_as_bmp() -> None:
    client = build_client()
    filename = client.get("/api/display", headers={"ID": MAC, "Access-Token": KEY}).json()["filename"]

    response = client.get(f"/image/{filename}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/bmp"
    assert response.content[:2] == b"BM"


def test_unknown_image_returns_404() -> None:
    response = build_client().get("/image/inconnue.bmp")

    assert response.status_code == 404


def test_log_endpoint_accepts_any_payload() -> None:
    response = build_client().post(
        "/api/log", headers={"ID": MAC, "Access-Token": KEY}, json={"log": {"message": "boum"}}
    )

    assert response.status_code == 204
```

- [ ] **Step 2: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_device_api.py -v`
Expected: FAIL avec `ImportError: cannot import name 'device'`

- [ ] **Step 3: Écrire les routes appareil**

`src/eink_dashboard/api/routes/device.py` :

```python
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Body, Header, HTTPException, Request, Response

from eink_dashboard.api.deps import SettingsDep, StoreDep
from eink_dashboard.render.images import ImageCache, to_bmp_bytes
from eink_dashboard.render.layout import render
from eink_dashboard.render.viewmodel import build_view

router = APIRouter()
log = structlog.get_logger()

DEFAULT_REFRESH_SECONDS = 300


def _check_mac(sent: str, expected: str) -> None:
    if not expected or sent.strip().casefold() != expected.strip().casefold():
        raise HTTPException(status_code=404, detail="appareil inconnu")


def _check_token(sent: str, expected: str) -> None:
    if not expected or sent != expected:
        raise HTTPException(status_code=401, detail="jeton invalide")


def _current_image(request: Request, store: StoreDep) -> str:
    now = datetime.now(request.app.state.tz)
    view = build_view(store.state, now)
    filename = f"dash-{view.content_hash()}.bmp"
    images: ImageCache = request.app.state.images
    if images.get(filename) is None:
        images.put(filename, to_bmp_bytes(render(view)))
    return filename


@router.get("/api/setup")
async def setup(
    request: Request,
    store: StoreDep,
    settings: SettingsDep,
    id: Annotated[str, Header()],
) -> dict[str, Any]:
    _check_mac(id, settings.device_mac)
    filename = _current_image(request, store)
    log.info("device.setup", mac=id)
    return {
        "status": 200,
        "api_key": settings.device_api_key,
        "friendly_id": "LYON01",
        "image_url": f"{settings.public_base_url.rstrip('/')}/image/{filename}",
        "filename": filename,
    }


@router.get("/api/display")
async def display(
    request: Request,
    store: StoreDep,
    settings: SettingsDep,
    id: Annotated[str, Header()],
    access_token: Annotated[str, Header()] = "",
    battery_voltage: Annotated[str | None, Header()] = None,
    fw_version: Annotated[str | None, Header()] = None,
    rssi: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    _check_mac(id, settings.device_mac)
    _check_token(access_token, settings.device_api_key)
    filename = _current_image(request, store)
    now = datetime.now(request.app.state.tz)
    log.info("device.display", mac=id, battery=battery_voltage, rssi=rssi, fw=fw_version)
    return {
        "status": 0,
        "image_url": f"{settings.public_base_url.rstrip('/')}/image/{filename}",
        "filename": filename,
        "refresh_rate": DEFAULT_REFRESH_SECONDS,
        "update_firmware": False,
        "firmware_url": None,
        "reset_firmware": False,
    }


@router.post("/api/log", status_code=204)
async def device_log(
    id: Annotated[str, Header()],
    payload: Annotated[dict[str, Any], Body()],
) -> Response:
    log.warning("device.log", mac=id, payload=payload)
    return Response(status_code=204)


@router.get("/image/{name}")
async def image(request: Request, name: str) -> Response:
    images: ImageCache = request.app.state.images
    payload = images.get(name)
    if payload is None:
        raise HTTPException(status_code=404, detail="image inconnue")
    return Response(content=payload, media_type="image/bmp")
```

L'argument `now` calculé dans `display` sert au journal et sera utilisé à la Task 13. S'il déclenche un avertissement de variable inutilisée à `ruff`, le supprimer ici et le rétablir à la Task 13.

- [ ] **Step 4: Câbler le cache d'images et les routes**

Dans `src/eink_dashboard/main.py`, ajouter l'import :

```python
from eink_dashboard.api.routes import device as device_routes
from eink_dashboard.render.images import ImageCache
```

Dans le lifespan, après `app.state.tz = tz` :

```python
    app.state.images = ImageCache()
```

Et après `app.include_router(dashboard_routes.router)` :

```python
app.include_router(device_routes.router)
```

- [ ] **Step 5: Lancer les tests et vérifier qu'ils passent**

Run: `pytest -v && mypy && ruff check .`
Expected: PASS

- [ ] **Step 6: Vérifier le contrat contre le vrai firmware**

Renseigner `DEVICE_MAC` et `DEVICE_API_KEY` dans `.env`, mettre `PUBLIC_BASE_URL` à l'adresse locale du serveur telle que le panneau la voit, puis `docker compose up -d --build`.

Flasher ou configurer le firmware TRMNL sur le XIAO et le pointer vers ce serveur. Deux inconnues à lever ici, dans cet ordre :

1. L'URL de serveur personnalisée est-elle saisissable dans le portail captif Wi-Fi, ou faut-il recompiler le firmware avec `API_BASE_URL` ? Consulter `usetrmnl/trmnl-firmware` et noter la réponse dans `docs/tcl-api-notes.md` sous une section « firmware ».
2. Le champ `status` attendu par `/api/display` vaut-il bien `0` ? Si le panneau boucle sur un écran d'erreur, consulter les requêtes reçues dans les logs du conteneur (`docker compose logs -f`) et essayer `"status": 200`.

Expected: le panneau affiche le dashboard. C'est le critère de validation de la phase appareil.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: endpoints du protocole appareil TRMNL et service des images BMP"
```

---

## Task 13: Cadence adaptative

**Files:**
- Modify: `src/eink_dashboard/services/dashboard.py`
- Modify: `src/eink_dashboard/api/routes/device.py`
- Test: `tests/unit/test_refresh_rate.py`
- Modify: `tests/unit/test_device_api.py`

**Interfaces:**
- Consumes: `datetime`.
- Produces: `refresh_rate_for(now: datetime) -> int` dans `services/dashboard.py`, avec les constantes `PEAK_REFRESH = 120`, `DAY_REFRESH = 300`, `NIGHT_REFRESH = 3600`.

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/unit/test_refresh_rate.py` :

```python
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from eink_dashboard.services.dashboard import (
    DAY_REFRESH,
    NIGHT_REFRESH,
    PEAK_REFRESH,
    refresh_rate_for,
)

PARIS = ZoneInfo("Europe/Paris")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 2, hour, minute, tzinfo=PARIS)


@pytest.mark.parametrize("hour,minute", [(7, 0), (8, 30), (9, 29), (17, 0), (19, 29)])
def test_peak_hours_use_the_short_interval(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute)) == PEAK_REFRESH


@pytest.mark.parametrize("hour,minute", [(9, 30), (12, 0), (16, 59), (19, 30), (22, 59)])
def test_daytime_uses_the_medium_interval(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute)) == DAY_REFRESH


@pytest.mark.parametrize("hour,minute", [(23, 0), (2, 0), (5, 59)])
def test_night_uses_the_long_interval(hour: int, minute: int) -> None:
    assert refresh_rate_for(at(hour, minute)) == NIGHT_REFRESH


def test_six_in_the_morning_is_daytime() -> None:
    assert refresh_rate_for(at(6, 0)) == DAY_REFRESH
```

- [ ] **Step 2: Lancer les tests et vérifier qu'ils échouent**

Run: `pytest tests/unit/test_refresh_rate.py -v`
Expected: FAIL avec `ImportError: cannot import name 'refresh_rate_for'`

- [ ] **Step 3: Écrire la fonction**

Ajouter à la fin de `src/eink_dashboard/services/dashboard.py` :

```python
PEAK_REFRESH = 120
DAY_REFRESH = 300
NIGHT_REFRESH = 3600

_MORNING_PEAK = (7 * 60, 9 * 60 + 30)
_EVENING_PEAK = (17 * 60, 19 * 60 + 30)
_NIGHT_START = 23 * 60
_NIGHT_END = 6 * 60


def refresh_rate_for(now: datetime) -> int:
    minutes = now.hour * 60 + now.minute
    if minutes >= _NIGHT_START or minutes < _NIGHT_END:
        return NIGHT_REFRESH
    for start, end in (_MORNING_PEAK, _EVENING_PEAK):
        if start <= minutes < end:
            return PEAK_REFRESH
    return DAY_REFRESH
```

- [ ] **Step 4: Brancher la fonction sur `/api/display`**

Dans `src/eink_dashboard/api/routes/device.py`, remplacer l'import et la constante :

```python
from eink_dashboard.services.dashboard import refresh_rate_for
```

Supprimer `DEFAULT_REFRESH_SECONDS` et remplacer la ligne du dictionnaire de réponse par :

```python
        "refresh_rate": refresh_rate_for(now),
```

- [ ] **Step 5: Ajouter le test d'intégration de la cadence**

Ajouter à `tests/unit/test_device_api.py` :

```python
def test_display_refresh_rate_matches_the_schedule() -> None:
    from eink_dashboard.services.dashboard import DAY_REFRESH, NIGHT_REFRESH, PEAK_REFRESH

    body = build_client().get(
        "/api/display", headers={"ID": MAC, "Access-Token": KEY}
    ).json()

    assert body["refresh_rate"] in {PEAK_REFRESH, DAY_REFRESH, NIGHT_REFRESH}
```

- [ ] **Step 6: Lancer toute la suite**

Run: `pytest -v && mypy && ruff check . && ruff format --check .`
Expected: PASS, aucune erreur

- [ ] **Step 7: Valider l'absence de clignotement**

Run: `docker compose up -d --build`

Interroger deux fois `/api/display` à quelques secondes d'intervalle avec les bons en-têtes :

```bash
curl -s -H "ID: $DEVICE_MAC" -H "Access-Token: $DEVICE_API_KEY" http://localhost:8000/api/display
```

Expected: si aucun temps d'attente n'a changé entre les deux appels, `filename` est identique. Observer ensuite le panneau réel pendant une demi-heure de nuit : il ne doit pas redessiner tant que les données ne bougent pas. Si le panneau redessine malgré un `filename` identique, c'est que le firmware ne compare pas ce champ ; noter le constat dans `docs/tcl-api-notes.md` et laisser le mécanisme en place, il reste correct et sans coût.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat: cadence de reveil adaptative selon l heure"
```

---

## Auto-revue du plan

**Couverture de la spec.** Chaque section de la spec est portée par au moins une tâche : sources vérifiées (Tasks 4 à 7), protocole TRMNL (Task 12), absence de base de données (aucune tâche n'en introduit), configuration double (Task 2), flux de données (Tasks 5, 7, 8, 12), gestion des erreurs (Tasks 5, 7, 8), observabilité (Task 9), cadence (Tasks 10 et 13), stack (Task 1), tests (toutes), Docker (Task 1).

**Écarts assumés par rapport à la spec, à corriger dans la spec après exécution.**

1. Le critère de lisibilité passe de trois mètres à deux mètres, calcul de densité de pixels à l'appui (Task 11, Step 8).
2. La spec ne précisait pas que `TclClient` isole les arrêts entre eux. Le plan le fait : un arrêt en échec devient un tableau vide, tous les arrêts en échec font lever et basculer le fournisseur en `error` (Task 7).
3. La spec ne précisait pas le sort de l'horodatage affiché. Le plan l'exclut du hachage et documente la conséquence (Task 10).

**Point non vérifiable à l'avance.** Les noms de champs de `tcl_sytral.tclpassagearret` sont derrière authentification. La Task 6 les capture, les documente, et les enferme dans la constante `TCL_FIELDS`, gardée par un test qui échoue si la table diverge de la réalité. C'est le seul endroit de la base de code qui dépend du format brut de TCL.

**Deux inconnues firmware** sont levées à la Task 12, Step 6 : configuration d'une URL de serveur personnalisée, et valeur attendue du champ `status` sur `/api/display`. Les deux ont un plan de repli explicite.
