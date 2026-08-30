import subprocess
import sys
import os
import shutil
import textwrap
import hashlib
import json
import platform
from pathlib import Path
from typing import Iterable


PROFILE_GROUPS = {
    "full": ["dev", "transcription", "advanced-audio", "local-embeddings"],
    "mac-intel-transcription": ["dev", "transcription"],
}


def resolve_build_profile() -> str:
    profile = os.environ.get("XPDITE_BUILD_PROFILE", "full").strip() or "full"
    if profile not in PROFILE_GROUPS:
        raise ValueError(f"Unsupported Xpdite Python build profile: {profile}")
    return profile


def local_embeddings_enabled(profile: str) -> bool:
    return profile == "full"


def resolve_python_executable(project_root: Path) -> Path:
    configured_env = os.environ.get("XPDITE_PYTHON_ENV", "").strip()
    candidates = [
        *(
            [Path(configured_env) / "Scripts" / "python.exe"]
            if configured_env and os.name == "nt"
            else [
                Path(configured_env) / "bin" / "python3",
                Path(configured_env) / "bin" / "python",
            ]
            if configured_env
            else []
        ),
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find a Python executable in .venv or sys.executable")


def inspect_python(python_executable: Path) -> dict[str, str]:
    helper = (
        "import json, platform, sys; "
        "print(json.dumps({'executable': sys.executable, "
        "'machine': platform.machine(), "
        "'version': f'{sys.version_info.major}.{sys.version_info.minor}'}))"
    )
    result = subprocess.run(
        [str(python_executable), "-c", helper],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def validate_python_architecture(identity: dict[str, str]) -> None:
    target_arch = os.environ.get("XPDITE_TARGET_ARCH", "").strip()
    if not target_arch:
        return
    expected = "x86_64" if target_arch == "x64" else "arm64"
    actual = identity.get("machine", "")
    normalized_actual = "x86_64" if actual.upper() == "AMD64" else actual
    if normalized_actual != expected:
        raise RuntimeError(
            f"Wrong Python architecture: expected {expected}, found {actual or 'unknown'}"
        )


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


def bundled_portaudio_exists(path: Path) -> bool:
    return any(
        entry.is_file() and "libportaudio" in entry.name.lower()
        for entry in iter_input_paths([path])
    )


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_stamp(
    project_root: Path,
    profile: str,
    python_identity: dict[str, str],
) -> dict:
    inputs = [
        project_root / "source",
        project_root / "mcp_servers",
        project_root / "build-server.spec",
        project_root / "scripts" / "build-python-exe.py",
        project_root / "pyproject.toml",
        project_root / "uv.lock",
        project_root / "requirements.txt",
    ]
    return {
        "schema_version": 2,
        "target": {
            "platform": os.environ.get("XPDITE_TARGET_PLATFORM", sys.platform),
            "architecture": os.environ.get(
                "XPDITE_TARGET_ARCH",
                "x64" if platform.machine() in {"x86_64", "AMD64"} else "arm64",
            ),
            "profile": profile,
            "groups": PROFILE_GROUPS[profile],
        },
        "python": python_identity,
        "lockfile_sha256": sha256_file(project_root / "uv.lock"),
        "latest_input_mtime": latest_mtime(inputs),
    }


def is_python_server_up_to_date(
    project_root: Path,
    exe_path: Path,
    expected_stamp: dict,
    require_local_embeddings: bool,
) -> bool:
    if not exe_path.exists():
        return False
    dist_dir = project_root / "dist-python"
    stamp_path = dist_dir / ".build-stamp.json"
    try:
        existing_stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    bundled_model_dir = resolve_bundled_sentence_transformer_output_dir(dist_dir)
    sentence_transformers_dir = resolve_sentence_transformers_package_dir(dist_dir)
    huggingface_hub_dir = resolve_huggingface_hub_package_dir(dist_dir)
    return (
        existing_stamp == expected_stamp
        and (
            expected_stamp.get("target", {}).get("platform") != "darwin"
            or bundled_portaudio_exists(resolve_python_server_output_dir(dist_dir))
        )
        and (
            not require_local_embeddings
            or (
                is_bundled_sentence_transformer_ready(bundled_model_dir)
                and sentence_transformers_dir.exists()
                and huggingface_hub_dir.exists()
            )
        )
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
        print("Please run 'bun run install:python' for the native build profile first.")
        sys.exit(1)

    profile = resolve_build_profile()
    try:
        python_identity = inspect_python(python_executable)
        validate_python_architecture(python_identity)
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Failed to validate build Python: {error}")
        sys.exit(1)
    expected_stamp = build_stamp(project_root, profile, python_identity)
    include_local_embeddings = local_embeddings_enabled(profile)

    print(
        f"Python build profile: {profile} "
        f"({os.environ.get('XPDITE_TARGET_PLATFORM', sys.platform)}/"
        f"{os.environ.get('XPDITE_TARGET_ARCH', python_identity['machine'])})"
    )
    print(f"Python executable: {python_identity['executable']}")

    if include_local_embeddings:
        try:
            prepare_sentence_transformer_model(project_root, python_executable)
        except subprocess.CalledProcessError as error:
            print("Failed to prepare bundled sentence-transformers model.")
            print("STDOUT:", error.stdout)
            print("STDERR:", error.stderr)
            sys.exit(1)
    else:
        print("Skipping bundled Sentence Transformers model for this profile.")

    if is_python_server_up_to_date(
        project_root, exe_path, expected_stamp, include_local_embeddings
    ):
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

        if include_local_embeddings:
            bundled_output_dir = resolve_bundled_sentence_transformer_output_dir(dist_dir)
            if not is_bundled_sentence_transformer_ready(bundled_output_dir):
                print(
                    "Bundled sentence-transformers model was not copied into the Python server bundle."
                )
                sys.exit(1)

            sentence_transformers_dir = resolve_sentence_transformers_package_dir(dist_dir)
            if not sentence_transformers_dir.exists():
                print("sentence_transformers package was not bundled into the Python server.")
                sys.exit(1)

            huggingface_hub_dir = resolve_huggingface_hub_package_dir(dist_dir)
            if not huggingface_hub_dir.exists():
                print("huggingface_hub package was not bundled into the Python server.")
                sys.exit(1)

            print(f"Bundled model copied to: {bundled_output_dir}")
            print(f"Bundled sentence_transformers package at: {sentence_transformers_dir}")
            print(f"Bundled huggingface_hub package at: {huggingface_hub_dir}")
        else:
            omitted_paths = [
                resolve_bundled_sentence_transformer_output_dir(dist_dir),
                resolve_sentence_transformers_package_dir(dist_dir),
            ]
            if any(path.exists() for path in omitted_paths):
                print("Intel profile unexpectedly bundled local embedding resources.")
                sys.exit(1)

        if sys.platform == "darwin" and not bundled_portaudio_exists(output_dir):
            print(
                "PortAudio was not bundled with PyAudio. Install it with "
                "'brew install portaudio' and rebuild."
            )
            sys.exit(1)

        (dist_dir / ".build-stamp.json").write_text(
            json.dumps(expected_stamp, indent=2) + "\n", encoding="utf-8"
        )
            
    except subprocess.CalledProcessError as e:
        print("Build failed.")
        print("STDOUT:", e.stdout)
        print("STDERR:", e.stderr)
        sys.exit(1)

    print("Build complete!")

if __name__ == "__main__":
    build_python_server()
