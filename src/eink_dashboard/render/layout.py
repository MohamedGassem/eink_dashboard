"""Rendu 1 bit 800x480 en zones fixes.

Découpage vertical (constantes ``*_TOP`` / ``*_BOTTOM``) :

    HEADER   20..62    LYON + heure
    TRANSIT  78..188   une ligne par couple ligne/direction (2 max)
    BIKES   204..322   titre VÉLO'V + 2 stations
    CONTEXT 338..430   perturbations (2 lignes max) ou note d'indisponibilité
    WEATHER 438..472   température + pluie courte échéance

Le rendu est déterministe : aucune donnée hors du ViewModel, pas de scroll,
tout texte tronqué à la largeur pixel de sa zone.
"""

from importlib.resources import files
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from eink_dashboard.render.viewmodel import DashboardView, format_bikes

WIDTH = 800
HEIGHT = 480
MARGIN = 20
BLACK = 0
WHITE = 1

HEADER_TOP = 20
HEADER_RULE_Y = 62

TRANSIT_TOP = 78
TRANSIT_BOTTOM = 188
TRANSIT_ROW_H = 54
# Colonne où commence le premier passage (gros), puis les suivants (petits).
TRANSIT_FIRST_X = 360
TRANSIT_LABEL_MAX = TRANSIT_FIRST_X - MARGIN - 12

BIKES_TOP = 204
BIKES_BOTTOM = 322
BIKES_ROW_H = 44

CONTEXT_TOP = 338
CONTEXT_BOTTOM = 430
CONTEXT_LINE_H = 30

WEATHER_TOP = 440

FONT_DIR = Path(str(files("eink_dashboard") / "render" / "fonts"))


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def _glyph_or(font: ImageFont.FreeTypeFont, glyph: str, fallback: str) -> str:
    return glyph if font.getmask(glyph).getbbox() is not None else fallback


def _truncate(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    while text and draw.textlength(text + ellipsis, font=font) > max_width:
        text = text[:-1]
    return text + ellipsis


def _wraps_to_two_lines(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
        if len(lines) == 2:
            break
    if current and len(lines) < 2:
        lines.append(current)
    return lines[:2]


def render(view: DashboardView) -> Image.Image:
    image = Image.new("1", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)

    header_font = _font("DejaVuSans-Bold.ttf", 30)
    label_font = _font("DejaVuSans.ttf", 28)
    first_font = _font("DejaVuSans-Bold.ttf", 36)
    next_font = _font("DejaVuSans.ttf", 22)
    bike_label_font = _font("DejaVuSans.ttf", 28)
    bike_count_font = _font("DejaVuSans-Bold.ttf", 32)
    context_font = _font("DejaVuSans.ttf", 22)
    weather_font = _font("DejaVuSans.ttf", 26)

    right = WIDTH - MARGIN

    # --- Header -----------------------------------------------------------
    draw.text((MARGIN, HEADER_TOP), "LYON", font=header_font, fill=BLACK)
    # En journée le contenu se fige entre deux évènements : on l'annonce (« MAJ »).
    as_of_text = f"MAJ {view.as_of}" if view.coarse else view.as_of
    as_of_width = draw.textlength(as_of_text, font=next_font)
    draw.text((right - as_of_width, HEADER_TOP + 8), as_of_text, font=next_font, fill=BLACK)
    draw.line([(MARGIN, HEADER_RULE_Y), (right, HEADER_RULE_Y)], fill=BLACK, width=2)

    # --- Transit ---------------------------------------------------------
    arrow = _glyph_or(label_font, "→", "->")
    y = TRANSIT_TOP
    for row in view.departures:
        if y >= TRANSIT_BOTTOM:
            break
        text = f"{row.line} {arrow} {row.direction}"
        label = _truncate(draw, text, label_font, TRANSIT_LABEL_MAX)
        draw.text((MARGIN, y + 8), label, font=label_font, fill=BLACK)
        draw.text((TRANSIT_FIRST_X, y), row.first_wait, font=first_font, fill=BLACK)
        if row.next_waits:
            nexts = "   ".join(row.next_waits)
            nexts_width = draw.textlength(nexts, font=next_font)
            draw.text((right - nexts_width, y + 14), nexts, font=next_font, fill=BLACK)
        y += TRANSIT_ROW_H

    # --- Vélo'v --------------------------------------------------------
    draw.text((MARGIN, BIKES_TOP), "VÉLO'V", font=header_font, fill=BLACK)
    y = BIKES_TOP + 42
    for bike in view.bikes:
        if y >= BIKES_BOTTOM:
            break
        count = format_bikes(bike.bikes)
        if bike.stale:
            count += " *"
        count_width = int(draw.textlength(count, font=bike_count_font))
        label_max = right - count_width - MARGIN - 20
        draw.text(
            (MARGIN, y + 2),
            _truncate(draw, bike.label, bike_label_font, label_max),
            font=bike_label_font,
            fill=BLACK,
        )
        draw.text((right - count_width, y), count, font=bike_count_font, fill=BLACK)
        y += BIKES_ROW_H

    draw.line([(MARGIN, CONTEXT_TOP - 6), (right, CONTEXT_TOP - 6)], fill=BLACK, width=2)

    # --- Zone contextuelle : perturbations puis météo ------------------
    warn = _glyph_or(context_font, "⚠", "!")
    context_width = WIDTH - 2 * MARGIN
    y = CONTEXT_TOP
    if view.traffic_note:
        draw.text((MARGIN, y), view.traffic_note, font=context_font, fill=BLACK)
    else:
        remaining_lines = (CONTEXT_BOTTOM - CONTEXT_TOP) // CONTEXT_LINE_H
        for index, alert in enumerate(view.alerts):
            head = f"{warn} {alert.line} · "
            head_width = draw.textlength(head, font=context_font)
            wrapped = _wraps_to_two_lines(
                draw, alert.text, context_font, context_width - int(head_width)
            )
            text_max = context_width - int(head_width)
            # Une alerte sur deux lignes prend toute la zone : la suivante est omise.
            if len(wrapped) == 2 and (index > 0 or len(view.alerts) > 1):
                wrapped = [_truncate(draw, alert.text, context_font, text_max)]
            if len(wrapped) > remaining_lines:
                break
            draw.text((MARGIN, y), head + wrapped[0], font=context_font, fill=BLACK)
            y += CONTEXT_LINE_H
            for extra in wrapped[1:]:
                draw.text((MARGIN + int(head_width), y), extra, font=context_font, fill=BLACK)
                y += CONTEXT_LINE_H
            remaining_lines -= len(wrapped)

    # --- Météo --------------------------------------------------------
    if view.weather is not None:
        if view.weather.temperature:
            temperature = view.weather.temperature
            draw.text((MARGIN, WEATHER_TOP), temperature, font=weather_font, fill=BLACK)
        condition = view.weather.condition
        condition_width = draw.textlength(condition, font=weather_font)
        draw.text((right - condition_width, WEATHER_TOP), condition, font=weather_font, fill=BLACK)

    return image
