"""Render one page at a time and write geometry metadata for fields.json."""

import json
from pathlib import Path
import sys

from pdf2image import convert_from_path
from pypdf import PdfReader

from form_utils import page_geometry, positive_number


def convert(pdf_path, output_dir, max_dim=1000):
    if not positive_number(max_dim) or int(max_dim) != max_dim:
        raise ValueError("max_dim must be a positive integer")
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(pdf_path)
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        width, height, _ = page_geometry(page)
        images = convert_from_path(pdf_path, dpi=200, first_page=index, last_page=index, size=int(max_dim), use_cropbox=True)
        image = images[0]
        try:
            image_path = output / f"page_{index}.png"
            image.save(image_path)
            pages.append({"page_number": index, "image_width": image.width, "image_height": image.height, "pdf_width": width, "pdf_height": height})
            print(f"Saved page {index} as {image_path} (size: {image.size})")
        finally:
            image.close()
    with (output / "pages.json").open("w", encoding="utf-8") as stream:
        json.dump({"pages": pages}, stream, indent=2)
    print(f"Converted {len(pages)} pages; dimensions saved to {output / 'pages.json'}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: convert_pdf_to_images.py [input pdf] [output directory]")
        sys.exit(1)
    convert(*sys.argv[1:])
