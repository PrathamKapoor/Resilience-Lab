"""Mechanical checks for files that define the dashboard deployment image."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_image_includes_alembic_configuration_at_its_workdir() -> None:
    """The documented Compose migration command needs Alembic's config in /app."""
    dockerfile = (ROOT / "deployment" / "docker" / "Dockerfile").read_text(encoding="utf-8")

    assert "WORKDIR /app" in dockerfile
    assert "COPY pyproject.toml README.md LICENSE alembic.ini ./" in dockerfile


def test_compose_example_uses_the_installed_psycopg3_sqlalchemy_driver() -> None:
    """The URL users copy must select psycopg3 rather than rely on a fallback."""
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "RESILIENCELAB_DATABASE_URL=postgresql+psycopg://" in example
