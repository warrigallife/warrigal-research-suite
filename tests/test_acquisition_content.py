import unittest
from io import BytesIO

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    NameObject,
    NumberObject,
    DictionaryObject,
    DecodedStreamObject,
)

from warrigal.acquisition.content import extract_pdf_content


class PDFContentExtractionTests(unittest.TestCase):
    def test_pdf_text_and_title_are_extracted(self):
        writer = PdfWriter()

        page = writer.add_blank_page(width=612, height=792)

        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")

        resources = DictionaryObject()
        resources[NameObject("/Font")] = DictionaryObject(
            {
                NameObject("/F1"): writer._add_object(font),
            }
        )
        page[NameObject("/Resources")] = resources

        content_stream = DecodedStreamObject()
        content_stream.set_data(
            b"BT\n/F1 18 Tf\n72 720 Td\n(Test Ganoderma Paper) Tj\nET"
        )
        page[NameObject("/Contents")] = writer._add_object(content_stream)

        writer.add_metadata({
            "/Title": "Test Ganoderma Paper",
        })

        buffer = BytesIO()
        writer.write(buffer)

        pdf_data = buffer.getvalue()

        content = extract_pdf_content(pdf_data)

        self.assertEqual(
            content.title,
            "Test Ganoderma Paper",
        )
        self.assertIn(
            "Test Ganoderma Paper",
            content.text,
        )


if __name__ == "__main__":
    unittest.main()
