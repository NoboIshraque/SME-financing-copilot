"""Static checks of the deployment files (WP-18). The CI `stack` job boots them for real."""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((REPO / "infra/docker-compose.yml").read_text(encoding="utf-8"))
CADDY = (REPO / "infra/Caddyfile").read_text(encoding="utf-8")
DEPLOY = (REPO / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
ENV_EXAMPLE = (REPO / "infra/.env.example").read_text(encoding="utf-8")
SERVICES = COMPOSE["services"]


def test_the_stack_has_db_api_worker_and_web():
    assert set(SERVICES) == {"db", "api", "worker", "web"}


@pytest.mark.parametrize("name", sorted(SERVICES))
def test_every_service_restarts_and_reports_health(name):
    service = SERVICES[name]
    assert service["restart"] == "unless-stopped"
    has_check = "healthcheck" in service or name in ("api", "web")  # api: HEALTHCHECK in image
    assert has_check


def test_only_the_web_proxy_publishes_ports():
    published = {name for name, s in SERVICES.items() if s.get("ports")}
    assert published == {"web"}
    assert {p.split(":")[0] for p in SERVICES["web"]["ports"]} == {"80", "443"}


def test_database_data_survives_redeploys():
    assert "pgdata:/var/lib/postgresql/data" in SERVICES["db"]["volumes"]
    assert COMPOSE["name"] == "hishab"  # fixed project name keeps the same volumes


def test_compose_contains_no_literal_secrets():
    text = (REPO / "infra/docker-compose.yml").read_text(encoding="utf-8")
    for key in ("PASSWORD", "SECRET_KEY", "VAULT_KEY", "API_KEY", "PRIVATE_KEY"):
        for line in text.splitlines():
            if key in line and ":" in line and not line.strip().startswith("#"):
                value = line.split(":", 1)[1]
                assert "${" in value or "@db" in value, line


def test_every_required_variable_is_in_the_env_template():
    text = (REPO / "infra/docker-compose.yml").read_text(encoding="utf-8")
    required = set(re.findall(r"\$\{([A-Z_]+):\?", text))
    template = {line.split("=")[0] for line in ENV_EXAMPLE.splitlines() if "=" in line}
    assert required <= template


def test_caddy_sends_strict_security_headers():
    csp = re.search(r'Content-Security-Policy "([^"]+)"', CADDY).group(1)
    assert "default-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-eval" not in csp and "script-src 'self';" in csp
    assert "http" not in csp  # no third-party origins (China reachability)
    for header in ("Strict-Transport-Security", "X-Content-Type-Options", "X-Frame-Options"):
        assert header in CADDY


def test_caddy_proxies_api_and_falls_back_to_the_spa():
    assert "reverse_proxy api:8000" in CADDY
    assert "try_files {path} /index.html" in CADDY


def test_images_run_as_non_root_and_web_is_multi_stage():
    api = (REPO / "infra/Dockerfile.api").read_text(encoding="utf-8")
    web = (REPO / "infra/Dockerfile.web").read_text(encoding="utf-8")
    assert re.search(r"^USER hishab$", api, re.M)
    assert web.count("FROM ") == 2


def test_docker_context_excludes_secrets_and_git():
    ignore = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "**/.env" in ignore and ".git" in ignore


def test_deploy_uses_only_the_documented_secrets_and_rolls_back():
    used = set(re.findall(r"secrets\.([A-Z_]+)", DEPLOY))
    assert used == {"DEPLOY_HOST", "DEPLOY_USER", "DEPLOY_SSH_KEY", "DEPLOY_DOMAIN",
                    "DEPLOY_KNOWN_HOSTS"}  # the last is optional: it pins the host key (R15)
    assert "Roll back" in DEPLOY and "conclusion == 'success'" in DEPLOY
