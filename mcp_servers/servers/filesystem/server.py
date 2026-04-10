import os
import shutil
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_servers.servers.filesystem.filesystem_descriptions import (
    CREATE_FOLDER_DESCRIPTION,
    LIST_DIRECTORY_DESCRIPTION,
    MOVE_FILE_DESCRIPTION,
    READ_FILE_DESCRIPTION,
    RENAME_FILE_DESCRIPTION,
    WRITE_FILE_DESCRIPTION,
)
from mcp_servers.servers.filesystem.sandbox import (
    DEFAULT_BASE_PATH,
    get_safe_path,
)

# File extraction imports (lazy loaded to avoid import overhead if not used)
_file_extractor = None


def _get_file_extractor():
    """Lazy-load the file extractor to avoid import overhead."""
    global _file_extractor
    if _file_extractor is None:
        from source.services.media.file_extractor import FileExtractor

        _file_extractor = FileExtractor()
    return _file_extractor


# File extension sets for routing
_IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
    }
)

_EXTRACTION_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".xlsx",
        ".xlsm",
        ".xls",
        ".odt",
        ".odp",
        ".ods",
        ".rtf",
    }
)

_ARCHIVE_EXTENSIONS = frozenset({".zip"})

_LEGACY_UNSUPPORTED = frozenset({".doc", ".ppt"})

mcp = FastMCP("Filesystem Tools")

BASE_PATH = DEFAULT_BASE_PATH


def _get_safe_path(path: str) -> str:
    return get_safe_path(path, BASE_PATH)


@mcp.tool(description=LIST_DIRECTORY_DESCRIPTION)
def list_directory(path: str) -> list[str]:
    try:
        clean_path = _get_safe_path(path)
        # Use os.scandir for efficiency (avoids repeated stat calls)
        entries_with_mtime: list[tuple[str, float]] = []
        with os.scandir(clean_path) as it:
            for entry in it:
                try:
                    # DirEntry.stat() caches stat info, much faster than os.stat()
                    mtime = entry.stat().st_mtime
                    entries_with_mtime.append((entry.name, mtime))
                except (OSError, PermissionError):
                    # Skip entries we can't stat
                    continue
        # Sort by mtime descending (most recent first)
        entries_with_mtime.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in entries_with_mtime][:50]

    except FileNotFoundError:
        return [f"Error: The directory '{path}' does not exist."]

    except PermissionError as e:
        return [f"Error: {str(e)}"]

    except NotADirectoryError:
        return [
            f"Error: '{path}' is a file, not a directory. Use read_file to view it."
        ]

    except Exception as e:
        return [f"Error: An unexpected error occurred: {str(e)}"]


@mcp.tool(description=READ_FILE_DESCRIPTION)
def read_file(
    path: str, offset: int = 0, max_chars: int = 8000
) -> str | dict[str, Any]:
    """
    Read file content with support for multiple formats and pagination.

    Args:
        path: File path to read
        offset: Character position to start reading from (0-indexed)
        max_chars: Maximum characters to return (default 8000, max 100000)

    Returns:
        - dict: Paginated result envelope with content, total_chars, has_more, etc.
        - dict: For image files, returns {"type": "image", "media_type": ..., "data": ..., ...}
        - str: Error messages only
    """
    from source.infrastructure.config import DEFAULT_READ_FILE_MAX_CHARS, MAX_TOOL_RESULT_LENGTH

    # Normalize parameters
    if offset < 0:
        offset = 0
    if max_chars <= 0:
        max_chars = DEFAULT_READ_FILE_MAX_CHARS
    max_chars = min(max_chars, MAX_TOOL_RESULT_LENGTH)

    try:
        clean_path = _get_safe_path(path)
        ext = Path(clean_path).suffix.lower()
        file_size = os.path.getsize(clean_path)

        # Image files - return dict for LLM image content block
        # Images cannot be paginated - they are always returned whole
        if ext in _IMAGE_EXTENSIONS:
            if offset > 0:
                return "Error: Image files cannot be paginated. Remove the offset parameter to read the full image."
            extractor = _get_file_extractor()
            result = extractor._load_image_file(clean_path)
            if result.data:
                return result.to_dict()
            return f"Error: Failed to load image '{path}'"

        # Legacy unsupported formats - return actionable error
        if ext in _LEGACY_UNSUPPORTED:
            return (
                f"Error: Legacy format '{ext}' is not supported. "
                "Please resave as .docx or .pptx for Word/PowerPoint documents."
            )

        # Document formats requiring extraction
        if ext in _EXTRACTION_EXTENSIONS:
            extractor = _get_file_extractor()
            extraction_result = extractor._extract_document(clean_path, ext)
            paginated = extractor.paginate_extraction(
                extraction_result, offset=offset, max_chars=max_chars
            )
            return paginated.to_dict()

        # Archive files - list contents (also paginated)
        if ext in _ARCHIVE_EXTENSIONS:
            extractor = _get_file_extractor()
            extraction_result = extractor._extract_zip(clean_path)
            paginated = extractor.paginate_extraction(
                extraction_result, offset=offset, max_chars=max_chars
            )
            return paginated.to_dict()

        # Text-native and unknown formats
        extractor = _get_file_extractor()
        if extractor.is_text_native(clean_path):
            with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
                text_result = f.read()
        else:
            with open(clean_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            text_result = (
                f"[Warning: Unknown file format, attempting text read]\n\n{content}"
            )

        # Determine file format from extension
        file_format = ext.lstrip(".") if ext else "txt"

        paginated = extractor.paginate_text(
            text=text_result,
            file_size_bytes=file_size,
            file_format=file_format,
            offset=offset,
            max_chars=max_chars,
        )
        return paginated.to_dict()

    except FileNotFoundError:
        return f"Error: The file '{path}' was not found. Please check the path using list_directory."

    except PermissionError as e:
        return f"Error: {str(e)}"

    except IsADirectoryError:
        return f"Error: '{path}' is a directory, not a file. Use list_directory to see its contents."

    except Exception as e:
        return f"Error: An unexpected error occurred reading '{path}': {str(e)}"


@mcp.tool(description=WRITE_FILE_DESCRIPTION)
def write_file(path: str, content: str) -> str:
    try:
        clean_path = _get_safe_path(path)
        parent_dir = os.path.dirname(clean_path)
        if not os.path.exists(parent_dir):
            return f"Error: The directory '{parent_dir}' does not exist. Please use create_folder first."

        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Success: Successfully wrote {len(content)} characters to '{path}'."

    except PermissionError as e:
        return f"Error: {str(e)}"

    except IsADirectoryError:
        return f"Error: '{path}' is a directory. You cannot write content to a directory path."

    except OSError as e:
        return f"Error: System error while writing to '{path}': {str(e)}"

    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool(description=CREATE_FOLDER_DESCRIPTION)
def create_folder(path: str, folder_name: str) -> str:
    try:
        full_path = os.path.join(path, folder_name)
        clean_path = _get_safe_path(full_path)

        if os.path.exists(clean_path):
            return f"Error: The folder '{folder_name}' already exists at '{path}'."

        os.makedirs(clean_path)
        return f"Success: Folder '{folder_name}' created successfully at '{path}'."

    except PermissionError as e:
        return f"Error: Permission denied. {str(e)}"

    except OSError as e:
        return f"Error: System error while creating folder '{folder_name}': {str(e)}"

    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool(description=MOVE_FILE_DESCRIPTION)
def move_file(source_path: str, destination_folder: str) -> str:
    try:
        clean_source = _get_safe_path(source_path)
        clean_dest_folder = _get_safe_path(destination_folder)

        if not os.path.exists(clean_source):
            return f"Error: The source path '{source_path}' does not exist."

        if not os.path.isdir(clean_dest_folder):
            return f"Error: The destination '{destination_folder}' is not a valid directory."

        filename = os.path.basename(clean_source)
        clean_full_destination = os.path.join(clean_dest_folder, filename)
        clean_full_destination = _get_safe_path(clean_full_destination)

        if os.path.exists(clean_full_destination):
            return f"Error: A file already exists at '{clean_full_destination}'. Move aborted."

        shutil.move(clean_source, clean_full_destination)
        return f"Success: Moved '{filename}' to '{destination_folder}'."

    except PermissionError as e:
        return f"Error: Permission denied. {str(e)}"

    except OSError as e:
        return f"Error: System error while moving file: {str(e)}"

    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"


@mcp.tool(description=RENAME_FILE_DESCRIPTION)
def rename_file(source_path: str, new_name: str) -> str:
    try:
        if os.sep in new_name or (os.altsep and os.altsep in new_name):
            return f"Error: 'new_name' must be a filename only, not a path. separators ('{os.sep}') are not allowed."

        clean_source = _get_safe_path(source_path)
        if not os.path.exists(clean_source):
            return f"Error: The source path '{source_path}' does not exist."

        parent_dir = os.path.dirname(clean_source)
        clean_new_path = os.path.join(parent_dir, new_name)
        clean_new_path = _get_safe_path(clean_new_path)

        if os.path.exists(clean_new_path):
            return f"Error: A file already exists with the name '{new_name}' in this directory. Rename aborted."

        os.rename(clean_source, clean_new_path)
        return f"Success: Renamed '{os.path.basename(source_path)}' to '{new_name}'."

    except PermissionError as e:
        return f"Error: Permission denied. {str(e)}"

    except OSError as e:
        return f"Error: System error while renaming file: {str(e)}"

    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"


if __name__ == "__main__":
    mcp.run()
