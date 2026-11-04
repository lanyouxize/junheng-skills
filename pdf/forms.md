# PDF form filling

Run commands from this skill directory. Install `requirements.txt` and Poppler
as described in [SKILL.md](SKILL.md).

First determine whether the PDF has interactive fields:

```bash
python scripts/check_fillable_fields.py input.pdf
```

## Interactive (AcroForm) fields

1. Extract the actual field IDs, options and widget locations:

   ```bash
   python scripts/extract_form_field_info.py input.pdf field_info.json
   python scripts/convert_pdf_to_images.py input.pdf previews
   ```

2. Inspect the rendered pages to associate each field with its label. Extracted
   `rect` and `widgets[].rect` are in the PDF's original user space, with Y
   increasing upward. Image coordinates start at the top-left. For rotated or
   offset pages, use the page transform; simple Y inversion is insufficient.

   A field can have several widgets across several pages. `page`/`rect` identify
   its first widget; `pages`/`widgets` contain every location. Radio options also
   include their page and rectangle. A field value applies to all its widgets.

3. Create `field_values.json` as valid JSON, using values from `field_info.json`:

   ```json
   [
     {"field_id": "last_name", "page": 1, "value": "Simpson"},
     {"field_id": "Checkbox12", "page": 1, "value": "/Yes"}
   ]
   ```

   - `page` may be any page listed in that field's `pages` array.
   - Text values must be strings.
   - Checkboxes use `checked_value` or `unchecked_value`; never assume `/On`.
   - Radio groups use a `radio_options[].value`.
   - Choices use `choice_options[].value`, not their display text. Both plain
     string options and `[export value, display text]` pairs are supported.
   - A multi-select choice accepts a JSON array of export values. An editable
     choice may accept a string not present in its option list.
   - Choice appearances embed the default Vera font. For option labels outside
     its glyph set, provide a suitable TrueType `font_path` on that field's
     entry in `field_values.json`.
   - Do not supply conflicting values for the same field. Buttons and digital
     signatures are not filled by this script.

4. Fill the PDF. Validation errors produce a nonzero exit code and no output
   write. All widgets of each selected field are updated, including other pages.

   ```bash
   python scripts/fill_fillable_fields.py input.pdf field_values.json filled.pdf
   ```

5. Re-read the output with `extract_form_field_info.py`/`PdfReader.get_fields()`
   and confirm the stored values. Render `filled.pdf` and inspect the affected
   pages for visible text, correct selections and clipping. Interactive fields
   use their existing font resources; verify non-Latin text in the actual output.

## Non-interactive fields

This workflow writes text into page content, so it remains visible without a
viewer synthesizing text annotation appearances. The script's historical name
`fill_pdf_form_with_annotations.py` is retained for existing callers.

### 1. Render and locate the input areas

```bash
python scripts/convert_pdf_to_images.py input.pdf previews
```

The converter creates the directory, processes one page at a time, and writes
`page_1.png`, etc., plus `pages.json`. It renders the visible CropBox with page rotation
applied. Images from a different renderer or crop setting must use matching
geometry; use the supplied converter for this workflow.

Inspect each image. Identify a label box and a separate input box for each
field. Input boxes must cover only the writable area and must not overlap labels
or other fields. For a checkbox, target the small square, not its Yes/No label.
For an underline, place the text box above the line. For labels inside a larger
box, exclude the label from the writable portion.

### 2. Create fields.json and validation images

Copy the `pages` array from the generated `previews/pages.json` without changing
its dimensions, then add `form_fields`. This is an illustrative complete JSON
example; replace the page dimensions and boxes with the actual measurements:

```json
{
  "pages": [
    {
      "page_number": 1,
      "image_width": 773,
      "image_height": 1000,
      "pdf_width": 612,
      "pdf_height": 792
    }
  ],
  "form_fields": [
    {
      "page_number": 1,
      "description": "Last name",
      "field_label": "Last name",
      "label_bounding_box": [30, 125, 95, 145],
      "entry_bounding_box": [100, 125, 280, 145],
      "entry_text": {"text": "Johnson", "font_size": 12, "font_color": "000000"}
    },
    {
      "page_number": 1,
      "description": "Age confirmation",
      "field_label": "Yes",
      "label_bounding_box": [100, 525, 132, 540],
      "entry_bounding_box": [140, 525, 155, 540],
      "entry_text": {"text": "X", "font_size": 8}
    }
  ]
}
```

- Boxes are `[left, top, right, bottom]` in image pixels, with positive area and
  coordinates inside that page image.
- `pdf_width`/`pdf_height` are displayed physical points, accounting for rotation
  and `/UserUnit`. They are required to compare text size with image boxes.
- Font size is in points, defaults to 14; color is an RRGGBB string.
- Text is not automatically wrapped or shrunk. Use explicit `\n` for multiple
  lines; the validator checks width and total height in PDF points.
- The default embedded font is ReportLab's bundled Vera font. For Chinese or
  other unsupported glyphs, set `entry_text.font_path` to a suitable TrueType
  font file. Missing glyphs cause a validation error rather than silent boxes.

For each page, generate a validation image:

```bash
python scripts/create_validation_image.py 1 fields.json previews/page_1.png validation_1.png
```

### 3. Validate the geometry and inspect the images

```bash
python scripts/check_bounding_boxes.py fields.json
```

Errors return exit code 1. Fix invalid pages, out-of-bounds or overlapping boxes,
missing fonts, and text that does not fit. Then inspect the validation images:
red rectangles must cover only writable areas; blue rectangles must contain the
corresponding labels. Correct the measurements and regenerate images as needed.

### 4. Fill, render and inspect the result

```bash
python scripts/fill_pdf_form_with_annotations.py input.pdf fields.json filled.pdf
python scripts/convert_pdf_to_images.py filled.pdf filled_previews
```

The filler independently validates the geometry and checks that the supplied PDF
dimensions match the actual pages before writing output. It handles page rotation
and nonzero MediaBox/CropBox origins while preserving existing annotations. Inspect the
rendered result for legible text, correct alignment, clipping and missing marks
before delivering it. A successful file write is not sufficient verification.
