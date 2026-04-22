import subprocess
import sys
import os
import shutil
from pathlib import Path
from typing import Iterable


def resolve_python_executable(project_root: Path) -> Path:
    candidates = [
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find a Python executable in .venv or sys.executable")


def iter_input_paths(paths: Iterable[Path]):
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            yield path
            continue
        for root, dirs, files in os.walk(path):
            root_path = Path(root)
            yield root_path
            dirs[:] = [
                directory
                for directory in dirs
                if directory
                not in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
            ]
            for file_name in files:
                if file_name.endswith((".pyc", ".pyo")):
                    continue
                yield root_path / file_name


def latest_mtime(paths: Iterable[Path]) -> float:
    latest = 0.0
    for path in iter_input_paths(paths):
        try:
            latest = max(latest, path.stat().st_mtime)
        except FileNotFoundError:
            continue
    return latest


def is_python_server_up_to_date(project_root: Path, exe_path: Path) -> bool:
    if not exe_path.exists():
        return False

    inputs = [
        project_root / "source",
        project_root / "mcp_servers",
        project_root / "build-server.spec",
        project_root / "scripts" / "build-python-exe.py",
        project_root / "pyproject.toml",
        project_root / "uv.lock",
        project_root / "requirements.txt",
    ]
    return exe_path.stat().st_mtime >= latest_mtime(inputs)

def build_python_server():
    """Build the Python server using PyInstaller (venv managed by UV)"""
    
    # Ensure we're in the project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    dist_dir = project_root / "dist-python"
    exe_name = "xpdite-server.exe" if os.name == "nt" else "xpdite-server"
    exe_path = dist_dir / exe_name

    try:
        python_executable = resolve_python_executable(project_root)
    except FileNotFoundError as error:
        print(str(error))
        print("Please run 'uv sync --group dev' or 'bun run install:python' first.")
        sys.exit(1)

    if is_python_server_up_to_date(project_root, exe_path):
        print(f"Python server executable is up to date at: {exe_path}")
        return

    # Create dist directory if it doesn't exist
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(exist_ok=True)
    
    # Build command
    cmd = [
        str(python_executable),
        "-m", "PyInstaller",
        "--distpath", str(dist_dir),
        "--workpath", str(project_root / "build-temp"),
        "build-server.spec"
    ]
    
    print("Building Python server executable...")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("Python server built successfully.")
        print(f"Executable created at: {dist_dir / exe_name}")
        
        # Verify the executable was created
        exe_path = dist_dir / exe_name
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"Executable size: {size_mb:.1f} MB")
        else:
            print("Executable not found after build")
            sys.exit(1)
            
    except subprocess.CalledProcessError as e:
        print("Build failed.")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        sys.exit(1)

    print("Build complete!")

if __name__ == "__main__":
    build_python_server()
