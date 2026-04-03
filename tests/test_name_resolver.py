from cs2screenshot.name_resolver import NameResolver


def _reset():
    NameResolver._skins_loaded = False
    NameResolver._stickers_loaded = False
    NameResolver._keychains_loaded = False
    NameResolver._skin_by_pair = {}
    NameResolver._sticker_names = {}
    NameResolver._keychain_names = {}
    NameResolver._state_loaded = False
    NameResolver._last_failed_at = 0.0


def test_parses_bymykel_like_structures(monkeypatch, tmp_path):
    _reset()
    monkeypatch.setattr(NameResolver, "_STATE_PATH", tmp_path / "resolver.json")

    skins = [{
        "weapon": {"weapon_id": 60, "name": "M4A1-S"},
        "pattern": {"name": "Printstream"},
        "paint_index": "1017",
    }]
    stickers = [{"def_index": "5007", "name": "Movistar Riders (Holo) | Stockholm 2021"}]
    keychains = [{"def_index": "12", "name": "Charm | Lil' Ava"}]

    def fake_fetch(_client, url):
        if url.endswith('/skins.json'):
            return skins
        if url.endswith('/stickers.json'):
            return stickers
        if url.endswith('/keychains.json'):
            return keychains
        return []

    monkeypatch.setattr(NameResolver, "_fetch_json", staticmethod(fake_fetch))

    s = NameResolver.resolve_skin(60, 1017)
    assert s.item_name == "M4A1-S"
    assert s.paint_name == "Printstream"
    assert NameResolver.resolve_sticker_name(5007) == "Movistar Riders (Holo) | Stockholm 2021"
    assert NameResolver.resolve_keychain_name(12) == "Charm | Lil' Ava"


def test_only_loads_on_miss(monkeypatch, tmp_path):
    _reset()
    monkeypatch.setattr(NameResolver, "_STATE_PATH", tmp_path / "resolver.json")
    NameResolver._skin_by_pair[(7, 282)] = ("AK-47", "Redline")

    calls = {"skins": 0}

    def fake_fetch(_client, url):
        if url.endswith('/skins.json'):
            calls["skins"] += 1
        return []

    monkeypatch.setattr(NameResolver, "_fetch_json", staticmethod(fake_fetch))

    # Cache hit: no fetch
    resolved = NameResolver.resolve_skin(7, 282)
    assert resolved.item_name == "AK-47"
    assert calls["skins"] == 0

    # Cache miss: exactly one fetch
    NameResolver.resolve_skin(9999, 9999)
    assert calls["skins"] == 1


def test_failed_network_is_backed_off(monkeypatch, tmp_path):
    _reset()
    monkeypatch.setattr(NameResolver, "_STATE_PATH", tmp_path / "resolver.json")
    monkeypatch.setattr(NameResolver, "_FAIL_RETRY_SECONDS", 999999)
    NameResolver._skin_by_pair[(7, 282)] = ("AK-47", "Redline")

    calls = {"skins": 0}

    def fake_fetch(_client, _url):
        calls["skins"] += 1
        raise RuntimeError("network down")

    monkeypatch.setattr(NameResolver, "_fetch_json", staticmethod(fake_fetch))

    NameResolver.resolve_skin(60, 1017)
    assert calls["skins"] == 1

    # second miss should skip network due cooldown
    NameResolver._skins_loaded = False
    NameResolver.resolve_skin(61, 1018)
    assert calls["skins"] == 1


def test_persistent_cache_is_reused(monkeypatch, tmp_path):
    _reset()
    state_path = tmp_path / "resolver.json"
    monkeypatch.setattr(NameResolver, "_STATE_PATH", state_path)
    monkeypatch.setattr(NameResolver, "_skins_loaded", True)
    monkeypatch.setattr(NameResolver, "_stickers_loaded", True)
    monkeypatch.setattr(NameResolver, "_keychains_loaded", True)
    NameResolver._skin_by_pair = {(60, 1017): ("M4A1-S", "Printstream")}
    NameResolver._sticker_names = {5007: "Sticker | Example"}
    NameResolver._keychain_names = {1: "Charm | Lil' Ava"}
    NameResolver._save_state()

    # New process simulation: empty in-memory, reload from disk state
    _reset()
    monkeypatch.setattr(NameResolver, "_STATE_PATH", state_path)

    def fake_fetch(_client, _url):
        raise AssertionError("network fetch should not happen when cache exists")

    monkeypatch.setattr(NameResolver, "_fetch_json", staticmethod(fake_fetch))

    assert NameResolver.resolve_skin(60, 1017).item_name == "M4A1-S"
    assert NameResolver.resolve_sticker_name(5007) == "Sticker | Example"
    assert NameResolver.resolve_keychain_name(1) == "Charm | Lil' Ava"
