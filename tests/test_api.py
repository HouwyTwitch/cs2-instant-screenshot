"""Smoke tests for the FastAPI backend (cs2screenshot.api)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from cs2screenshot.api import app

client = TestClient(app)

# Reference modern inspect link (AK-47, paintindex 1352, seed 666, BS, 4 stickers)
_REF_HEX = (
    "00180720C80A280638A4E1F5FB03409A0562040800104C62040801104C62040802"
    "104C62040803104C6D4F5E30"
)
_REF_LINK = (
    "steam://rungame/730/76561202255233023/+csgo_econ_action_preview " + _REF_HEX
)


def test_health() -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_decode_modern_link() -> None:
    r = client.post("/api/decode", json={"inspect_link": _REF_LINK})
    assert r.status_code == 200
    data = r.json()
    assert data["defindex"] == 7
    assert data["paintindex"] == 1352
    assert data["paintseed"] == 666
    assert data["wear_tier"] == "BS"
    assert len(data["stickers"]) == 4


def test_decode_invalid_link_returns_400() -> None:
    r = client.post("/api/decode", json={"inspect_link": "not-a-link"})
    assert r.status_code == 400


def test_paintkit_missing_returns_404() -> None:
    # 404 only when no paint kit exists for the index; the extracted dataset may
    # or may not be present, so use an index that is never a real paint kit.
    r = client.get("/api/paintkit/99999999")
    assert r.status_code == 404


def test_proxy_rejects_disallowed_host() -> None:
    r = client.get("/api/proxy", params={"url": "https://evil.example.com/a.png"})
    assert r.status_code == 400
