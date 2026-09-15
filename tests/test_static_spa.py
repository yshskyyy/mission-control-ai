import re
import os
import subprocess
import sys


def test_index_assets_and_spa_fallback(client):
    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")

    urls = re.findall(r'(?:src|href)="(/assets/[^"]+)"', index.text)
    assert any(url.endswith(".js") for url in urls)
    assert any(url.endswith(".css") for url in urls)
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        expected = "javascript" if url.endswith(".js") else "text/css"
        assert expected in response.headers["content-type"]

    fallback = client.get("/learning/session/example")
    assert fallback.status_code == 200
    assert fallback.text == index.text


def test_spa_fallback_does_not_capture_reserved_routes(client):
    assert client.get("/health").status_code == 200
    assert client.get("/docs").status_code == 200
    assert client.get("/metrics/").status_code == 200
    assert client.get("/api/not-a-real-route").status_code == 404
    assert client.get("/assets/not-a-real-file.js").status_code == 404


def test_main_imports_without_frontend_build_and_backend_routes_work(tmp_path):
    environment = os.environ.copy()
    environment.update({
        "STATIC_DIR": str(tmp_path / "missing-static"),
        "DATABASE_PATH": str(tmp_path / "fresh-checkout.db"),
        "ENVIRONMENT": "test",
    })
    code = """
from fastapi.testclient import TestClient
from app.main import app
with TestClient(app) as client:
    assert client.get('/health').status_code == 200
    assert client.get('/docs').status_code == 200
    assert client.get('/api/not-a-real-route').status_code == 404
    response = client.get('/')
    assert response.status_code == 503
    assert 'Frontend build is unavailable' in response.text
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=os.getcwd(), env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_production_startup_rejects_missing_frontend_build(tmp_path):
    environment = os.environ.copy()
    environment.update({
        "STATIC_DIR": str(tmp_path / "missing-static"),
        "DATABASE_PATH": str(tmp_path / "production-check.db"),
        "ENVIRONMENT": "production",
    })
    code = """
from fastapi.testclient import TestClient
from app.main import app
try:
    with TestClient(app):
        pass
except RuntimeError as exc:
    assert 'Frontend build is missing' in str(exc)
else:
    raise AssertionError('production startup unexpectedly accepted a missing frontend build')
"""
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=os.getcwd(), env=environment,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
