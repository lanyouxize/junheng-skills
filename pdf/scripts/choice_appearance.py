"""Generate choice widget appearances without changing their export options."""

from io import BytesIO
import re

from pypdf import PdfReader
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject, RectangleObject, TextStringObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from form_utils import resolve_font
from extract_form_field_info import get_full_annotation_field_id


def _set_color(drawing, values, stroke=False):
    methods = {
        1: drawing.setStrokeGray if stroke else drawing.setFillGray,
        3: drawing.setStrokeColorRGB if stroke else drawing.setFillColorRGB,
        4: drawing.setStrokeColorCMYK if stroke else drawing.setFillColorCMYK,
    }
    if values and len(values) in methods:
        methods[len(values)](*[float(value) for value in values])


def fill_choice(writer, info, value, settings):
    field_ref = writer.get_fields()[info["field_id"]].indirect_reference
    field = field_ref.get_object()
    selected = value if isinstance(value, list) else [value]
    field[NameObject("/V")] = ArrayObject([TextStringObject(item) for item in value]) if isinstance(value, list) else TextStringObject(value)
    indices = [index for index, option in enumerate(info["choice_options"]) if option["value"] in selected]
    if indices:
        field[NameObject("/I")] = ArrayObject([NumberObject(index) for index in indices])
    else:
        field.pop("/I", None)
    labels = [option["text"] for option in info["choice_options"]]
    combo = bool(int(field.get("/Ff", 0)) & (1 << 17))
    display_value = next((option["text"] for option in info["choice_options"] if option["value"] == value), value) if combo else ""
    font_data = {"text": str(display_value) if combo else "\n".join(labels)}
    if "font_path" in settings:
        font_data["font_path"] = settings["font_path"]
    font = resolve_font(font_data)

    for number in info["pages"]:
        page = writer.pages[number - 1]
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            # Compare the qualified name rather than the field's short name.
            if annotation.get("/Subtype") != "/Widget" or get_full_annotation_field_id(annotation) != info["field_id"]:
                continue
            rect = annotation["/Rect"]
            width, height = float(rect[2] - rect[0]), float(rect[3] - rect[1])
            buffer = BytesIO()
            drawing = canvas.Canvas(buffer, pagesize=(width, height))
            characteristics = annotation.get("/MK", field.get("/MK", {}))
            background, border = characteristics.get("/BG"), characteristics.get("/BC")
            if background:
                _set_color(drawing, background)
                drawing.rect(0, 0, width, height, stroke=0, fill=1)
            border_width = float(annotation.get("/BS", field.get("/BS", {})).get("/W", 1))
            if border and border_width > 0:
                _set_color(drawing, border, stroke=True)
                drawing.setLineWidth(border_width)
                drawing.rect(border_width / 2, border_width / 2, max(0, width - border_width), max(0, height - border_width), stroke=1, fill=0)
            padding = max(2, border_width + 1)
            clip = drawing.beginPath()
            clip.rect(padding, padding, max(0, width - 2 * padding), max(0, height - 2 * padding))
            drawing.clipPath(clip, stroke=0)
            appearance = str(annotation.get_inherited("/DA", writer._root_object["/AcroForm"].get("/DA", "")))
            match = re.search(r"/\S+\s+([0-9.]+)\s+Tf", appearance)
            size = float(match.group(1)) if match else 12
            if size <= 0:
                size = min(12, max(1, height - 2 * padding))
            drawing.setFont(font, size)
            baseline = height - padding - pdfmetrics.getAscent(font, size)
            if combo:
                drawing.setFillColorRGB(0, 0, 0)
                drawing.drawString(padding, baseline, str(display_value))
            else:
                for index in range(max(0, int(field.get("/TI", 0))), len(labels)):
                    if baseline + size < 0:
                        break
                    if index in indices:
                        drawing.setFillColorRGB(0.8, 0.85, 0.95)
                        drawing.rect(padding, baseline + pdfmetrics.getDescent(font, size), width - 2 * padding, size * 1.2, stroke=0, fill=1)
                    drawing.setFillColorRGB(0, 0, 0)
                    drawing.drawString(padding, baseline, labels[index])
                    baseline -= size * 1.2
            drawing.save()
            overlay = PdfReader(buffer).pages[0]
            stream = DecodedStreamObject()
            stream.set_data(overlay.get_contents().get_data())
            stream.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Form"), NameObject("/BBox"): RectangleObject((0, 0, width, height)), NameObject("/Resources"): overlay["/Resources"].clone(writer)})
            annotation[NameObject("/AP")] = DictionaryObject({NameObject("/N"): writer._add_object(stream)})
