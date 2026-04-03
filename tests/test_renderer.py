from cs2screenshot.models import InspectData, StickerData
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
    assert "Approximate preview" in html
    assert "canvas" in html
    assert "Download PNG" in html
