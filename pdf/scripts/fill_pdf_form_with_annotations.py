"""Fill non-interactive forms with embedded text in the page content.

The historical filename is retained for existing callers; output no longer
relies on a PDF viewer generating FreeText annotation appearances.
"""

from io import BytesIO
import json
import math
import sys

from pypdf import PdfReader, PdfWriter
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from check_bounding_boxes import validate_fields_data
from form_utils import page_geometry, text_layout


def transform_coordinates(bbox, image_width, image_height, pdf_width, pdf_height):
    """Map image pixels to displayed PDF points, before inverse page rotation."""
    return (
        bbox[0] * pdf_width / image_width,
        pdf_height - bbox[3] * pdf_height / image_height,
        bbox[2] * pdf_width / image_width,
        pdf_height - bbox[1] * pdf_height / image_height,
    )


def fill_pdf_form(input_pdf_path, fields_json_path, output_pdf_path):
    with open(fields_json_path, encoding="utf-8") as stream:
        data = json.load(stream)
    errors = [message for message in validate_fields_data(data) if message.startswith("FAILURE:")]
    if errors:
        raise ValueError("\n".join(errors))

    writer = PdfWriter(clone_from=input_pdf_path)
    pages = {page["page_number"]: page for page in data["pages"]}
    for number, info in pages.items():
        if number > len(writer.pages):
            raise ValueError(f"Page {number} does not exist in the input PDF")
        width, height, _ = page_geometry(writer.pages[number - 1])
        if not all(math.isclose(actual, info[key], rel_tol=1e-6, abs_tol=0.02) for actual, key in ((width, "pdf_width"), (height, "pdf_height"))):
            raise ValueError(f"PDF dimensions for page {number} do not match the input PDF; regenerate pages.json")

    count = 0
    for number, info in pages.items():
        fields = [field for field in data["form_fields"] if field["page_number"] == number and field.get("entry_text", {}).get("text")]
        if not fields:
            continue
        page = writer.pages[number - 1]
        width, height, inverse = page_geometry(page)
        buffer = BytesIO()
        overlay_canvas = canvas.Canvas(buffer, pagesize=(width, height))
        for field in fields:
            entry = field["entry_text"]
            font, size, lines, leading, _, _ = text_layout(entry)
            left, _, _, top = transform_coordinates(field["entry_bounding_box"], info["image_width"], info["image_height"], width, height)
            overlay_canvas.setFont(font, size)
            overlay_canvas.setFillColor(HexColor("#" + entry.get("font_color", "000000")))
            baseline = top - pdfmetrics.getAscent(font, size)
            for line in lines:
                overlay_canvas.drawString(left, baseline, line)
                baseline -= leading
            count += 1
        overlay_canvas.save()
        overlay = PdfReader(buffer).pages[0]
        page.merge_transformed_page(overlay, inverse, expand=False)

    with open(output_pdf_path, "wb") as output:
        writer.write(output)
    print(f"Wrote {count} text entries to {output_pdf_path}; render and inspect the output before delivery")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: fill_pdf_form_with_annotations.py [input pdf] [fields.json] [output pdf]")
        sys.exit(1)
    try:
        fill_pdf_form(*sys.argv[1:])
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
