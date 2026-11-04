"""Extract AcroForm fields and every widget location, including repeated fields."""

import json
import sys

from pypdf import PdfReader


RADIO = 1 << 15
PUSHBUTTON = 1 << 16
EDITABLE_CHOICE = 1 << 18
MULTISELECT = 1 << 21


def get_full_annotation_field_id(annotation):
    components = []
    seen = set()
    while annotation is not None:
        annotation = annotation.get_object()
        if id(annotation) in seen:
            raise ValueError("Cycle in PDF field parent hierarchy")
        seen.add(id(annotation))
        if annotation.get("/T"):
            components.append(str(annotation["/T"]))
        annotation = annotation.get("/Parent")
    return ".".join(reversed(components)) if components else None


def make_field_dict(field, field_id):
    info = {"field_id": field_id}
    kind = field.get("/FT")
    flags = int(field.get("/Ff", 0))
    if kind == "/Tx":
        info["type"] = "text"
    elif kind == "/Btn":
        if flags & PUSHBUTTON:
            info["type"] = "pushbutton"
        elif flags & RADIO:
            info.update(type="radio_group", radio_options=[])
        else:
            info["type"] = "checkbox"
    elif kind == "/Ch":
        info.update(type="choice", choice_options=[], multi_select=bool(flags & MULTISELECT), editable=bool(flags & EDITABLE_CHOICE))
        for option in field.get("/Opt", field.get("/_States_", [])):
            if isinstance(option, str):
                value = text = option
            elif isinstance(option, (list, tuple)) and len(option) == 2:
                value, text = option
            else:
                raise ValueError(f"Unsupported choice option for {field_id}: {option!r}")
            info["choice_options"].append({"value": str(value), "text": str(text)})
    else:
        info["type"] = f"unknown ({kind})"
    return info


def get_field_info(reader):
    fields = reader.get_fields() or {}
    by_id = {}
    for field_id, field in fields.items():
        # A terminal field can have /Kids that are pure Widget objects. Only
        # containers of named child fields should be skipped here.
        kids = field.get("/Kids", [])
        if not field.get("/FT") or any("/T" in child.get_object() for child in kids):
            continue
        by_id[field_id] = make_field_dict(field, field_id)

    for page_number, page in enumerate(reader.pages, start=1):
        for reference in page.get("/Annots", []):
            annotation = reference.get_object()
            if annotation.get("/Subtype") != "/Widget":
                continue
            field_id = get_full_annotation_field_id(annotation)
            info = by_id.get(field_id)
            rect = annotation.get("/Rect")
            if info is None or rect is None:
                continue
            rect = [float(value) for value in rect]
            info.setdefault("widgets", []).append({"page": page_number, "rect": rect})
            info.setdefault("page", page_number)
            info.setdefault("rect", rect)
            normal = annotation.get("/AP", {}).get("/N", {})
            on_values = [str(value) for value in normal if value != "/Off"] if isinstance(normal, dict) else []
            if info["type"] == "radio_group":
                info["radio_options"].extend({"value": value, "page": page_number, "rect": rect} for value in on_values)
            elif info["type"] == "checkbox":
                states = info.setdefault("checked_values", [])
                for value in on_values:
                    if value not in states:
                        states.append(value)
                if states:
                    info["checked_value"] = states[0]
                info["unchecked_value"] = "/Off"

    result = []
    for info in by_id.values():
        if not info.get("widgets"):
            print(f"Unable to determine widget location for field {info['field_id']}; ignoring", file=sys.stderr)
            continue
        info["pages"] = sorted({widget["page"] for widget in info["widgets"]})
        result.append(info)
    result.sort(key=lambda info: (info["page"], -info["rect"][1], info["rect"][0]))
    return result


def write_field_info(pdf_path, json_output_path):
    info = get_field_info(PdfReader(pdf_path))
    with open(json_output_path, "w", encoding="utf-8") as output:
        json.dump(info, output, indent=2, ensure_ascii=False)
    print(f"Wrote {len(info)} fields to {json_output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: extract_form_field_info.py [input pdf] [output json]")
        sys.exit(1)
    write_field_info(*sys.argv[1:])
