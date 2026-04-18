"""Tests for source/services/media/file_extractor.py"""

import base64
import datetime
import io
import os
import sys
import tempfile
import time
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import source.services.media.file_extractor as file_extractor_module
from source.services.media.file_extractor import (
    ARCHIVE_EXTENSIONS,
    EXTRACTED_IMAGE_PREFIX,
    EXTRACTION_EXTENSIONS,
    FileInfo,
    IMAGE_EXTENSIONS,
    LEGACY_UNSUPPORTED,
    MAX_EXCEL_ROWS,
    MIN_IMAGE_SIZE,
    PaginatedResult,
    TEXT_NATIVE_EXTENSIONS,
    ExtractedImage,
    ExtractionMetadata,
    ExtractionResult,
    FileExtractor,
    ImageResult,
)


def _make_png_bytes(size=(100, 100), color="red"):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color=color).save(buffer, format="PNG")
    return buffer.getvalue()


# ------------------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------------------


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def extractor(temp_dir):
    """Create a FileExtractor with a temp screenshot folder."""
    return FileExtractor(screenshot_folder=temp_dir)


@pytest.fixture
def sample_text_file(temp_dir):
    """Create a sample text file."""
    filepath = os.path.join(temp_dir, "sample.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("Hello, World!\nThis is a test file.")
    return filepath


@pytest.fixture
def sample_image_file(temp_dir):
    """Create a sample PNG image."""
    from PIL import Image

    filepath = os.path.join(temp_dir, "sample.png")
    img = Image.new("RGB", (100, 100), color="red")
    img.save(filepath)
    return filepath


@pytest.fixture
def sample_small_image_file(temp_dir):
    """Create a small image (below MIN_IMAGE_SIZE threshold)."""
    from PIL import Image

    filepath = os.path.join(temp_dir, "small.png")
    img = Image.new("RGB", (30, 30), color="blue")
    img.save(filepath)
    return filepath


# ------------------------------------------------------------------------------
# Test Constants
# ------------------------------------------------------------------------------


class TestConstants:
    """Tests for module constants."""

    def test_text_native_extensions_is_frozenset(self):
        assert isinstance(TEXT_NATIVE_EXTENSIONS, frozenset)
        assert ".txt" in TEXT_NATIVE_EXTENSIONS
        assert ".py" in TEXT_NATIVE_EXTENSIONS
        assert ".md" in TEXT_NATIVE_EXTENSIONS
        assert ".json" in TEXT_NATIVE_EXTENSIONS

    def test_image_extensions_is_frozenset(self):
        assert isinstance(IMAGE_EXTENSIONS, frozenset)
        assert ".png" in IMAGE_EXTENSIONS
        assert ".jpg" in IMAGE_EXTENSIONS
        assert ".jpeg" in IMAGE_EXTENSIONS
        assert ".webp" in IMAGE_EXTENSIONS
        assert ".gif" in IMAGE_EXTENSIONS

    def test_extraction_extensions_is_frozenset(self):
        assert isinstance(EXTRACTION_EXTENSIONS, frozenset)
        assert ".pdf" in EXTRACTION_EXTENSIONS
        assert ".docx" in EXTRACTION_EXTENSIONS
        assert ".pptx" in EXTRACTION_EXTENSIONS
        assert ".xlsx" in EXTRACTION_EXTENSIONS
        assert ".xls" in EXTRACTION_EXTENSIONS

    def test_archive_extensions_is_frozenset(self):
        assert isinstance(ARCHIVE_EXTENSIONS, frozenset)
        assert ".zip" in ARCHIVE_EXTENSIONS

    def test_legacy_unsupported_is_frozenset(self):
        assert isinstance(LEGACY_UNSUPPORTED, frozenset)
        assert ".doc" in LEGACY_UNSUPPORTED
        assert ".ppt" in LEGACY_UNSUPPORTED

    def test_min_image_size_is_positive(self):
        assert MIN_IMAGE_SIZE > 0
        assert MIN_IMAGE_SIZE == 50

    def test_max_excel_rows_is_positive(self):
        assert MAX_EXCEL_ROWS > 0
        assert MAX_EXCEL_ROWS == 2000


# ------------------------------------------------------------------------------
# Test Data Classes
# ------------------------------------------------------------------------------


class TestExtractedImage:
    """Tests for ExtractedImage dataclass."""

    def test_create_extracted_image(self):
        img = ExtractedImage(
            path="/path/to/image.png",
            page=1,
            index=1,
            width=100,
            height=200,
            description="Page 1, Image 1",
        )
        assert img.path == "/path/to/image.png"
        assert img.page == 1
        assert img.index == 1
        assert img.width == 100
        assert img.height == 200
        assert img.description == "Page 1, Image 1"

    def test_extracted_image_with_no_page(self):
        img = ExtractedImage(
            path="/path/to/image.png",
            page=None,
            index=1,
            width=100,
            height=100,
            description="Image 1",
        )
        assert img.page is None


class TestExtractionMetadata:
    """Tests for ExtractionMetadata dataclass."""

    def test_create_metadata_minimal(self):
        meta = ExtractionMetadata(format="pdf", file_size_bytes=1024)
        assert meta.format == "pdf"
        assert meta.file_size_bytes == 1024
        assert meta.title is None
        assert meta.author is None
        assert meta.created_at is None
        assert meta.sheet_names is None
        assert meta.slide_count is None

    def test_create_metadata_full(self):
        meta = ExtractionMetadata(
            format="xlsx",
            file_size_bytes=2048,
            title="Test Document",
            author="Test Author",
            created_at="2024-01-01T00:00:00",
            sheet_names=["Sheet1", "Sheet2"],
            slide_count=None,
        )
        assert meta.title == "Test Document"
        assert meta.author == "Test Author"
        assert meta.sheet_names == ["Sheet1", "Sheet2"]


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_create_result_minimal(self):
        result = ExtractionResult(
            text="Sample text",
            total_chars=11,
            page_count=1,
        )
        assert result.text == "Sample text"
        assert result.total_chars == 11
        assert result.page_count == 1
        assert result.extracted_images == []
        assert result.metadata is None
        assert result.warnings == []

    def test_create_result_with_images_and_warnings(self):
        img = ExtractedImage(
            path="/path/to/img.png",
            page=1,
            index=1,
            width=100,
            height=100,
            description="Test",
        )
        result = ExtractionResult(
            text="Sample",
            total_chars=6,
            page_count=1,
            extracted_images=[img],
            warnings=["Warning 1"],
        )
        assert len(result.extracted_images) == 1
        assert len(result.warnings) == 1


class TestImageResult:
    """Tests for ImageResult dataclass."""

    def test_create_image_result(self):
        result = ImageResult(
            type="image",
            media_type="image/png",
            data="base64data",
            width=100,
            height=200,
            file_size_bytes=1024,
        )
        assert result.type == "image"
        assert result.media_type == "image/png"
        assert result.data == "base64data"
        assert result.width == 100
        assert result.height == 200
        assert result.file_size_bytes == 1024

    def test_image_result_to_dict(self):
        result = ImageResult(
            type="image",
            media_type="image/jpeg",
            data="abc123",
            width=50,
            height=50,
            file_size_bytes=512,
        )
        d = result.to_dict()
        assert d["type"] == "image"
        assert d["media_type"] == "image/jpeg"
        assert d["data"] == "abc123"
        assert d["width"] == 50
        assert d["height"] == 50
        assert d["file_size_bytes"] == 512

    def test_image_result_defaults(self):
        result = ImageResult()
        assert result.type == "image"
        assert result.media_type == ""
        assert result.data == ""
        assert result.width == 0
        assert result.height == 0
        assert result.file_size_bytes == 0


class TestPaginationDataClasses:
    """Tests for pagination-related dataclasses."""

    def test_file_info_to_dict(self):
        info = FileInfo(
            format="pdf",
            file_size_bytes=1234,
            page_count=2,
            title="Doc",
            author="Author",
            extracted_images=[{"path": "/tmp/img.png"}],
            warnings=["warning"],
        )
        payload = info.to_dict()
        assert payload["format"] == "pdf"
        assert payload["file_size_bytes"] == 1234
        assert payload["page_count"] == 2
        assert payload["title"] == "Doc"
        assert payload["author"] == "Author"
        assert payload["extracted_images"] == [{"path": "/tmp/img.png"}]
        assert payload["warnings"] == ["warning"]

    def test_paginated_result_to_dict_omits_file_info_when_none(self):
        paginated = PaginatedResult(
            content="abc",
            total_chars=3,
            offset=0,
            chars_returned=3,
            has_more=False,
            next_offset=None,
            chunk_summary="Showing characters 0-3 of 3 (100%)",
            file_info=None,
        )
        payload = paginated.to_dict()
        assert payload["content"] == "abc"
        assert payload["has_more"] is False
        assert "file_info" not in payload


# ------------------------------------------------------------------------------
# Test FileExtractor Static Methods
# ------------------------------------------------------------------------------


class TestFileExtractorStaticMethods:
    """Tests for FileExtractor static methods."""

    def test_is_image_file_true(self):
        assert FileExtractor.is_image_file("/path/to/file.png") is True
        assert FileExtractor.is_image_file("/path/to/file.jpg") is True
        assert FileExtractor.is_image_file("/path/to/file.JPEG") is True
        assert FileExtractor.is_image_file("/path/to/file.WebP") is True

    def test_is_image_file_false(self):
        assert FileExtractor.is_image_file("/path/to/file.txt") is False
        assert FileExtractor.is_image_file("/path/to/file.pdf") is False
        assert FileExtractor.is_image_file("/path/to/file") is False

    def test_is_text_native_true(self):
        assert FileExtractor.is_text_native("/path/to/file.txt") is True
        assert FileExtractor.is_text_native("/path/to/file.py") is True
        assert FileExtractor.is_text_native("/path/to/file.md") is True
        assert FileExtractor.is_text_native("/path/to/Makefile") is True  # no extension

    def test_is_text_native_false(self):
        assert FileExtractor.is_text_native("/path/to/file.pdf") is False
        assert FileExtractor.is_text_native("/path/to/file.png") is False
        assert FileExtractor.is_text_native("/path/to/file.docx") is False

    def test_is_extractable_true(self):
        assert FileExtractor.is_extractable("/path/to/file.pdf") is True
        assert FileExtractor.is_extractable("/path/to/file.docx") is True
        assert FileExtractor.is_extractable("/path/to/file.xlsx") is True
        assert FileExtractor.is_extractable("/path/to/file.PPTX") is True

    def test_is_extractable_false(self):
        assert FileExtractor.is_extractable("/path/to/file.txt") is False
        assert FileExtractor.is_extractable("/path/to/file.png") is False
        assert FileExtractor.is_extractable("/path/to/file.doc") is False  # legacy


# ------------------------------------------------------------------------------
# Test FileExtractor Instance Methods
# ------------------------------------------------------------------------------


class TestFileExtractorInit:
    """Tests for FileExtractor initialization."""

    def test_init_creates_screenshot_folder(self, temp_dir):
        folder = os.path.join(temp_dir, "new_folder")
        assert not os.path.exists(folder)
        extractor = FileExtractor(screenshot_folder=folder)
        assert os.path.exists(folder)
        assert extractor.screenshot_folder == folder

    def test_init_uses_default_folder(self):
        with patch("source.services.media.file_extractor.SCREENSHOT_FOLDER", "/default"):
            with patch("os.makedirs"):
                extractor = FileExtractor()
                assert extractor.screenshot_folder == "/default"


class TestFileExtractorExtract:
    """Tests for FileExtractor.extract() method."""

    async def test_extract_file_not_found(self, extractor):
        result = await extractor.extract("/nonexistent/file.txt")
        assert isinstance(result, str)
        assert "Error: File not found" in result

    async def test_extract_text_file(self, extractor, sample_text_file):
        result = await extractor.extract(sample_text_file)
        assert isinstance(result, str)
        assert "Hello, World!" in result
        assert "This is a test file." in result

    async def test_extract_image_file(self, extractor, sample_image_file):
        result = await extractor.extract(sample_image_file)
        assert isinstance(result, ImageResult)
        assert result.type == "image"
        assert result.media_type == "image/png"
        assert result.width == 100
        assert result.height == 100
        assert len(result.data) > 0

    async def test_extract_legacy_format_error(self, extractor, temp_dir):
        doc_path = os.path.join(temp_dir, "legacy.doc")
        with open(doc_path, "wb") as f:
            f.write(b"fake doc content")

        result = await extractor.extract(doc_path)
        assert isinstance(result, str)
        assert "Legacy format" in result
        assert ".docx" in result

    async def test_extract_unknown_format_attempts_text_read(self, extractor, temp_dir):
        unknown_path = os.path.join(temp_dir, "file.xyz")
        with open(unknown_path, "w", encoding="utf-8") as f:
            f.write("some content")

        result = await extractor.extract(unknown_path)
        assert isinstance(result, str)
        assert "Unknown file format" in result
        assert "some content" in result


class TestFileExtractorTextReading:
    """Tests for text file reading."""

    def test_read_text_file(self, extractor, sample_text_file):
        result = extractor._read_text_file(sample_text_file)
        assert "Hello, World!" in result

    def test_read_text_file_utf8(self, extractor, temp_dir):
        filepath = os.path.join(temp_dir, "unicode.txt")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("Hello \u4e16\u754c")  # Hello World in Chinese

        result = extractor._read_text_file(filepath)
        assert "\u4e16\u754c" in result

    def test_read_text_file_error(self, extractor):
        result = extractor._read_text_file("/nonexistent.txt")
        assert "Error reading file" in result

    def test_try_text_read_success(self, extractor, sample_text_file):
        result = extractor._try_text_read(sample_text_file)
        assert "Unknown file format" in result
        assert "Hello, World!" in result

    def test_try_text_read_failure(self, extractor):
        result = extractor._try_text_read("/nonexistent.xyz")
        assert "Error: Unable to read file" in result


class TestFileExtractorImageLoading:
    """Tests for image file loading."""

    def test_load_image_file_png(self, extractor, sample_image_file):
        result = extractor._load_image_file(sample_image_file)
        assert isinstance(result, ImageResult)
        assert result.type == "image"
        assert result.media_type == "image/png"
        assert result.width == 100
        assert result.height == 100
        assert result.file_size_bytes > 0

        # Verify base64 is valid
        decoded = base64.b64decode(result.data)
        assert len(decoded) > 0

    def test_load_image_file_jpeg(self, extractor, temp_dir):
        from PIL import Image

        filepath = os.path.join(temp_dir, "sample.jpg")
        img = Image.new("RGB", (200, 150), color="green")
        img.save(filepath, "JPEG")

        result = extractor._load_image_file(filepath)
        assert result.media_type == "image/jpeg"
        assert result.width == 200
        assert result.height == 150

    def test_load_image_file_error_returns_empty_result(self, extractor):
        result = extractor._load_image_file("/nonexistent.png")
        assert isinstance(result, ImageResult)
        assert result.data == ""
        assert result.width == 0
        assert result.height == 0


class TestFileExtractorFormatResult:
    """Tests for format_result_for_tool method."""

    def test_format_result_text_only(self, extractor):
        result = ExtractionResult(
            text="Sample extracted text",
            total_chars=21,
            page_count=1,
        )
        formatted = extractor.format_result_for_tool(result)
        assert formatted == "Sample extracted text"

    def test_format_result_with_images(self, extractor):
        img = ExtractedImage(
            path="/path/to/img.png",
            page=1,
            index=1,
            width=100,
            height=200,
            description="Page 1, Image 1",
        )
        result = ExtractionResult(
            text="Document text",
            total_chars=13,
            page_count=1,
            extracted_images=[img],
        )
        formatted = extractor.format_result_for_tool(result)
        assert formatted == "Document text"

    def test_format_result_with_warnings(self, extractor):
        result = ExtractionResult(
            text="Text",
            total_chars=4,
            page_count=1,
            warnings=["Warning 1", "Warning 2"],
        )
        formatted = extractor.format_result_for_tool(result)
        assert formatted == "Text"


# ------------------------------------------------------------------------------
# Test Document Extraction
# ------------------------------------------------------------------------------


class TestFileExtractorDocumentDispatch:
    """Tests for document extraction dispatch."""

    def test_extract_document_unknown_format(self, extractor):
        result = extractor._extract_document("/path/to/file.unknown", ".unknown")
        assert isinstance(result, ExtractionResult)
        assert "No extractor for format" in result.text
        assert len(result.warnings) > 0

    def test_extract_document_password_protected(self, extractor, temp_dir):
        # Simulate password-protected exception
        with patch.object(
            extractor, "_extract_pdf", side_effect=Exception("password required")
        ):
            pdf_path = os.path.join(temp_dir, "protected.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"fake pdf")

            result = extractor._extract_document(pdf_path, ".pdf")
            assert "password-protected" in result.text.lower()

    def test_extract_document_encrypted_error(self, extractor, temp_dir):
        with patch.object(
            extractor, "_extract_pdf", side_effect=Exception("encrypted content")
        ):
            pdf_path = os.path.join(temp_dir, "encrypted.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"fake pdf")

            result = extractor._extract_document(pdf_path, ".pdf")
            assert "password-protected" in result.text.lower()

    def test_extract_document_generic_error(self, extractor, temp_dir):
        with patch.object(
            extractor, "_extract_pdf", side_effect=Exception("some random error")
        ):
            pdf_path = os.path.join(temp_dir, "broken.pdf")
            with open(pdf_path, "wb") as f:
                f.write(b"fake pdf")

            result = extractor._extract_document(pdf_path, ".pdf")
            assert "Error extracting content" in result.text


class TestFileExtractorStructuredExtractors:
    """Tests for mocked document extractor branches."""

    def test_extract_pdf_collects_text_images_and_warnings(self, extractor, temp_dir):
        pdf_path = os.path.join(temp_dir, "report.pdf")
        with open(pdf_path, "wb") as f:
            f.write(b"%PDF-1.4")

        valid_image = _make_png_bytes((120, 120))
        oversized_image = b"x" * (file_extractor_module.MAX_EMBEDDED_IMAGE_BYTES + 1)
        broken_image = b"not-an-image"

        class FakePage:
            def __init__(self, text, images):
                self._text = text
                self._images = images

            def get_text(self):
                return self._text

            def get_images(self, full=True):
                assert full is True
                return self._images

        class FakeDoc:
            def __init__(self):
                self.metadata = {"title": "Quarterly Report", "author": "Ops"}
                self.closed = False
                self._pages = [
                    FakePage("Page one text", [(11,), (12,), (13,)]),
                    FakePage("   ", []),
                ]

            def __len__(self):
                return len(self._pages)

            def __iter__(self):
                return iter(self._pages)

            def extract_image(self, xref):
                return {
                    11: {"image": valid_image, "ext": "png"},
                    12: {"image": oversized_image, "ext": "png"},
                    13: {"image": broken_image, "ext": "png"},
                }[xref]

            def close(self):
                self.closed = True

        fake_doc = FakeDoc()
        fitz_module = ModuleType("fitz")
        fitz_module.open = lambda path: fake_doc

        saved_image = ExtractedImage(
            path=os.path.join(temp_dir, "saved.png"),
            page=1,
            index=1,
            width=120,
            height=120,
            description="Page 1, Image 1",
        )

        with (
            patch.dict(sys.modules, {"fitz": fitz_module}),
            patch.object(extractor, "_save_extracted_image", return_value=saved_image),
        ):
            result = extractor._extract_pdf(pdf_path)

        assert fake_doc.closed is True
        assert result.page_count == 2
        assert result.metadata is not None
        assert result.metadata.title == "Quarterly Report"
        assert result.metadata.author == "Ops"
        assert saved_image in result.extracted_images
        assert "--- Page 1 ---" in result.text
        assert "Page one text" in result.text
        assert "[No text content on this page]" in result.text
        assert extractor._format_inline_image_marker(saved_image) in result.text
        assert any("too large" in warning for warning in result.warnings)
        assert any("extraction failed" in warning for warning in result.warnings)

    def test_extract_docx_preserves_document_order_and_appends_unmapped_images(
        self, extractor, temp_dir
    ):
        docx_path = os.path.join(temp_dir, "report.docx")
        with open(docx_path, "wb") as f:
            f.write(b"docx")

        class FakeDocxElement:
            def __init__(self, tag, drawings=0):
                self.tag = tag
                self._drawings = drawings

            def xpath(self, _expr):
                return [object()] * self._drawings

        para_element = FakeDocxElement("w:p", drawings=1)
        table_element = FakeDocxElement("w:tbl")

        paragraph = SimpleNamespace(_element=para_element, text="Intro paragraph")
        header_row = SimpleNamespace(cells=[SimpleNamespace(text="Header"), SimpleNamespace(text="Value")])
        data_row = SimpleNamespace(cells=[SimpleNamespace(text="A"), SimpleNamespace(text="1")])
        table = SimpleNamespace(_element=table_element, rows=[header_row, data_row])

        image_one = SimpleNamespace(
            reltype="image/png",
            target_part=SimpleNamespace(
                blob=_make_png_bytes((120, 120)),
                content_type="image/png",
            ),
        )
        image_two = SimpleNamespace(
            reltype="image/png",
            target_part=SimpleNamespace(
                blob=_make_png_bytes((140, 140), color="blue"),
                content_type="image/png",
            ),
        )

        fake_doc = SimpleNamespace(
            core_properties=SimpleNamespace(
                title="Doc Title",
                author="Doc Author",
                created=datetime.datetime(2024, 1, 2, 3, 4, 5),
            ),
            paragraphs=[paragraph],
            tables=[table],
            part=SimpleNamespace(rels={"rId1": image_one, "rId2": image_two}),
            element=SimpleNamespace(body=[para_element, table_element]),
        )

        docx_module = ModuleType("docx")
        docx_module.Document = lambda path: fake_doc

        saved_images = [
            ExtractedImage(
                path=os.path.join(temp_dir, "img1.png"),
                page=None,
                index=1,
                width=120,
                height=120,
                description="Image 1",
            ),
            ExtractedImage(
                path=os.path.join(temp_dir, "img2.png"),
                page=None,
                index=2,
                width=140,
                height=140,
                description="Image 2",
            ),
        ]

        with (
            patch.dict(sys.modules, {"docx": docx_module}),
            patch.object(extractor, "_save_extracted_image", side_effect=saved_images),
        ):
            result = extractor._extract_docx(docx_path)

        assert result.metadata is not None
        assert result.metadata.format == "docx"
        assert result.metadata.title == "Doc Title"
        assert result.metadata.author == "Doc Author"
        assert result.metadata.created_at == "2024-01-02T03:04:05"
        assert result.extracted_images == saved_images
        assert "Intro paragraph" in result.text
        assert extractor._format_inline_image_marker(saved_images[0]) in result.text
        assert "| Header | Value |" in result.text
        assert extractor._format_inline_image_marker(saved_images[1]) in result.text

    def test_extract_xlsx_formats_rows_and_truncates(self, extractor, temp_dir):
        xlsx_path = os.path.join(temp_dir, "sheet.xlsx")
        with open(xlsx_path, "wb") as f:
            f.write(b"xlsx")

        class FakeSheet:
            def __init__(self, rows):
                self._rows = rows

            def iter_rows(self, values_only=True):
                assert values_only is True
                return iter(self._rows)

        class FakeWorkbook:
            def __init__(self):
                self.sheetnames = ["Summary", "Empty"]
                self.closed = False
                self._sheets = {
                    "Summary": FakeSheet([("alpha", 1), ("beta", 2)]),
                    "Empty": FakeSheet([(None, None)]),
                }

            def __getitem__(self, name):
                return self._sheets[name]

            def close(self):
                self.closed = True

        workbook = FakeWorkbook()
        openpyxl_module = ModuleType("openpyxl")
        openpyxl_module.load_workbook = lambda path, read_only, data_only: workbook

        with (
            patch.dict(sys.modules, {"openpyxl": openpyxl_module}),
            patch.object(file_extractor_module, "MAX_EXCEL_ROWS", 1),
        ):
            result = extractor._extract_xlsx(xlsx_path)

        assert workbook.closed is True
        assert result.metadata is not None
        assert result.metadata.format == "xlsx"
        assert result.metadata.sheet_names == ["Summary", "Empty"]
        assert "--- Sheet: Summary ---" in result.text
        assert "| alpha | 1 |" in result.text
        assert "[Empty sheet]" in result.text
        assert result.page_count == 2
        assert result.warnings == ["Sheet 'Summary': truncated at 1 rows"]

    def test_extract_xls_formats_rows_and_truncates(self, extractor, temp_dir):
        xls_path = os.path.join(temp_dir, "legacy.xls")
        with open(xls_path, "wb") as f:
            f.write(b"xls")

        class FakeSheet:
            def __init__(self, rows):
                self._rows = rows
                self.nrows = len(rows)

            def row_values(self, row_idx):
                return self._rows[row_idx]

        class FakeWorkbook:
            def __init__(self):
                self._sheets = {
                    "Summary": FakeSheet([["alpha", 1], ["beta", 2]]),
                    "Empty": FakeSheet([[None, None]]),
                }

            def sheet_names(self):
                return list(self._sheets.keys())

            def sheet_by_name(self, name):
                return self._sheets[name]

        xlrd_module = ModuleType("xlrd")
        xlrd_module.open_workbook = lambda path: FakeWorkbook()

        with (
            patch.dict(sys.modules, {"xlrd": xlrd_module}),
            patch.object(file_extractor_module, "MAX_EXCEL_ROWS", 1),
        ):
            result = extractor._extract_xls(xls_path)

        assert result.metadata is not None
        assert result.metadata.format == "xls"
        assert result.metadata.sheet_names == ["Summary", "Empty"]
        assert "| alpha | 1 |" in result.text
        assert "[Empty sheet]" in result.text
        assert result.page_count == 2
        assert result.warnings == ["Sheet 'Summary': truncated at 1 rows"]

    def test_extract_odf_reads_text_and_spreadsheet_cells(self, extractor, temp_dir):
        ods_path = os.path.join(temp_dir, "book.ods")
        with open(ods_path, "wb") as f:
            f.write(b"ods")

        class FakeTextNode:
            TEXT_NODE = 3

            def __init__(self, text):
                self.nodeType = self.TEXT_NODE
                self.childNodes = []
                self._text = text

            def __str__(self):
                return self._text

        class FakeElement:
            def __init__(self, child_nodes=None, attrs=None):
                self.nodeType = 1
                self.childNodes = child_nodes or []
                self._attrs = attrs or {}
                self._typed_children = {}

            def getElementsByType(self, type_):
                return self._typed_children.get(type_, [])

            def set_children(self, type_, children):
                self._typed_children[type_] = children
                return self

            def getAttribute(self, name):
                return self._attrs.get(name)

        text_module = ModuleType("odf.text")
        text_module.P = object()
        table_module = ModuleType("odf.table")
        table_module.Table = object()
        table_module.TableRow = object()
        table_module.TableCell = object()

        paragraph = FakeElement([FakeTextNode("First paragraph")])
        row = FakeElement().set_children(
            table_module.TableCell,
            [
                FakeElement([FakeTextNode("A1")]),
                FakeElement([FakeTextNode("B1")]),
            ],
        )
        table = FakeElement(attrs={"name": "Sheet1"}).set_children(
            table_module.TableRow,
            [row],
        )

        class FakeOdfDocument:
            def getElementsByType(self, type_):
                if type_ is text_module.P:
                    return [paragraph]
                if type_ is table_module.Table:
                    return [table]
                return []

        odf_module = ModuleType("odf")
        odf_module.text = text_module
        odf_module.table = table_module
        odf_open_document = ModuleType("odf.opendocument")
        odf_open_document.load = lambda path: FakeOdfDocument()

        with patch.dict(
            sys.modules,
            {
                "odf": odf_module,
                "odf.text": text_module,
                "odf.table": table_module,
                "odf.opendocument": odf_open_document,
            },
        ):
            result = extractor._extract_odf(ods_path, ".ods")

        assert result.metadata is not None
        assert result.metadata.format == "ods"
        assert "First paragraph" in result.text
        assert "--- Sheet: Sheet1 ---" in result.text
        assert "| A1 | B1 |" in result.text
        assert result.warnings == []

    def test_extract_pptx_collects_titles_text_and_images(self, extractor, temp_dir):
        pptx_path = os.path.join(temp_dir, "slides.pptx")
        with open(pptx_path, "wb") as f:
            f.write(b"pptx")

        picture_type = 99

        class FakeShapes(list):
            def __init__(self, shapes, title):
                super().__init__(shapes)
                self.title = title

        title_shape = SimpleNamespace(text="Quarterly Update")
        text_shape = SimpleNamespace(
            has_text_frame=True,
            text_frame=SimpleNamespace(
                paragraphs=[
                    SimpleNamespace(text="Quarterly Update"),
                    SimpleNamespace(text="Revenue grew 20%"),
                ]
            ),
            shape_type=None,
        )
        picture_shape = SimpleNamespace(
            has_text_frame=False,
            shape_type=picture_type,
            image=SimpleNamespace(blob=_make_png_bytes((150, 90)), ext="png"),
        )
        slide = SimpleNamespace(shapes=FakeShapes([text_shape, picture_shape], title_shape))
        fake_presentation = SimpleNamespace(
            core_properties=SimpleNamespace(
                title="Deck Title",
                author="Presenter",
                created=datetime.datetime(2024, 2, 3, 4, 5, 6),
            ),
            slides=[slide],
        )

        pptx_module = ModuleType("pptx")
        pptx_module.Presentation = lambda path: fake_presentation
        pptx_enum_module = ModuleType("pptx.enum")
        pptx_shapes_module = ModuleType("pptx.enum.shapes")
        pptx_shapes_module.MSO_SHAPE_TYPE = SimpleNamespace(PICTURE=picture_type)

        saved_image = ExtractedImage(
            path=os.path.join(temp_dir, "slide-image.png"),
            page=1,
            index=1,
            width=150,
            height=90,
            description="Page 1, Image 1",
        )

        with (
            patch.dict(
                sys.modules,
                {
                    "pptx": pptx_module,
                    "pptx.enum": pptx_enum_module,
                    "pptx.enum.shapes": pptx_shapes_module,
                },
            ),
            patch.object(extractor, "_save_extracted_image", return_value=saved_image),
        ):
            result = extractor._extract_pptx(pptx_path)

        assert result.metadata is not None
        assert result.metadata.format == "pptx"
        assert result.metadata.title == "Deck Title"
        assert result.metadata.author == "Presenter"
        assert result.metadata.created_at == "2024-02-03T04:05:06"
        assert result.page_count == 1
        assert "--- Slide 1: Quarterly Update ---" in result.text
        assert "Revenue grew 20%" in result.text
        assert result.text.count("Quarterly Update") == 1
        assert extractor._format_inline_image_marker(saved_image) in result.text
        assert result.extracted_images == [saved_image]

    def test_get_odf_text_recurses_into_nested_nodes(self, extractor):
        class FakeTextNode:
            TEXT_NODE = 3

            def __init__(self, text):
                self.nodeType = self.TEXT_NODE
                self.childNodes = []
                self._text = text

            def __str__(self):
                return self._text

        class FakeNode:
            TEXT_NODE = 3

            def __init__(self, child_nodes):
                self.nodeType = 1
                self.childNodes = child_nodes

        nested = FakeNode([FakeTextNode("Hello "), FakeNode([FakeTextNode("World")])])

        assert extractor._get_odf_text(nested) == "Hello World"


class TestFileExtractorPagination:
    """Tests for pagination helpers."""

    def test_build_file_info_maps_images_and_metadata(self, extractor):
        img = ExtractedImage(
            path="/tmp/extracted_img.png",
            page=2,
            index=1,
            width=120,
            height=80,
            description="Page 2, Image 1",
        )
        result = ExtractionResult(
            text="Body",
            total_chars=4,
            page_count=3,
            extracted_images=[img],
            metadata=ExtractionMetadata(
                format="pdf",
                file_size_bytes=2048,
                title="Quarterly Report",
                author="Finance Team",
            ),
            warnings=["minor warning"],
        )

        info = extractor.build_file_info(result)
        payload = info.to_dict()
        assert payload["format"] == "pdf"
        assert payload["file_size_bytes"] == 2048
        assert payload["page_count"] == 3
        assert payload["title"] == "Quarterly Report"
        assert payload["author"] == "Finance Team"
        assert payload["warnings"] == ["minor warning"]
        assert payload["extracted_images"][0]["path"] == "/tmp/extracted_img.png"
        assert payload["extracted_images"][0]["page"] == 2
        assert payload["extracted_images"][0]["width"] == 120

    def test_paginate_extraction_first_chunk_includes_file_info(self, extractor):
        result = ExtractionResult(
            text="abcdefghij",
            total_chars=10,
            page_count=1,
            metadata=ExtractionMetadata(format="txt", file_size_bytes=10),
        )

        page = extractor.paginate_extraction(result, offset=0, max_chars=4)
        assert page.content == "abcd"
        assert page.total_chars == 10
        assert page.offset == 0
        assert page.chars_returned == 4
        assert page.has_more is True
        assert page.next_offset == 4
        assert page.chunk_summary == "Showing characters 0-4 of 10 (40%)"
        assert page.file_info is not None
        assert page.file_info.format == "txt"

    def test_paginate_extraction_middle_chunk_omits_file_info(self, extractor):
        result = ExtractionResult(
            text="abcdefghij",
            total_chars=10,
            page_count=1,
            metadata=ExtractionMetadata(format="txt", file_size_bytes=10),
        )

        page = extractor.paginate_extraction(result, offset=4, max_chars=4)
        assert page.content == "efgh"
        assert page.offset == 4
        assert page.chars_returned == 4
        assert page.has_more is True
        assert page.next_offset == 8
        assert page.file_info is None

    def test_paginate_extraction_final_chunk(self, extractor):
        result = ExtractionResult(
            text="abcdefghij",
            total_chars=10,
            page_count=1,
            metadata=ExtractionMetadata(format="txt", file_size_bytes=10),
        )

        page = extractor.paginate_extraction(result, offset=8, max_chars=4)
        assert page.content == "ij"
        assert page.chars_returned == 2
        assert page.has_more is False
        assert page.next_offset is None
        assert page.chunk_summary == "Showing characters 8-10 of 10 (100%)"

    def test_paginate_extraction_offset_beyond_eof(self, extractor):
        result = ExtractionResult(
            text="abc",
            total_chars=3,
            page_count=1,
            metadata=ExtractionMetadata(format="txt", file_size_bytes=3),
        )

        page = extractor.paginate_extraction(result, offset=10, max_chars=4)
        assert page.content == ""
        assert page.chars_returned == 0
        assert page.has_more is False
        assert page.next_offset is None
        assert "beyond end of file" in page.chunk_summary

    def test_paginate_extraction_negative_offset_treated_as_zero(self, extractor):
        result = ExtractionResult(
            text="abcdef",
            total_chars=6,
            page_count=1,
            metadata=ExtractionMetadata(format="txt", file_size_bytes=6),
        )

        page = extractor.paginate_extraction(result, offset=-5, max_chars=2)
        assert page.offset == 0
        assert page.content == "ab"

    def test_paginate_extraction_non_positive_max_chars_uses_default(self, extractor):
        result = ExtractionResult(
            text="abcdefghij",
            total_chars=10,
            page_count=1,
            metadata=ExtractionMetadata(format="txt", file_size_bytes=10),
        )
        page = extractor.paginate_extraction(result, offset=0, max_chars=0)

        assert page.content == "abcdefghij"
        assert page.chars_returned == 10

    def test_paginate_extraction_empty_file(self, extractor):
        result = ExtractionResult(
            text="",
            total_chars=0,
            page_count=0,
            metadata=ExtractionMetadata(format="txt", file_size_bytes=0),
        )

        page = extractor.paginate_extraction(result, offset=0, max_chars=100)
        assert page.content == ""
        assert page.total_chars == 0
        assert page.chars_returned == 0
        assert page.has_more is False
        assert page.next_offset is None
        assert page.chunk_summary == "Showing characters 0-0 of 0 (100%)"
        assert page.file_info is not None

    def test_paginate_text_first_chunk_has_file_info(self, extractor):
        page = extractor.paginate_text(
            text="0123456789",
            file_size_bytes=10,
            file_format="py",
            offset=0,
            max_chars=4,
        )
        assert page.content == "0123"
        assert page.total_chars == 10
        assert page.has_more is True
        assert page.next_offset == 4
        assert page.file_info is not None
        assert page.file_info.format == "py"
        assert page.file_info.file_size_bytes == 10

    def test_paginate_text_later_chunk_omits_file_info(self, extractor):
        page = extractor.paginate_text(
            text="0123456789",
            file_size_bytes=10,
            file_format="py",
            offset=4,
            max_chars=4,
        )
        assert page.content == "4567"
        assert page.file_info is None

    def test_paginate_text_offset_beyond_eof(self, extractor):
        page = extractor.paginate_text(
            text="abc",
            file_size_bytes=3,
            file_format="txt",
            offset=9,
            max_chars=4,
        )
        assert page.content == ""
        assert page.has_more is False
        assert page.next_offset is None
        assert "beyond end of file" in page.chunk_summary

    def test_paginate_text_empty_file(self, extractor):
        page = extractor.paginate_text(
            text="",
            file_size_bytes=0,
            file_format="txt",
            offset=0,
            max_chars=4,
        )
        assert page.content == ""
        assert page.total_chars == 0
        assert page.has_more is False
        assert page.chunk_summary == "Showing characters 0-0 of 0 (100%)"
        assert page.file_info is not None

    def test_inline_image_marker_uses_absolute_path(self, extractor):
        img = ExtractedImage(
            path="/tmp/extracted_report_p15_i1_a1b2.png",
            page=15,
            index=1,
            width=1200,
            height=800,
            description="Page 15, Image 1",
        )

        marker = extractor._format_inline_image_marker(img)
        assert marker == (
            "[IMAGE: /tmp/extracted_report_p15_i1_a1b2.png "
            "(1200x800) - call read_file to view]"
        )


class TestFileExtractorRTF:
    """Tests for RTF extraction."""

    def test_extract_rtf(self, extractor, temp_dir):
        rtf_path = os.path.join(temp_dir, "sample.rtf")
        rtf_content = r"{\rtf1\ansi Hello RTF World}"
        with open(rtf_path, "w", encoding="utf-8") as f:
            f.write(rtf_content)

        result = extractor._extract_rtf(rtf_path)
        assert isinstance(result, ExtractionResult)
        assert result.metadata is not None
        assert result.metadata.format == "rtf"
        assert result.metadata.file_size_bytes > 0


class TestFileExtractorZIP:
    """Tests for ZIP extraction."""

    def test_extract_zip(self, extractor, temp_dir):
        import zipfile

        zip_path = os.path.join(temp_dir, "archive.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("file1.txt", "content1")
            zf.writestr("subdir/file2.txt", "content2")

        result = extractor._extract_zip(zip_path)
        assert isinstance(result, ExtractionResult)
        assert result.metadata is not None
        assert "ZIP Archive Contents" in result.text
        assert "file1.txt" in result.text
        assert "subdir/file2.txt" in result.text
        assert "Total files: 2" in result.text
        assert result.metadata.format == "zip"

    def test_extract_zip_bad_file(self, extractor, temp_dir):
        bad_zip_path = os.path.join(temp_dir, "bad.zip")
        with open(bad_zip_path, "wb") as f:
            f.write(b"not a real zip file")

        result = extractor._extract_zip(bad_zip_path)
        assert isinstance(result, ExtractionResult)
        assert "Invalid" in result.text or "corrupted" in result.text.lower()
        assert len(result.warnings) > 0


# ------------------------------------------------------------------------------
# Test Image Saving
# ------------------------------------------------------------------------------


class TestFileExtractorImageSaving:
    """Tests for image saving helper."""

    def test_save_extracted_image(self, extractor, temp_dir):
        from PIL import Image

        pil_img = Image.new("RGB", (100, 100), color="red")
        saved = extractor._save_extracted_image(
            pil_img=pil_img,
            source_stem="document",
            page=1,
            index=1,
            ext="png",
        )

        assert saved is not None
        assert isinstance(saved, ExtractedImage)
        # Use realpath for comparison since the saved path is canonicalized
        assert saved.path.startswith(os.path.realpath(temp_dir))
        assert EXTRACTED_IMAGE_PREFIX in saved.path
        assert os.path.exists(saved.path)
        assert saved.page == 1
        assert saved.index == 1
        assert saved.width == 100
        assert saved.height == 100
        assert "Page 1" in saved.description

    def test_save_extracted_image_no_page(self, extractor, temp_dir):
        from PIL import Image

        pil_img = Image.new("RGB", (50, 50), color="blue")
        saved = extractor._save_extracted_image(
            pil_img=pil_img,
            source_stem="image",
            page=None,
            index=3,
            ext="png",
        )

        assert saved is not None
        assert saved.page is None
        assert "Image 3" in saved.description
        assert "Page" not in saved.description

    def test_save_extracted_image_rgba_to_jpg(self, extractor, temp_dir):
        from PIL import Image

        pil_img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        saved = extractor._save_extracted_image(
            pil_img=pil_img,
            source_stem="test",
            page=1,
            index=1,
            ext="jpg",
        )

        assert saved is not None
        # JPEG doesn't support alpha, so it should be converted
        with Image.open(saved.path) as loaded:
            assert loaded.mode == "RGB"


# ------------------------------------------------------------------------------
# Test Cleanup
# ------------------------------------------------------------------------------


class TestFileExtractorCleanup:
    """Tests for cleanup_extracted_images static method."""

    def test_cleanup_removes_old_extracted_images(self, temp_dir):
        # Create old extracted image
        old_file = os.path.join(temp_dir, f"{EXTRACTED_IMAGE_PREFIX}old.png")
        with open(old_file, "w") as f:
            f.write("old")

        # Set modification time to 25 hours ago
        old_time = time.time() - (25 * 3600)
        os.utime(old_file, (old_time, old_time))

        # Create recent extracted image
        new_file = os.path.join(temp_dir, f"{EXTRACTED_IMAGE_PREFIX}new.png")
        with open(new_file, "w") as f:
            f.write("new")

        # Run cleanup
        removed = FileExtractor.cleanup_extracted_images(
            screenshot_folder=temp_dir, max_age_hours=24
        )

        assert removed == 1
        assert not os.path.exists(old_file)
        assert os.path.exists(new_file)

    def test_cleanup_removes_all_with_zero_max_age(self, temp_dir):
        # Create extracted images
        file1 = os.path.join(temp_dir, f"{EXTRACTED_IMAGE_PREFIX}1.png")
        file2 = os.path.join(temp_dir, f"{EXTRACTED_IMAGE_PREFIX}2.png")
        with open(file1, "w") as f:
            f.write("1")
        with open(file2, "w") as f:
            f.write("2")

        removed = FileExtractor.cleanup_extracted_images(
            screenshot_folder=temp_dir, max_age_hours=0
        )

        assert removed == 2
        assert not os.path.exists(file1)
        assert not os.path.exists(file2)

    def test_cleanup_ignores_non_extracted_files(self, temp_dir):
        # Create non-extracted file
        regular_file = os.path.join(temp_dir, "regular_screenshot.png")
        with open(regular_file, "w") as f:
            f.write("regular")

        removed = FileExtractor.cleanup_extracted_images(
            screenshot_folder=temp_dir, max_age_hours=0
        )

        assert removed == 0
        assert os.path.exists(regular_file)

    def test_cleanup_nonexistent_folder(self):
        removed = FileExtractor.cleanup_extracted_images(
            screenshot_folder="/nonexistent/folder", max_age_hours=0
        )
        assert removed == 0

    def test_cleanup_uses_default_folder(self):
        with patch("source.services.media.file_extractor.SCREENSHOT_FOLDER", "/default"):
            with patch("os.path.exists", return_value=False):
                removed = FileExtractor.cleanup_extracted_images()
                assert removed == 0

    def test_cleanup_continues_when_stat_fails_for_one_file(self, temp_dir):
        stale_file = os.path.join(temp_dir, f"{EXTRACTED_IMAGE_PREFIX}stale.png")
        blocked_file = os.path.join(temp_dir, f"{EXTRACTED_IMAGE_PREFIX}blocked.png")
        with open(stale_file, "w", encoding="utf-8") as f:
            f.write("stale")
        with open(blocked_file, "w", encoding="utf-8") as f:
            f.write("blocked")

        old_time = time.time() - (25 * 3600)
        os.utime(stale_file, (old_time, old_time))

        real_getmtime = os.path.getmtime

        def fake_getmtime(path):
            if path == blocked_file:
                raise OSError("stat failed")
            return real_getmtime(path)

        with patch("source.services.media.file_extractor.os.path.getmtime", side_effect=fake_getmtime):
            removed = FileExtractor.cleanup_extracted_images(
                screenshot_folder=temp_dir, max_age_hours=24
            )

        assert removed == 1
        assert not os.path.exists(stale_file)
        assert os.path.exists(blocked_file)


# ------------------------------------------------------------------------------
# Test Format Table Helper
# ------------------------------------------------------------------------------


class TestFileExtractorFormatTable:
    """Tests for _format_table helper method."""

    def test_format_table(self, extractor):
        # Create a mock table
        mock_cell1 = MagicMock()
        mock_cell1.text = "Header 1"
        mock_cell2 = MagicMock()
        mock_cell2.text = "Header 2"
        mock_row1 = MagicMock()
        mock_row1.cells = [mock_cell1, mock_cell2]

        mock_cell3 = MagicMock()
        mock_cell3.text = "Value 1"
        mock_cell4 = MagicMock()
        mock_cell4.text = "Value 2"
        mock_row2 = MagicMock()
        mock_row2.cells = [mock_cell3, mock_cell4]

        mock_table = MagicMock()
        mock_table.rows = [mock_row1, mock_row2]

        result = extractor._format_table(mock_table)
        lines = result.split("\n")
        assert len(lines) == 3
        assert "Header 1" in lines[0]
        assert "Header 2" in lines[0]
        assert "---" in lines[1]
        assert "Value 1" in lines[2]
        assert "Value 2" in lines[2]


# ------------------------------------------------------------------------------
# Integration-style Tests
# ------------------------------------------------------------------------------


class TestFileExtractorIntegration:
    """Integration-style tests for full extraction flow."""

    async def test_extract_and_format_flow(self, extractor, sample_text_file):
        """Test the full flow of extracting and formatting."""
        result = await extractor.extract(sample_text_file)

        # Text file returns string directly
        assert isinstance(result, str)
        assert "Hello, World!" in result

    async def test_extract_image_and_check_base64(self, extractor, sample_image_file):
        """Test image extraction produces valid base64."""
        result = await extractor.extract(sample_image_file)

        assert isinstance(result, ImageResult)
        # Verify base64 can be decoded back to image
        decoded = base64.b64decode(result.data)
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(decoded))
        assert img.size == (100, 100)
