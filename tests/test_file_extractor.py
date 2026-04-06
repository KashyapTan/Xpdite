"""Tests for source/services/media/file_extractor.py"""

import base64
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

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
