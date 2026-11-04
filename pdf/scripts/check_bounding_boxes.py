"""Validate fields.json geometry and text fit in physical PDF points."""

from dataclasses import dataclass
import json
import math
import re
import sys

from form_utils import positive_number, text_layout


@dataclass
class RectAndField:
    rect: list[float]
    rect_type: str
    field: dict


def validate_fields_data(data):
    messages = []
    if not isinstance(data, dict) or not isinstance(data.get("form_fields"), list):
        return ["FAILURE: form_fields must be a list"]
    messages.append(f"Read {len(data['form_fields'])} fields")
    if not isinstance(data.get("pages"), list) or not data["pages"]:
        return messages + ["FAILURE: pages must include image_width, image_height, pdf_width and pdf_height"]

    def fail(message):
        messages.append("FAILURE: " + message)

    pages = {}
    for page in data["pages"]:
        if not isinstance(page, dict):
            fail("Each page must be an object")
            continue
        number = page.get("page_number")
        if type(number) is not int or number < 1 or number in pages:
            fail("page_number must be a unique positive integer")
            continue
        if not all(positive_number(page.get(k)) for k in ("image_width", "image_height", "pdf_width", "pdf_height")):
            fail(f"Page {number} must have positive image dimensions in pixels and PDF dimensions in points")
            continue
        pages[number] = page

    rects = []
    for index, field in enumerate(data["form_fields"]):
        if not isinstance(field, dict):
            fail(f"Field {index + 1} must be an object")
            continue
        description = field.get("description", f"Field {index + 1}")
        number = field.get("page_number")
        if type(number) is not int or number not in pages:
            fail(f"Unknown page_number for `{description}`")
            continue
        page = pages[number]
        valid_boxes = {}
        for kind in ("label", "entry"):
            rect = field.get(f"{kind}_bounding_box")
            valid = (
                isinstance(rect, list) and len(rect) == 4
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in rect)
            )
            if not valid or not (0 <= rect[0] < rect[2] <= page["image_width"] and 0 <= rect[1] < rect[3] <= page["image_height"]):
                fail(f"Invalid or out-of-bounds {kind} bounding box for `{description}`")
                continue
            valid_boxes[kind] = rect
            rects.append(RectAndField(rect, kind, field))

        if "entry_text" in field:
            entry = field["entry_text"]
            if not isinstance(entry, dict):
                fail(f"entry_text must be an object for `{description}`")
                continue
            color = entry.get("font_color", "000000")
            if not isinstance(color, str) or not re.fullmatch(r"[0-9a-fA-F]{6}", color):
                fail(f"Invalid font_color for `{description}`; use RRGGBB")
            try:
                _, _, _, _, width, height = text_layout(entry)
            except (ValueError, OSError, KeyError) as error:
                fail(f"Invalid text for `{description}`: {error}")
                continue
            if "entry" in valid_boxes:
                rect = valid_boxes["entry"]
                box_width = (rect[2] - rect[0]) * page["pdf_width"] / page["image_width"]
                box_height = (rect[3] - rect[1]) * page["pdf_height"] / page["image_height"]
                if box_height + 1e-6 < height:
                    fail(f"entry bounding box height ({box_height:.2f} pt) for `{description}` is too short for the text content ({height:.2f} pt)")
                if box_width + 1e-6 < width:
                    fail(f"entry bounding box width ({box_width:.2f} pt) for `{description}` is too narrow for the text content ({width:.2f} pt)")

    for i, first in enumerate(rects):
        for second in rects[i + 1:]:
            if first.field["page_number"] != second.field["page_number"]:
                continue
            a, b = first.rect, second.rect
            if a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]:
                description = first.field.get("description", "field")
                if first.field is second.field:
                    fail(f"intersection between label and entry bounding boxes for `{description}` ({a}, {b})")
                else:
                    fail(f"intersection between {first.rect_type} bounding box for `{description}` ({a}) and {second.rect_type} bounding box ({b})")
            if len(messages) >= 20:
                return messages[:20] + ["Aborting further checks; fix bounding boxes and try again"]

    if not any(message.startswith("FAILURE:") for message in messages):
        messages.append("SUCCESS: All bounding boxes are valid")
    return messages


def get_bounding_box_messages(fields_json_stream):
    return validate_fields_data(json.load(fields_json_stream))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: check_bounding_boxes.py [fields.json]")
        sys.exit(1)
    try:
        with open(sys.argv[1], encoding="utf-8") as stream:
            messages = get_bounding_box_messages(stream)
    except (OSError, ValueError) as error:
        messages = [f"FAILURE: {error}"]
    for message in messages:
        print(message)
    sys.exit(1 if any(message.startswith("FAILURE:") for message in messages) else 0)
