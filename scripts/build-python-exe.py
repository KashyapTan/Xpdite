import subprocess
import sys
import os
import shutil
import textwrap
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


def resolve_python_server_output_dir(dist_dir: Path) -> Path:
    return dist_dir / "xpdite-server"


def resolve_python_server_executable(dist_dir: Path) -> Path:
    exe_name = "xpdite-server.exe" if os.name == "nt" else "xpdite-server"
    return resolve_python_server_output_dir(dist_dir) / exe_name


def resolve_bundled_sentence_transformer_output_dir(dist_dir: Path) -> Path:
    return (
        resolve_python_server_output_dir(dist_dir)
        / "_internal"
        / "embedding-models"
        / "all-MiniLM-L6-v2"
    )


def resolve_sentence_transformers_package_dir(dist_dir: Path) -> Path:
    return (
        resolve_python_server_output_dir(dist_dir)
        / "_internal"
        / "sentence_transformers"
    )


def resolve_huggingface_hub_package_dir(dist_dir: Path) -> Path:
    return (
        resolve_python_server_output_dir(dist_dir)
        / "_internal"
        / "huggingface_hub"
    )


def directory_size_bytes(path: Path) -> int:
    total = 0
    for entry in iter_input_paths([path]):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def is_bundled_sentence_transformer_ready(path: Path) -> bool:
    required_paths = (
        path / "config.json",
        path / "config_sentence_transformers.json",
        path / "modules.json",
        path / "model.safetensors",
        path / "sentence_bert_config.json",
        path / "tokenizer.json",
        path / "tokenizer_config.json",
        path / "vocab.txt",
        path / "1_Pooling" / "config.json",
    )
    return all(required_path.exists() for required_path in required_paths)


def prepare_sentence_transformer_model(
    project_root: Path, python_executable: Path
) -> Path:
    model_dir = project_root / "build-temp" / "embedding-models" / "all-MiniLM-L6-v2"

    if is_bundled_sentence_transformer_ready(model_dir):
        print(f"Bundled sentence-transformers model is ready at: {model_dir}")
        return model_dir

    model_dir.parent.mkdir(parents=True, exist_ok=True)

    helper_script = textwrap.dedent(
        """
        import shutil
        import sys
        from pathlib import Path

        from huggingface_hub import snapshot_download

        repo_id = "sentence-transformers/all-MiniLM-L6-v2"
        target_dir = Path(sys.argv[1])
        snapshot_path = Path(snapshot_download(repo_id=repo_id))

        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(snapshot_path, target_dir, symlinks=False)
        print(target_dir)
        """
    ).strip()

    print("Preparing bundled sentence-transformers model...")
    result = subprocess.run(
        [str(python_executable), "-c", helper_script, str(model_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    return model_dir


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
    dist_dir = project_root / "dist-python"
    bundled_model_dir = resolve_bundled_sentence_transformer_output_dir(dist_dir)
    sentence_transformers_dir = resolve_sentence_transformers_package_dir(dist_dir)
    huggingface_hub_dir = resolve_huggingface_hub_package_dir(dist_dir)
    return (
        exe_path.stat().st_mtime >= latest_mtime(inputs)
        and is_bundled_sentence_transformer_ready(bundled_model_dir)
        and sentence_transformers_dir.exists()
        and huggingface_hub_dir.exists()
    )

def build_python_server():
    """Build the Python server using PyInstaller (venv managed by UV)"""
    
    # Ensure we're in the project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    dist_dir = project_root / "dist-python"
    output_dir = resolve_python_server_output_dir(dist_dir)
    exe_path = resolve_python_server_executable(dist_dir)

    try:
        python_executable = resolve_python_executable(project_root)
    except FileNotFoundError as error:
        print(str(error))
        print("Please run 'uv sync --group dev' or 'bun run install:python' first.")
        sys.exit(1)

    try:
        prepare_sentence_transformer_model(project_root, python_executable)
    except subprocess.CalledProcessError as error:
        print("Failed to prepare bundled sentence-transformers model.")
        print("STDOUT:", error.stdout)
        print("STDERR:", error.stderr)
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
        print(f"Bundle created at: {output_dir}")
        
        # Verify the executable was created
        exe_path = resolve_python_server_executable(dist_dir)
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            bundle_size_mb = directory_size_bytes(output_dir) / (1024 * 1024)
            print(f"Executable size: {size_mb:.1f} MB")
            print(f"Bundle size: {bundle_size_mb:.1f} MB")
        else:
            print("Executable not found after build")
            sys.exit(1)

        bundled_output_dir = resolve_bundled_sentence_transformer_output_dir(dist_dir)
        if not is_bundled_sentence_transformer_ready(bundled_output_dir):
            print(
                "Bundled sentence-transformers model was not copied into the Python server bundle."
            )
            sys.exit(1)

        sentence_transformers_dir = resolve_sentence_transformers_package_dir(dist_dir)
        if not sentence_transformers_dir.exists():
            print(
                "sentence_transformers package was not bundled into the Python server."
            )
            sys.exit(1)

        huggingface_hub_dir = resolve_huggingface_hub_package_dir(dist_dir)
        if not huggingface_hub_dir.exists():
            print("huggingface_hub package was not bundled into the Python server.")
            sys.exit(1)

        print(f"Bundled model copied to: {bundled_output_dir}")
        print(f"Bundled sentence_transformers package at: {sentence_transformers_dir}")
        print(f"Bundled huggingface_hub package at: {huggingface_hub_dir}")
            
    except subprocess.CalledProcessError as e:
        print("Build failed.")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        sys.exit(1)

    print("Build complete!")

if __name__ == "__main__":
    build_python_server()
