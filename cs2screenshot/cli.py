"""CLI entry point for cs2screenshot."""
from __future__ import annotations

import json
from pathlib import Path

import typer
from rich import print as rprint
from rich.table import Table

from .decoder import decode
from .renderer import build_item_render_html

app = typer.Typer(
    name="cs2screenshot",
    help="CS2 item inspect link decoder and screenshot tool.",
    no_args_is_help=True,
)


@app.callback()
def _root() -> None:
    """CS2 item inspect link decoder and screenshot tool."""


@app.command(name="decode")
def decode_cmd(
    inspect_link: str = typer.Argument(..., metavar="INSPECT_LINK", help="CS2 inspect link"),
    table_output: bool = typer.Option(False, "--table", help="Output as table instead of JSON"),
) -> None:
    """Decode a CS2 inspect link and print item parameters."""
    try:
        data = decode(inspect_link)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    if not table_output:
        typer.echo(json.dumps(data.to_dict(), indent=2))
        return

    if data.needs_gc_lookup:
        rprint(
            "[yellow]Warning: legacy inspect link — full item data requires a "
            "Game Coordinator lookup (Steam bot). Only link parameters are shown.[/yellow]"
        )

    table = Table(title="CS2 Item Parameters", show_header=True, header_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value")

    def row(label: str, value: object) -> None:
        table.add_row(label, str(value) if value is not None else "[dim]—[/dim]")

    row("Inspect Link", data.inspect_link[:80] + ("…" if len(data.inspect_link) > 80 else ""))
    row("Asset ID", data.asset_id or None)
    row("Owner SteamID", data.owner_steamid or None)
    row("Market ID", data.market_id or None)
    table.add_section()
    row("DefIndex", data.defindex)
    row("Item Name", data.item_name)
    row("PaintIndex", data.paintindex)
    row("Paint Name", data.paint_name)
    row("PaintSeed", data.paintseed)
    row("PaintWear (float)", f"{data.paintwear:.10f}" if data.paintwear else None)
    row("Wear Tier", f"{data.wear_tier} ({data.wear_tier_name})" if data.wear_tier else None)
    table.add_section()
    row("StatTrak", data.stattrak)
    row("StatTrak Kills", data.stattrak_count)
    row("Souvenir", data.souvenir)
    row("Rarity", data.rarity)
    row("Quality", data.quality)

    if data.stickers:
        table.add_section()
        for i, s in enumerate(data.stickers):
            extra = ""
            if s.offset_x or s.offset_y:
                extra += f"  x={s.offset_x:.4f} y={s.offset_y:.4f}"
            # In new payloads rotation is frequently encoded in field 9 ("offset_z").
            rot = s.rotation if s.rotation else s.offset_z
            extra += f"  r={rot:.4f}"
            row(
                f"Sticker [{i}]",
                f"slot={s.slot}  id={s.sticker_id}"
                + (f" ({s.name})" if s.name else "")
                + f"  wear={s.wear:.4f}"
                + extra,
            )

    if data.keychains:
        table.add_section()
        for i, k in enumerate(data.keychains):
            row(
                f"Keychain [{i}]",
                f"slot={k.slot}  id={k.keychain_id}"
                + (f" ({k.name})" if k.name else "")
                + f"  pattern={k.pattern}",
            )

    rprint(table)


@app.command(name="render")
def render_cmd(
    inspect_link: str = typer.Argument(..., metavar="INSPECT_LINK", help="CS2 inspect link"),
    out: Path = typer.Option(Path("item-render.html"), "--out", help="Output HTML file"),
    inline_images: bool = typer.Option(
        True,
        "--inline-images/--no-inline-images",
        help="Download images and embed as data URIs to avoid browser CORS issues.",
    ),
) -> None:
    """Generate an HTML preview that overlays stickers on top of the skin image."""
    try:
        data = decode(inspect_link)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    html = build_item_render_html(data, inline_images=inline_images)
    out.write_text(html, encoding="utf-8")
    typer.echo(str(out.resolve()))


if __name__ == "__main__":
    app()
