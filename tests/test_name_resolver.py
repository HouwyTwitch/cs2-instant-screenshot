from cs2screenshot.name_resolver import NameResolver


def _reset():
    NameResolver._skins_loaded = False
    NameResolver._stickers_loaded = False
    NameResolver._keychains_loaded = False
    NameResolver._skin_by_pair = {}
    NameResolver._sticker_names = {}
    NameResolver._keychain_names = {}


def test_parses_bymykel_like_structures(monkeypatch):
    _reset()

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


def test_only_loads_on_miss(monkeypatch):
    _reset()
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
