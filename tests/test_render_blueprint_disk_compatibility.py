from pathlib import Path


def test_disk_backed_render_blueprint_omits_unsupported_shutdown_delay() -> None:
    source = Path("render.yaml").read_text(encoding="utf-8")

    assert "disk:" in source
    assert "mountPath: /app/database" in source
    assert "maxShutdownDelaySeconds" not in source
