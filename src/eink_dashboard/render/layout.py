from importlib.resources import files
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from eink_dashboard.render.viewmodel import DashboardView

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

    header = _font("DejaVuSans-Bold.ttf", 26)
    title = _font("DejaVuSans-Bold.ttf", 34)
    body = _font("DejaVuSans.ttf", 30)
    small = _font("DejaVuSans.ttf", 20)

    draw.text((MARGIN, MARGIN), "LYON", font=header, fill=BLACK)
    as_of_width = draw.textlength(view.as_of, font=small)
    draw.text((WIDTH - MARGIN - as_of_width, MARGIN + 6), view.as_of, font=small, fill=BLACK)

    y = MARGIN + 48
    draw.line([(MARGIN, y), (WIDTH - MARGIN, y)], fill=BLACK, width=2)
    y += 14

    for block in view.stops:
        if y > HEIGHT - 160:
            break
        heading = block.title if not block.stale else f"{block.title}   {block.note}"
        draw.text(
            (MARGIN, y), _truncate(draw, heading, title, WIDTH - 2 * MARGIN), font=title, fill=BLACK
        )
        y += 42
        for line in block.lines:
            if y > HEIGHT - 150:
                break
            waits = "   ".join(line.waits)
            waits_width = draw.textlength(waits, font=body)
            draw.text((MARGIN + 10, y), line.line, font=body, fill=BLACK)
            label = _truncate(
                draw, line.direction, body, WIDTH - 2 * MARGIN - 60 - int(waits_width) - 30
            )
            draw.text((MARGIN + 60, y), label, font=body, fill=BLACK)
            draw.text((WIDTH - MARGIN - waits_width, y), waits, font=body, fill=BLACK)
            y += 38
        y += 10

    footer_top = HEIGHT - 120
    draw.line([(MARGIN, footer_top), (WIDTH - MARGIN, footer_top)], fill=BLACK, width=2)
    y = footer_top + 12
    draw.text((MARGIN, y), "VÉLO'V", font=header, fill=BLACK)
    y += 36

    for bike in view.bikes:
        if y > HEIGHT - 30:
            break
        suffix = f"   {bike.note}" if bike.stale else ""
        text = f"{bike.label}   {bike.bikes} vélos   {bike.docks} places   /{bike.capacity}{suffix}"
        draw.text(
            (MARGIN, y), _truncate(draw, text, body, WIDTH - 2 * MARGIN), font=body, fill=BLACK
        )
        y += 36

    return image
