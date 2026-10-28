"""The deploy files (docs/DEPLOY.md): the image holds what the app reads at run time and no secrets or data, and
the database lands on the host's mounted folder."""

import subprocess
from pathlib import Path

from offer_engine.config import DEFAULT_DB_PATH

ROOT = Path(__file__).resolve().parents[1]


def dockerignore() -> set[str]:
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_secrets_and_data_stay_out_of_the_image():
    ignored = dockerignore()
    assert {".env", ".env.*", "data/"} <= ignored


def test_files_the_app_reads_at_run_time_go_into_the_image():
    # The live page reads GLOSSARY.md (T39), the Offer Bot the Persona Cards, replay mode the recordings (T36).
    needed = ["GLOSSARY.md", "personas/", "demo/", "console/", "src/", "uv.lock", ".env.example"]
    ignored = dockerignore()
    assert not [path for path in needed if path in ignored or path.rstrip("/") in ignored]
    assert "!.env.example" in ignored


def test_the_database_lives_on_the_mounted_folder():
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "compose.yaml").read_text()
    assert "WORKDIR /app" in dockerfile
    assert DEFAULT_DB_PATH.parts[0] == "data"
    assert "./data:/app/data" in compose


def test_the_image_starts_every_process():
    assert 'CMD ["uv", "run", "--no-sync", "offer-engine", "start"]' in (ROOT / "Dockerfile").read_text()


def test_no_port_is_published_on_the_host():
    # The Cloudflare Tunnel reaches the app over compose's network; the instance opens only SSH.
    assert "ports:" not in (ROOT / "compose.yaml").read_text()


def test_the_deploy_wizard_parses_and_its_env_file_stays_out_of_git_and_the_image():
    # scripts/deploy-wizard.sh builds the instance's .env on the laptop as .env.poe, full of secrets.
    wizard = ROOT / "scripts" / "deploy-wizard.sh"
    assert subprocess.run(["bash", "-n", str(wizard)]).returncode == 0
    assert "ENV_FILE=.env.poe" in wizard.read_text()
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env.poe"], cwd=ROOT)
    assert ignored.returncode == 0
    assert ".env.*" in dockerignore()
