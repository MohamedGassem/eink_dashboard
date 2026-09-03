from importlib.resources import files
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from eink_dashboard.render.viewmodel import DashboardView, format_bikes

WIDTH = 800
HEIGHT = 480
MARGIN = 20
BLACK = 0
WHITE = 1

FONT_DIR = Path(str(files("eink_dashboard") / "render" / "fonts"))


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _truncate(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text + ellipsis


def render(view: DashboardView) -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    header = _font("DejaVuSans-Bold.ttf", 30)
    first = _font("DejaVuSans-Bold.ttf", 34)
    body = _font("DejaVuSans.ttf", 28)
    small = _font("DejaVuSans.ttf", 22)

    right = WIDTH - MARGIN

    # Header : LYON + heure.
    draw.text((MARGIN, MARGIN), "LYON", font=header, fill=BLACK)
    as_of_width = draw.textlength(view.as_of, font=small)
    draw.text((right - as_of_width, MARGIN + 6), view.as_of, font=small, fill=BLACK)
    draw.line([(MARGIN, 62), (right, 62)], fill=BLACK, width=2)

    # Transit : une ligne par couple ligne/direction.
    y = 82
    for row in view.departures:
        label = _truncate(draw, f"{row.line} → {row.direction}", body, 360)
        draw.text((MARGIN, y + 4), label, font=body, fill=BLACK)
        draw.text((MARGIN + 380, y), row.first_wait, font=first, fill=BLACK)
        nexts = "   ".join(row.next_waits)
        nexts_width = draw.textlength(nexts, font=small)
        draw.text((right - nexts_width, y + 10), nexts, font=small, fill=BLACK)
        y += 50

    # Vélo'v : titre + une ligne par station.
    y = max(y, 210) + 8
    draw.text((MARGIN, y), "VÉLO'V", font=header, fill=BLACK)
    y += 40
    for bike in view.bikes:
        text = format_bikes(bike.bikes)
        if bike.stale:
            text += " *"
        text_width = draw.textlength(text, font=first if bike.bikes == 0 else body)
        font = first if bike.bikes == 0 else body
        draw.text((MARGIN, y), _truncate(draw, bike.label, body, 520), font=body, fill=BLACK)
        draw.text((right - text_width, y - 2), text, font=font, fill=BLACK)
        y += 46

    # Zone contextuelle : perturbations puis météo.
    footer_top = HEIGHT - 134
    draw.line([(MARGIN, footer_top), (right, footer_top)], fill=BLACK, width=2)
    y = footer_top + 12
    for alert in view.alerts:
        line = _truncate(draw, f"! {alert.line} · {alert.text}", small, WIDTH - 2 * MARGIN)
        draw.text((MARGIN, y), line, font=small, fill=BLACK)
        y += 30
    if view.traffic_note:
        draw.text((MARGIN, y), view.traffic_note, font=small, fill=BLACK)
        y += 30

    if view.weather is not None:
        weather_y = HEIGHT - 34
        draw.text((MARGIN, weather_y), view.weather.temperature, font=body, fill=BLACK)
        condition = view.weather.condition
        condition_width = draw.textlength(condition, font=body)
        draw.text((right - condition_width, weather_y), condition, font=body, fill=BLACK)

    return image
