from cs2screenshot.models import InspectData, StickerData
from cs2screenshot import renderer
from cs2screenshot.renderer import build_item_render_html


def test_build_item_render_html_contains_payload():
    data = InspectData(
        defindex=60,
        paintindex=1017,
        paintseed=130,
        paintwear=0.03,
        stattrak=None,
        stattrak_count=None,
        souvenir=None,
        rarity=5,
        quality=4,
        item_name="M4A1-S",
        paint_name="Printstream",
        item_image="https://example.com/skin.png",
        stickers=[
            StickerData(
                slot=0,
                sticker_id=5007,
                wear=0.1,
                rotation=15.0,
                offset_x=0.2,
                offset_y=0.1,
                image="https://example.com/sticker.png",
                name="Sticker | Example",
            )
        ],
    )

    html = build_item_render_html(data)

    assert "https://example.com/skin.png" in html
    assert "https://example.com/sticker.png" in html
    assert "cs2inspects" in html
    assert "Download PNG" in html


def test_inline_images_replaces_urls(monkeypatch):
    class _Resp:
        headers = {"content-type": "image/png"}
        content = b"fakepng"

        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, _url):
            return _Resp()

    monkeypatch.setattr(renderer.httpx, "Client", _Client)

    data = InspectData(
        defindex=60,
        paintindex=1017,
        paintseed=130,
        paintwear=0.03,
        stattrak=None,
        stattrak_count=None,
        souvenir=None,
        rarity=5,
        quality=4,
        item_image="https://example.com/skin.png",
        stickers=[StickerData(slot=0, sticker_id=1, image="https://example.com/sticker.png")],
    )
    html = build_item_render_html(data, inline_images=True)
    assert "data:image/png;base64," in html


def test_html_contains_coordinate_formula():
    """The JS must include the cs2inspects coordinate formula."""
    data = InspectData(
        defindex=7,
        paintindex=282,
        paintseed=661,
        paintwear=0.15,
        stattrak=None,
        stattrak_count=None,
        souvenir=None,
        rarity=4,
        quality=4,
        stickers=[],
    )
    html = build_item_render_html(data)
    # Must reference the stickerFloatValue divisor used by cs2inspects
    assert "stickerFloatValue" in html
    assert "computeStickerPosition" in html
    # Must use a 1920x1080 scene
    assert "1920" in html
    assert "1080" in html
