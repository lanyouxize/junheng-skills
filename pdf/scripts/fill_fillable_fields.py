"""Validate and fill AcroForm fields, updating appearances on all widget pages."""

import json
import sys

from pypdf import PdfReader, PdfWriter

from extract_form_field_info import get_field_info
from choice_appearance import fill_choice


def validation_error_for_field_value(info, value):
    kind = info["type"]
    field_id = info["field_id"]
    if kind == "text":
        valid = isinstance(value, str)
    elif kind == "checkbox":
        valid = isinstance(value, str) and value in info.get("checked_values", [info.get("checked_value")]) + [info.get("unchecked_value", "/Off")]
    elif kind == "radio_group":
        valid = isinstance(value, str) and value in [option["value"] for option in info["radio_options"]]
    elif kind == "choice":
        choices = [option["value"] for option in info["choice_options"]]
        if isinstance(value, list):
            valid = info.get("multi_select", False) and all(isinstance(item, str) and item in choices for item in value)
        else:
            valid = isinstance(value, str) and (value in choices or info.get("editable", False))
    else:
        return f"ERROR: Unsupported field type {kind!r} for {field_id!r}"
    if not valid:
        return f"ERROR: Invalid value {value!r} for {kind} field {field_id!r}"
    return None


def fill_pdf_fields(input_pdf_path, fields_json_path, output_pdf_path):
    with open(fields_json_path, encoding="utf-8") as stream:
        fields = json.load(stream)
    if not isinstance(fields, list):
        raise ValueError("field_values.json must contain a list")
    reader = PdfReader(input_pdf_path)
    by_id = {field["field_id"]: field for field in get_field_info(reader)}
    values = {}
    settings = {}
    errors = []
    for field in fields:
        if not isinstance(field, dict) or "field_id" not in field:
            errors.append("ERROR: Each entry must contain field_id and page")
            continue
        field_id = field["field_id"]
        if not isinstance(field_id, str) or field_id not in by_id:
            errors.append(f"ERROR: {field_id!r} is not a valid field ID")
            continue
        info = by_id[field_id]
        if type(field.get("page")) is not int or field["page"] not in info["pages"]:
            errors.append(f"ERROR: Incorrect page for {field_id!r}; expected one of {info['pages']}")
        if "value" not in field:
            continue
        error = validation_error_for_field_value(info, field["value"])
        if error:
            errors.append(error)
        elif field_id in values and values[field_id] != field["value"]:
            errors.append(f"ERROR: Conflicting values for repeated field {field_id!r}")
        else:
            values[field_id] = field["value"]
            settings[field_id] = field
    if errors:
        raise ValueError("\n".join(errors))

    writer = PdfWriter(clone_from=reader)
    if values:
        # Update every widget, so repeated text and cross-page radio groups do
        # not retain stale appearances on pages omitted from field_values.json.
        ordinary = {field_id: value for field_id, value in values.items() if by_id[field_id]["type"] != "choice"}
        if ordinary:
            writer.update_page_form_field_values(None, ordinary, auto_regenerate=False)
        for field_id, value in values.items():
            if by_id[field_id]["type"] == "choice":
                fill_choice(writer, by_id[field_id], value, settings[field_id])
        writer.set_need_appearances_writer(False)
    with open(output_pdf_path, "wb") as output:
        writer.write(output)
    print(f"Wrote {len(values)} field values to {output_pdf_path}; render and inspect before delivery")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: fill_fillable_fields.py [input pdf] [field_values.json] [output pdf]")
        sys.exit(1)
    try:
        fill_pdf_fields(*sys.argv[1:])
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
