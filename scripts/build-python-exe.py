import subprocess
import sys
import os
import shutil
from pathlib import Path


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

def build_python_server():
    """Build the Python server using PyInstaller (venv managed by UV)"""
    
    # Ensure we're in the project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # Create dist directory if it doesn't exist
    dist_dir = project_root / "dist-python"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(exist_ok=True)
    
    try:
        python_executable = resolve_python_executable(project_root)
    except FileNotFoundError as error:
        print(str(error))
        print("Please run 'uv sync --group dev' or 'bun run install:python' first.")
        sys.exit(1)
    
    # Build command
    cmd = [
        str(python_executable),
        "-m", "PyInstaller",
        "--clean",
        "--distpath", str(dist_dir),
        "--workpath", str(project_root / "build-temp"),
        "build-server.spec"
    ]

    exe_name = "xpdite-server.exe" if os.name == "nt" else "xpdite-server"
    
    print("Building Python server executable...")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print("✅ Python server built successfully!")
        print(f"Executable created at: {dist_dir / exe_name}")
        
        # Verify the executable was created
        exe_path = dist_dir / exe_name
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"Executable size: {size_mb:.1f} MB")
        else:
            print("❌ Executable not found after build")
            sys.exit(1)
            
    except subprocess.CalledProcessError as e:
        print("❌ Build failed!")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        sys.exit(1)
    
    # Clean up build artifacts
    build_temp = project_root / "build-temp"
    if build_temp.exists():
        shutil.rmtree(build_temp)
    
    print("Build complete!")

if __name__ == "__main__":
    build_python_server()
