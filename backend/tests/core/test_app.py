import socket

import pytest
from pydantic import ValidationError

from app.contracts import CONTRACTS_VERSION
from app.db import discover_model_modules
from app.main import discover_routers
from app.settings import AppEnv, LLMMode, Settings

STRONG = "x" * 40


def test_health_reports_contract_version_and_synthetic_banner(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["contracts_version"] == CONTRACTS_VERSION
    assert body["data_mode_banner"] == "synthetic"
    assert body["config"]["database"] == "sqlite"


def test_health_hides_banner_when_demo_mode_is_off(settings):
    from fastapi.testclient import TestClient

    from app.main import create_app

    quiet = settings.model_copy(update={"demo_mode": False})
    with TestClient(create_app(quiet)) as client:
        assert client.get("/api/health").json()["data_mode_banner"] is None


def test_router_discovery_mounts_health_and_skips_private_modules():
    names = [name for name, _ in discover_routers()]
    assert "health" in names
    assert all(not name.startswith("_") for name in names)


def test_model_discovery_only_returns_models_modules():
    assert all(name.endswith(".models") for name in discover_model_modules())


def test_settings_defaults_are_safe_for_development():
    settings = Settings(_env_file=None)
    assert settings.app_env is AppEnv.development
    assert settings.llm_mode is LLMMode.fixtures
    assert settings.is_sqlite


def test_cors_origins_accept_comma_separated_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://hishab.quadbits.net, http://localhost:5173")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["https://hishab.quadbits.net", "http://localhost:5173"]


PG = "postgresql+psycopg://hishab:pw@db:5432/hishab"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"database_url": "sqlite:///./x.db"}, "PostgreSQL"),
        ({"secret_key": "change-me"}, "secret_key"),
        ({"vault_key": "short"}, "vault_key"),
        ({"demo_mode": True}, "demo_mode"),
        ({"llm_mode": "fixtures"}, "fixtures"),
    ],
)
def test_production_refuses_unsafe_configuration(overrides, message):
    base = {"app_env": "production", "secret_key": STRONG, "vault_key": STRONG,
            "demo_mode": False, "llm_mode": "live", "database_url": PG}
    base.update(overrides)
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **base)


def test_production_accepts_safe_configuration():
    settings = Settings(_env_file=None, app_env="production", secret_key=STRONG,
                        vault_key=STRONG, demo_mode=False, llm_mode="live", database_url=PG)
    assert settings.app_env is AppEnv.production


def test_hosted_demo_allows_synthetic_data_but_still_needs_real_secrets():
    demo = Settings(_env_file=None, app_env="demo", secret_key=STRONG, vault_key=STRONG,
                    demo_mode=True, llm_mode="fixtures", database_url=PG)
    assert demo.demo_mode
    with pytest.raises(ValidationError, match="secret_key"):
        Settings(_env_file=None, app_env="demo", vault_key=STRONG, database_url=PG)


def test_public_view_never_contains_secret_values():
    secret = "gsk_live_secret_value_123"
    settings = Settings(_env_file=None, groq_api_key=secret, secret_key=STRONG)
    view = settings.public_view()
    assert view["groq_key_set"] is True
    assert secret not in repr(view) and STRONG not in repr(view)
    assert secret not in repr(settings)


def test_tests_cannot_reach_the_network():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="must not use the network"):
            sock.connect(("93.184.216.34", 443))
    finally:
        sock.close()


@pytest.mark.parametrize(("app_env", "served"), [("development", True), ("test", True),
                                                 ("demo", False), ("production", False)])
def test_interactive_docs_are_served_only_where_developers_run_the_app(settings, app_env, served):
    from fastapi.testclient import TestClient

    from app.main import create_app

    # Only app_env matters here; the rest stays the in-memory test configuration.
    env = settings.model_copy(update={"app_env": AppEnv(app_env)})
    with TestClient(create_app(env)) as client:
        codes = {path: client.get(path).status_code
                 for path in ("/api/docs", "/api/redoc", "/api/openapi.json")}
    assert codes == dict.fromkeys(codes, 200 if served else 404)

