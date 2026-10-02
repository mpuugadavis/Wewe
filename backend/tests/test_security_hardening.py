from fastapi.testclient import TestClient


def test_security_headers_are_present(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert response.headers["X-Request-ID"]


def test_untrusted_host_is_rejected(client: TestClient) -> None:
    response = client.get("/health/live", headers={"Host": "attacker.example"})
    assert response.status_code == 400


def test_oversized_request_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        headers={"Content-Length": "2000001"},
        content=b"",
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_auth_responses_are_not_cacheable(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": "missing@example.com", "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.headers["Cache-Control"] == "no-store"
