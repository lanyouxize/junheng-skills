"""Shared page geometry and embedded fonts for PDF form scripts."""

import hashlib
import math
from pathlib import Path

import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.ttfonts import TTFError


def positive_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def page_geometry(page):
    """Displayed visible page size in points and inverse transform to user space.

    Images must use use_cropbox=True, as convert_pdf_to_images.py does.
    """
    media, crop = page.mediabox, page.cropbox
    left, bottom = max(float(media.left), float(crop.left)), max(float(media.bottom), float(crop.bottom))
    right, top = min(float(media.right), float(crop.right)), min(float(media.top), float(crop.top))
    width, height = right - left, top - bottom
    unit = float(page.get("/UserUnit", 1))
    rotation = int(page.get("/Rotate", 0)) % 360
    if not all(positive_number(v) for v in (width, height, unit)):
        raise ValueError("Invalid MediaBox/CropBox dimensions or /UserUnit")
    if rotation not in (0, 90, 180, 270):
        raise ValueError("Page rotation must be a multiple of 90 degrees")
    scale = 1 / unit
    transforms = {
        0: (scale, 0, 0, scale, left, bottom),
        90: (0, scale, -scale, 0, left + width, bottom),
        180: (-scale, 0, 0, -scale, left + width, bottom + height),
        270: (0, -scale, scale, 0, left, bottom + height),
    }
    if rotation in (90, 270):
        width, height = height, width
    return width * unit, height * unit, transforms[rotation]


def resolve_font(entry_text):
    """Embed a TrueType font; report missing glyphs instead of drawing boxes."""
    font_path = entry_text.get("font_path")
    if font_path is not None and not isinstance(font_path, str):
        raise ValueError("font_path must be a file path string")
    path = Path(font_path).expanduser().resolve() if font_path else Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
    name = "PDFForm_" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
    if name not in pdfmetrics.getRegisteredFontNames():
        try:
            pdfmetrics.registerFont(TTFont(name, str(path)))
        except (OSError, TTFError) as error:
            raise ValueError(f"Cannot load TrueType font {path}: {error}") from error
    font = pdfmetrics.getFont(name)
    text = entry_text.get("text", "")
    missing = {ord(c) for c in text if c not in "\n\r" and ord(c) not in font.face.charToGlyph}
    if missing:
        sample = ", ".join(f"U+{c:04X}" for c in sorted(missing)[:5])
        raise ValueError(f"Font lacks glyphs {sample}; supply entry_text.font_path with a suitable TrueType font")
    return name


def text_layout(entry_text):
    size = entry_text.get("font_size", 14)
    if not positive_number(size):
        raise ValueError("font_size must be a positive finite number in points")
    text = entry_text.get("text", "")
    if not isinstance(text, str):
        raise ValueError("entry_text.text must be a string")
    font = resolve_font(entry_text)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    leading = size * 1.2
    width = max(pdfmetrics.stringWidth(line, font, size) for line in lines)
    ascent, descent = pdfmetrics.getAscentDescent(font, size)
    height = max(size, ascent - descent) + (len(lines) - 1) * leading
    return font, size, lines, leading, width, height
