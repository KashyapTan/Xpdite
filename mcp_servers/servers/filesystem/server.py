import os
import shutil
from mcp.server.fastmcp import FastMCP

from mcp_servers.servers.filesystem.filesystem_descriptions import (
    BASE_PATH,
    LIST_DIRECTORY_DESCRIPTION, READ_FILE_DESCRIPTION, 
    WRITE_FILE_DESCRIPTION, CREATE_FOLDER_DESCRIPTION, 
    MOVE_FILE_DESCRIPTION, RENAME_FILE_DESCRIPTION,
)

mcp = FastMCP("Filesystem Tools")

# --- Security Helper ---
def _get_safe_path(path: str) -> str:
    """
    Security Helper: Resolves the path and ensures it stays within BASE_PATH.
    Prevents path traversal and Symlink attacks.
    """
    # 1. Expand user (~/...) 
    expanded_path = os.path.expanduser(path)

    # 2. Resolve absolute path AND symlinks
    # os.path.realpath is crucial: it follows symlinks to their final destination.
    target_path = os.path.realpath(expanded_path)
    
    # Ensure BASE_PATH is also fully resolved to compare apples to apples
    safe_base = os.path.realpath(BASE_PATH)

    # 3. Check if the target path starts with the allowed BASE_PATH
    if safe_base != os.path.commonpath([safe_base, target_path]):
        raise PermissionError(f"Access denied: Path '{path}' resolves outside the allowed directory.")
    
    return target_path

# ------------------------------------------------------------------
# 1. List Directory Tool
# ------------------------------------------------------------------
@mcp.tool(description=LIST_DIRECTORY_DESCRIPTION)
def list_directory(path: str) -> list[str]:
    try:
        # Use the safe path helper to prevent access outside BASE_PATH
        clean_path = _get_safe_path(path)
        
        # Get all entries in the directory
        entries = os.listdir(clean_path)
        
        # Create full paths to check mtime
        # We filter for os.path.exists to avoid crashing if a temp file disappears
        full_paths = [
            os.path.join(clean_path, entry) 
            for entry in entries 
            if os.path.exists(os.path.join(clean_path, entry))
        ]
        
        # Sort by modification time (latest first)
        full_paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        
        # Return just the filenames (relative to the listed directory)
        return [os.path.basename(p) for p in full_paths][0:50] # Get the 50 most recent files/folders

    except FileNotFoundError:
        return [f"Error: The directory '{path}' does not exist."]
    
    except PermissionError as e:
        return [f"Error: {str(e)}"]
    
    except NotADirectoryError:
        return [f"Error: '{path}' is a file, not a directory. Use read_file to view it."]
        
    except Exception as e:
        return [f"Error: An unexpected error occurred: {str(e)}"]


# ------------------------------------------------------------------
# 2. Read Tool
# ------------------------------------------------------------------
@mcp.tool(description=READ_FILE_DESCRIPTION)
def read_file(path: str) -> str:
    try:
        clean_path = _get_safe_path(path)

        # 'errors="replace"' handles non-utf8 files without crashing
        with open(clean_path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()
            
    except FileNotFoundError:
        return f"Error: The file '{path}' was not found. Please check the path using list_directory."
    
    except PermissionError as e:
        return f"Error: {str(e)}"
    
    except IsADirectoryError:
        return f"Error: '{path}' is a directory, not a file. Use list_directory to see its contents."
        
    except Exception as e:
        return f"Error: An unexpected error occurred reading '{path}': {str(e)}"

# ------------------------------------------------------------------
# 3. Write File Tool
# ------------------------------------------------------------------
@mcp.tool(description=WRITE_FILE_DESCRIPTION)
def write_file(path: str, content: str) -> str:
    try:
        clean_path = _get_safe_path(path)
        
        # Check if the parent directory exists
        parent_dir = os.path.dirname(clean_path)
        if not os.path.exists(parent_dir):
            return f"Error: The directory '{parent_dir}' does not exist. Please use create_folder first."

        # Write the content
        with open(clean_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        return f"Success: Successfully wrote {len(content)} characters to '{path}'."

    except PermissionError as e:
        return f"Error: {str(e)}"
        
    except IsADirectoryError:
        return f"Error: '{path}' is a directory. You cannot write content to a directory path."
        
    except OSError as e:
        # Handles specific OS-level write errors (like disk full)
        return f"Error: System error while writing to '{path}': {str(e)}"
        
    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"

# ------------------------------------------------------------------
# 4. Create Folder Tool
# ------------------------------------------------------------------
@mcp.tool(description=CREATE_FOLDER_DESCRIPTION)
def create_folder(path: str, folder_name: str) -> str:
    try:
        # Combine the parent path and the new folder name
        full_path = os.path.join(path, folder_name)
        
        # secure the full path
        clean_path = _get_safe_path(full_path)
        
        # Check if the specific folder already exists
        if os.path.exists(clean_path):
            return f"Error: The folder '{folder_name}' already exists at '{path}'."
        
        # Create the folder
        os.makedirs(clean_path)
        return f"Success: Folder '{folder_name}' created successfully at '{path}'."

    except PermissionError as e:
        return f"Error: Permission denied. {str(e)}"
        
    except OSError as e:
        return f"Error: System error while creating folder '{folder_name}': {str(e)}"
        
    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"

# ------------------------------------------------------------------
# 5. Move File Tool
# ------------------------------------------------------------------
@mcp.tool(description=MOVE_FILE_DESCRIPTION)
def move_file(source_path: str, destination_folder: str) -> str:
    try:
        # 1. Secure the source path immediately
        clean_source = _get_safe_path(source_path)
        
        # 2. Secure the destination folder
        # We process the folder first to make sure it exists and is safe
        clean_dest_folder = _get_safe_path(destination_folder)

        # 3. Existence Checks
        if not os.path.exists(clean_source):
            return f"Error: The source path '{source_path}' does not exist."
            
        # Verify destination is actually a directory
        if not os.path.isdir(clean_dest_folder):
             return f"Error: The destination '{destination_folder}' is not a valid directory."

        # 4. Construct final destination path
        filename = os.path.basename(clean_source)
        clean_full_destination = os.path.join(clean_dest_folder, filename)

        # Double check: Ensure the final constructed path is still safe 
        # (This is defensive depth in case the filename contains weird characters)
        clean_full_destination = _get_safe_path(clean_full_destination)

        # 5. Prevent overwriting existing files (Optional but recommended safety)
        if os.path.exists(clean_full_destination):
            return f"Error: A file already exists at '{clean_full_destination}'. Move aborted."

        # 6. Move the file
        # shutil.move is more robust than os.rename for cross-filesystem moves
        shutil.move(clean_source, clean_full_destination)
        
        return f"Success: Moved '{filename}' to '{destination_folder}'."

    except PermissionError as e:
        return f"Error: Permission denied. {str(e)}"
        
    except OSError as e:
        return f"Error: System error while moving file: {str(e)}"
        
    except Exception as e:
        return f"Error: An unexpected error occurred: {str(e)}"
    
# ------------------------------------------------------------------
# 6. Rename File Tool
# ------------------------------------------------------------------
@mcp.tool(description=RENAME_FILE_DESCRIPTION)
def rename_file(source_path: str, new_name: str) -> str:
    try:
        # Prevent the user from supplying a path like "../newname.txt"
        if os.sep in new_name or (os.altsep and os.altsep in new_name):
            return f"Error: 'new_name' must be a filename only, not a path. separators ('{os.sep}') are not allowed."
        
        # 1. Secure the source path immediately
        clean_source = _get_safe_path(source_path)

        # 2. Check if source exists
        if not os.path.exists(clean_source):
            return f"Error: The source path '{source_path}' does not exist."

        # 3. Construct new path in the same directory
        parent_dir = os.path.dirname(clean_source)
        clean_new_path = os.path.join(parent_dir, new_name)

        # 4. Secure the new path (Double check context limits)
        # Even though we checked new_name for separators, this handles 
        # edge cases where the resulting path might somehow be weird.
        clean_new_path = _get_safe_path(clean_new_path)

        # 5. Prevent overwriting existing files
        if os.path.exists(clean_new_path):
            return f"Error: A file already exists with the name '{new_name}' in this directory. Rename aborted."

        # 6. Rename the file
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