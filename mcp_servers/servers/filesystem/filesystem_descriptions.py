import os
from pathlib import Path

# --- Configuration (dynamic — works on any machine / OS) ---
USERNAME = os.getenv("USERNAME") or os.getenv("USER") or Path.home().name
BASE_PATH = os.path.abspath(str(Path.home()))


LIST_DIRECTORY_DESCRIPTION = f"""
**PRIMARY DISCOVERY TOOL - MUST BE CALLED FIRST**
Inspects a directory to understand the file structure.

MANDATORY WORKFLOW:
You MUST call this tool before using `read_file`, `write_file`, `move_file`, or `rename_file` to verify paths exist and prevent hallucinated file locations.

Use this tool to:
1. Explore the folder layout when you are unsure where files are located.
2. Find specific resources (images, text files, code, logs) by name or extension.
3. Validate paths before attempting to read or write.

CURRENT CONTEXT:
- Username: {USERNAME}
- Base Path: {BASE_PATH}
"""

READ_FILE_DESCRIPTION = f"""
Reads the content of a file.

PREREQUISITES:
1. **Call `list_directory` FIRST** to verify the file exists and get the exact path. Do not guess paths.

Use this tool to:
1. Analyze text documents, code files, logs, or configuration files.
2. Retrieve context required to answer the user's question.
3. Verify the current state of a file before making edits (see `write_file`).

If the file is large, consider reading it in chunks or summarizing it (if your capabilities allow).

CURRENT CONTEXT:
- Username: {USERNAME}
- Base Path: {BASE_PATH}
"""

WRITE_FILE_DESCRIPTION = f"""
Writes content to a specific file path.

PREREQUISITES:
1. **Call `list_directory` FIRST** to verify the target directory exists and check for filename conflicts.
2. **Call `read_file` FIRST** if you are editing an existing file. You must know the current content to ensure you do not overwrite important data accidentally.

Use this tool to:
1. Create new files (e.g., notes, scripts, reports, config files).
2. Overwrite existing files with updated content.

CRITICAL SAFETY RULES:
- If the file already exists, this tool will OVERWRITE it completely.
- Confirm the directory exists before writing.

NOTE: If you are writing code to a file, dont use backticks or markdown formatting in the content. Just write the raw code as it should appear in the file.

CURRENT CONTEXT:
- Username: {USERNAME}
- Base Path: {BASE_PATH}
"""

CREATE_FOLDER_DESCRIPTION = f"""
Creates a new directory (folder) with a specific 'folder_name' INSIDE the directory specified by 'path'.

PREREQUISITES:
1. **Call `list_directory` FIRST** to verify the PARENT path where you intend to create the new folder.

CRITICAL ARGUMENT RULES:
- `path`: The **PARENT** directory. Do NOT include the new folder name here.
- `folder_name`: The name of the new folder only.

Use this tool to:
1. Set up new project structures or workspaces.
2. Create categories for organizing files (e.g., "make a 'Photos' folder").

CURRENT CONTEXT:
- Username: {USERNAME}
- Base Path: {BASE_PATH}
"""

MOVE_FILE_DESCRIPTION = f"""
Moves a file or directory from one location to another.

PREREQUISITES:
1. **Call `list_directory` FIRST** to confirm the `source_path` exists.
2. **Call `list_directory` on the destination** to confirm the `destination_folder` exists.

Use this tool to:
1. Organize files by transferring them into appropriate subfolders.
2. Relocate entire directories to new parent folders.

CRITICAL SAFETY RULES:
- Strictly for changing locations, NOT for renaming files in place.
- If a file with the same name exists in the destination, check system settings first.

CURRENT CONTEXT:
- Username: {USERNAME}
- Base Path: {BASE_PATH}
"""

RENAME_FILE_DESCRIPTION = f"""
Renames a file or directory without moving it.

PREREQUISITES:
1. **Call `list_directory` FIRST** to confirm the `source_path` exists.
2. **Call `list_directory`** to ensure the `new_name` does not already exist in that location (to avoid overwrite errors).

Use this tool to:
1. Fix typos in filenames.
2. Update naming conventions (e.g., 'data.csv' -> '2023_data.csv').
3. Change file extensions.

CRITICAL SAFETY RULES:
- The 'new_name' must be a filename only, not a path.

CURRENT CONTEXT:
- Username: {USERNAME}
- Base Path: {BASE_PATH}
"""