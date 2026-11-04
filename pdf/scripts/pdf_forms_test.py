"""Regression tests using real PDF fields and rendered output."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, RectangleObject, TextStringObject, NumberObject
from reportlab.pdfgen import canvas

from check_bounding_boxes import validate_fields_data
from convert_pdf_to_images import convert
from create_validation_image import create_validation_image
from extract_form_field_info import get_field_info
from fill_fillable_fields import fill_pdf_fields, validation_error_for_field_value
from fill_pdf_form_with_annotations import fill_pdf_form
from form_utils import page_geometry

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None


class PdfFormsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="pdf-skill-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def json_file(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def form(self, field_type="choice", **kwargs):
        path = self.root / "form.pdf"
        c = canvas.Canvas(str(path))
        getattr(c.acroForm, field_type)(name="field", x=30, y=600, **kwargs)
        c.showPage()
        c.save()
        return path

    def repeated_text_form(self):
        source = self.form("textfield", value="old", width=150, height=25)
        writer = PdfWriter(clone_from=source)
        second_page = writer.add_blank_page(612, 792)
        widget_ref = writer.pages[0]["/Annots"][0]
        widget = widget_ref.get_object()
        parent = DictionaryObject({NameObject(key): widget[key] for key in ("/FT", "/T", "/V", "/DA")})
        parent_ref = writer._add_object(parent)
        for key in ("/T", "/FT", "/V", "/DV", "/DA"):
            widget.pop(key, None)
        widget[NameObject("/Parent")] = parent_ref
        second_widget = DictionaryObject(dict(widget))
        second_widget[NameObject("/P")] = second_page.indirect_reference
        second_ref = writer._add_object(second_widget)
        second_page[NameObject("/Annots")] = ArrayObject([second_ref])
        parent[NameObject("/Kids")] = ArrayObject([widget_ref, second_ref])
        writer._root_object["/AcroForm"][NameObject("/Fields")] = ArrayObject([parent_ref])
        path = self.root / "repeated.pdf"
        writer.write(path)
        return path

    def fields_data(self):
        return {
            "pages": [{"page_number": 1, "image_width": 773, "image_height": 1000, "pdf_width": 612, "pdf_height": 792}],
            "form_fields": [{"description": "Name", "page_number": 1,
                             "label_bounding_box": [10, 10, 50, 30], "entry_bounding_box": [60, 50, 300, 100],
                             "entry_text": {"text": "VISIBLE", "font_size": 14}}],
        }

    def test_plain_string_choice_round_trip(self):
        source = self.form(options=["Red", "Blue"], value="Red")
        info = get_field_info(PdfReader(source))[0]
        self.assertEqual(info["choice_options"], [{"value": "Red", "text": "Red"}, {"value": "Blue", "text": "Blue"}])
        values = self.json_file("values.json", [{"field_id": "field", "page": 1, "value": "Blue"}])
        output = self.root / "filled.pdf"
        fill_pdf_fields(source, values, output)
        result = PdfReader(output)
        self.assertEqual(result.get_fields()["field"]["/V"], "Blue")
        self.assertIs(result.trailer["/Root"]["/AcroForm"]["/NeedAppearances"].value, False)
        self.assertIn("/AP", result.pages[0]["/Annots"][0].get_object())

    def test_export_display_pairs_and_multiselect(self):
        source = self.form("listbox", options=[("Red label", "red"), ("Blue label", "blue")], value="red", fieldFlags="multiSelect")
        info = get_field_info(PdfReader(source))[0]
        self.assertEqual(info["choice_options"][0], {"value": "red", "text": "Red label"})
        self.assertIsNone(validation_error_for_field_value(info, ["red", "blue"]))
        self.assertIsNotNone(validation_error_for_field_value(info, ["invalid"]))
        output = self.root / "multi.pdf"
        values = self.json_file("multi.json", [{"field_id": "field", "page": 1, "value": ["red", "blue"]}])
        fill_pdf_fields(source, values, output)
        self.assertEqual(list(PdfReader(output).get_fields()["field"]["/V"]), ["red", "blue"])
        appearance = PdfReader(output).pages[0]["/Annots"][0].get_object()["/AP"]["/N"].get_data()
        self.assertIn(b"Red label", appearance)
        self.assertIn(b"Blue label", appearance)

    def test_repeated_widgets_are_extracted_and_updated(self):
        source = self.repeated_text_form()
        info = get_field_info(PdfReader(source))[0]
        self.assertEqual(info["pages"], [1, 2])
        self.assertEqual(len(info["widgets"]), 2)
        values = self.json_file("values.json", [{"field_id": "field", "page": 2, "value": "Updated"}])
        output = self.root / "updated.pdf"
        fill_pdf_fields(source, values, output)
        reader = PdfReader(output)
        self.assertEqual(reader.get_fields()["field"]["/V"], "Updated")
        for page in reader.pages:
            annotation = page["/Annots"][0].get_object()
            self.assertIn(b"Updated", annotation["/AP"]["/N"].get_data())

    def test_conflicting_repeated_values_do_not_write_output(self):
        source = self.repeated_text_form()
        values = self.json_file("values.json", [{"field_id": "field", "page": page, "value": str(page)} for page in (1, 2)])
        output = self.root / "invalid.pdf"
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            fill_pdf_fields(source, values, output)
        self.assertFalse(output.exists())

    def test_hierarchical_field_and_missing_fields(self):
        source = self.form("textfield", value="old")
        writer = PdfWriter(clone_from=source)
        field = writer.pages[0]["/Annots"][0]
        parent = DictionaryObject({NameObject("/T"): TextStringObject("group"), NameObject("/Kids"): ArrayObject([field])})
        parent_ref = writer._add_object(parent)
        field.get_object()[NameObject("/Parent")] = parent_ref
        writer._root_object["/AcroForm"][NameObject("/Fields")] = ArrayObject([parent_ref])
        path = self.root / "hierarchy.pdf"
        writer.write(path)
        self.assertEqual(get_field_info(PdfReader(path))[0]["field_id"], "group.field")
        blank = PdfWriter()
        blank.add_blank_page(100, 100)
        blank.write(self.root / "blank.pdf")
        self.assertEqual(get_field_info(PdfReader(self.root / "blank.pdf")), [])

    def test_combo_uses_display_text_and_keeps_export_value(self):
        source = self.form(options=[("Red label", "red"), ("Blue label", "blue")], value="red")
        values = self.json_file("values.json", [{"field_id": "field", "page": 1, "value": "blue"}])
        output = self.root / "combo.pdf"
        fill_pdf_fields(source, values, output)
        reader = PdfReader(output)
        self.assertEqual(reader.get_fields()["field"]["/V"], "blue")
        self.assertEqual(list(reader.get_fields()["field"]["/Opt"][1]), ["blue", "Blue label"])
        self.assertIn(b"Blue label", reader.pages[0]["/Annots"][0].get_object()["/AP"]["/N"].get_data())

    def test_validation_image_uses_actual_dimensions(self):
        data = self.fields_data()
        fields = self.json_file("fields.json", data)
        image = self.root / "preview.png"
        Image.new("RGB", (773, 1000), "white").save(image)
        output = self.root / "new" / "validation.png"
        create_validation_image(1, fields, image, output)
        with Image.open(output) as result:
            self.assertEqual(result.getpixel((60, 50)), (255, 0, 0))
        Image.new("RGB", (20, 20), "white").save(image)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            create_validation_image(1, fields, image, output)

    def test_checkbox_and_cross_page_radio(self):
        source = self.form("checkbox", checked=False)
        info = get_field_info(PdfReader(source))[0]
        self.assertIn(info["checked_value"], info["checked_values"])
        output = self.root / "checked.pdf"
        values = self.json_file("check.json", [{"field_id": "field", "page": 1, "value": info["checked_value"]}])
        fill_pdf_fields(source, values, output)
        self.assertEqual(PdfReader(output).pages[0]["/Annots"][0].get_object()["/AS"], info["checked_value"])
        radio = self.root / "radio.pdf"
        c = canvas.Canvas(str(radio))
        for option in ("one", "two"):
            c.acroForm.radio(name="selection", value=option, selected=option == "one", x=30, y=600)
            c.showPage()
        c.save()
        info = get_field_info(PdfReader(radio))[0]
        self.assertEqual(info["type"], "radio_group")
        self.assertEqual(info["pages"], [1, 2])
        values = self.json_file("radio.json", [{"field_id": "selection", "page": 2, "value": "/two"}])
        fill_pdf_fields(radio, values, output)
        pages = PdfReader(output).pages
        self.assertEqual(pages[0]["/Annots"][0].get_object()["/AS"], "/Off")
        self.assertEqual(pages[1]["/Annots"][0].get_object()["/AS"], "/two")

    def test_validation_units_bounds_width_and_exit_code(self):
        for mutate in (
            lambda d: d["form_fields"][0].update(page_number=999),
            lambda d: d["form_fields"][0].update(entry_bounding_box=[-100, -100, -50, -50]),
            lambda d: d["form_fields"][0].update(entry_bounding_box=[60, 50, 300, 65]),
            lambda d: d["form_fields"][0]["entry_text"].update(text="W" * 100),
            lambda d: d["form_fields"][0]["entry_text"].update(text="one\ntwo\nthree\nfour"),
            lambda d: d["pages"][0].pop("pdf_height"),
            lambda d: d["form_fields"][0]["entry_text"].update(font_path="/missing/font.ttf"),
            lambda d: d["form_fields"][0]["entry_text"].update(text="中文"),
        ):
            with self.subTest(mutate=mutate):
                data = self.fields_data()
                mutate(data)
                self.assertTrue(any(message.startswith("FAILURE:") for message in validate_fields_data(data)))
        data = self.fields_data()
        data["form_fields"][0]["entry_bounding_box"] = [10, 10, 100, 50]
        path = self.json_file("invalid.json", data)
        script = Path(__file__).with_name("check_bounding_boxes.py")
        result = subprocess.run([sys.executable, str(script), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("intersection", result.stdout)

    def test_static_filler_rejects_wrong_actual_pdf_dimensions(self):
        source = self.root / "small.pdf"
        writer = PdfWriter()
        writer.add_blank_page(100, 100)
        writer.write(source)
        data = self.fields_data()
        path = self.json_file("wrong.json", data)
        output = self.root / "invalid.pdf"
        with self.assertRaisesRegex(ValueError, "dimensions"):
            fill_pdf_form(source, path, output)
        self.assertFalse(output.exists())

    @unittest.skipUnless(pdfium, "Install requirements-dev.txt for rendering tests")
    def test_rendered_text_is_visible_and_inside_box_for_all_rotations(self):
        for rotation in (0, 90, 180, 270):
            for unit in (1, 2):
                with self.subTest(rotation=rotation, unit=unit):
                    writer = PdfWriter()
                    page = writer.add_blank_page(300, 200)
                    page.mediabox = RectangleObject((40, 60, 340, 260))
                    page[NameObject("/UserUnit")] = NumberObject(unit)
                    page.rotate(rotation)
                    link = DictionaryObject({NameObject("/Type"): NameObject("/Annot"), NameObject("/Subtype"): NameObject("/Link"), NameObject("/Rect"): RectangleObject((50, 70, 60, 80)), NameObject("/Border"): ArrayObject([NumberObject(0)] * 3)})
                    page[NameObject("/Annots")] = ArrayObject([writer._add_object(link)])
                    source = self.root / f"source-{rotation}-{unit}.pdf"
                    writer.write(source)
                    width, height, _ = page_geometry(page)
                    data = self.fields_data()
                    data["pages"][0].update(image_width=width * 2, image_height=height * 2, pdf_width=width, pdf_height=height)
                    box = [40, 80, 360, 150]
                    data["form_fields"][0]["entry_bounding_box"] = box
                    values = self.json_file("static.json", data)
                    output = self.root / f"filled-{rotation}-{unit}.pdf"
                    fill_pdf_form(source, values, output)
                    result = PdfReader(output)
                    self.assertIn("VISIBLE", result.pages[0].extract_text())
                    self.assertEqual(list(result.pages[0]["/Annots"][0].get_object()["/Rect"]), [50, 70, 60, 80])
                    with pdfium.PdfDocument(output) as doc:
                        # PDFium's render scale is per raw canvas unit.
                        image = doc[0].render(scale=2 * unit, draw_annots=False).to_pil().convert("RGB")
                        bounds = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
                    self.assertIsNotNone(bounds)
                    self.assertGreaterEqual(bounds[0], box[0] - 1)
                    self.assertGreaterEqual(bounds[1], box[1] - 1)
                    self.assertLessEqual(bounds[2], box[2] + 1)
                    self.assertLessEqual(bounds[3], box[3] + 1)

    @unittest.skipUnless(shutil.which("pdftoppm"), "Poppler required")
    def test_converter_creates_directory_and_renders_one_page_at_a_time(self):
        source = self.root / "pages.pdf"
        writer = PdfWriter()
        writer.add_blank_page(300, 200)
        writer.add_blank_page(200, 300).rotate(90)
        writer.write(source)
        from pdf2image import convert_from_path
        output = self.root / "nested" / "previews"
        with patch("convert_pdf_to_images.convert_from_path", wraps=convert_from_path) as render:
            convert(str(source), str(output), max_dim=400)
        self.assertEqual(render.call_count, 2)
        for i, call in enumerate(render.call_args_list, start=1):
            self.assertEqual((call.kwargs["first_page"], call.kwargs["last_page"]), (i, i))
        metadata = json.loads((output / "pages.json").read_text())
        for page in metadata["pages"]:
            self.assertEqual((page["pdf_width"], page["pdf_height"]), (300, 200))
            with Image.open(output / f"page_{page['page_number']}.png") as image:
                self.assertLessEqual(max(image.size), 400)
                self.assertEqual(list(image.size), [page["image_width"], page["image_height"]])

    def test_merge_example_preserves_and_namespaces_form_fields(self):
        source = self.form("textfield", value="old")
        writer = PdfWriter()
        for index in (1, 2):
            reader = PdfReader(source)
            reader.add_form_topname(f"document_{index}")
            writer.append(reader)
        output = self.root / "merged.pdf"
        writer.write(output)
        self.assertTrue({"document_1.field", "document_2.field"}.issubset(PdfReader(output).get_fields()))

    @unittest.skipUnless(pdfium and shutil.which("pdftoppm"), "Rendering dependencies required")
    def test_cropped_rotated_page_uses_visible_geometry(self):
        writer = PdfWriter()
        page = writer.add_blank_page(300, 200)
        page.mediabox = RectangleObject((40, 60, 340, 260))
        page.cropbox = RectangleObject((70, 90, 310, 230))
        page.rotate(90)
        source = self.root / "cropped.pdf"
        writer.write(source)
        previews = self.root / "previews"
        convert(str(source), str(previews), max_dim=400)
        data = json.loads((previews / "pages.json").read_text())
        info = data["pages"][0]
        self.assertEqual((info["pdf_width"], info["pdf_height"]), (140, 240))
        box = [25, 100, 200, 140]
        data["form_fields"] = [{"page_number": 1, "description": "Name", "label_bounding_box": [5, 5, 15, 20], "entry_bounding_box": box, "entry_text": {"text": "VISIBLE", "font_size": 14}}]
        values = self.json_file("cropped.json", data)
        output = self.root / "cropped-filled.pdf"
        fill_pdf_form(source, values, output)
        with pdfium.PdfDocument(output) as doc:
            image = doc[0].render(scale=2, draw_annots=False).to_pil().convert("RGB")
            bounds = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
        expected = [box[0] * 280 / info["image_width"], box[1] * 480 / info["image_height"], box[2] * 280 / info["image_width"], box[3] * 480 / info["image_height"]]
        self.assertIsNotNone(bounds)
        self.assertGreaterEqual(bounds[0], expected[0] - 1)
        self.assertGreaterEqual(bounds[1], expected[1] - 1)
        self.assertLessEqual(bounds[2], expected[2] + 1)
        self.assertLessEqual(bounds[3], expected[3] + 1)


if __name__ == "__main__":
    unittest.main()
