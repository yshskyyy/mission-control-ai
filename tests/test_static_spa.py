import re


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
