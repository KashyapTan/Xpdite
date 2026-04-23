#!/usr/bin/env bash

set -euo pipefail

REPO_OWNER="${XPDITE_REPO_OWNER:-KashyapTan}"
REPO_NAME="${XPDITE_REPO_NAME:-Xpdite}"
CHANNEL="${XPDITE_CHANNEL:-latest}"
REQUESTED_VERSION="${XPDITE_VERSION:-}"
USER_AGENT="xpdite-install-script"
RELEASES_API="${XPDITE_RELEASES_API:-https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases?per_page=20}"
OS_NAME="${XPDITE_OS_OVERRIDE:-$(uname -s)}"
ARCH_NAME="${XPDITE_ARCH_OVERRIDE:-$(uname -m)}"
INSTALL_DIR="${XPDITE_INSTALL_DIR:-/Applications}"
DRY_RUN="${XPDITE_DRY_RUN:-0}"
KEEP_DOWNLOAD="${XPDITE_KEEP_DOWNLOAD:-0}"

log() {
  printf '==> %s\n' "$*"
}

warn() {
  printf 'warning: %s\n' "$*" >&2
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

normalize_requested_tag() {
  if [[ -z "$REQUESTED_VERSION" ]]; then
    printf ''
    return
  fi

  if [[ "$REQUESTED_VERSION" == v* ]]; then
    printf '%s' "$REQUESTED_VERSION"
    return
  fi

  printf 'v%s' "$REQUESTED_VERSION"
}

channel_matches() {
  local prerelease="$1"

  case "$CHANNEL" in
    beta)
      [[ "$prerelease" == "true" ]]
      ;;
    stable)
      [[ "$prerelease" == "false" ]]
      ;;
    latest|any)
      return 0
      ;;
    *)
      fail "Unsupported XPDITE_CHANNEL value: $CHANNEL"
      ;;
  esac
}

parse_release_with_python() {
  local releases_json="$1"
  local asset_pattern="$2"
  local requested_tag="$3"

  XPDITE_RELEASES_JSON="$releases_json" \
  XPDITE_ASSET_PATTERN="$asset_pattern" \
  XPDITE_CHANNEL="$CHANNEL" \
  XPDITE_REQUESTED_TAG="$requested_tag" \
  python3 - <<'PY'
import json
import os
import re
import sys

asset_pattern = re.compile(os.environ["XPDITE_ASSET_PATTERN"])
channel = os.environ["XPDITE_CHANNEL"]
requested_tag = os.environ["XPDITE_REQUESTED_TAG"]

releases = json.loads(os.environ["XPDITE_RELEASES_JSON"])

for release in releases:
    if release.get("draft"):
        continue

    tag_name = release.get("tag_name", "")
    prerelease = bool(release.get("prerelease"))

    if requested_tag and tag_name != requested_tag:
        continue

    if channel == "beta" and not prerelease:
        continue
    if channel == "stable" and prerelease:
        continue
    if channel not in {"beta", "stable", "latest", "any"}:
        print(f"Unsupported XPDITE_CHANNEL value: {channel}", file=sys.stderr)
        sys.exit(2)

    asset = next(
        (item for item in release.get("assets", []) if asset_pattern.match(item.get("name", ""))),
        None,
    )
    if asset is None:
        continue

    checksum = next(
        (item for item in release.get("assets", []) if item.get("name") == "SHA256SUMS.txt"),
        None,
    )

    print(tag_name)
    print(asset["name"])
    print(asset["browser_download_url"])
    print("" if checksum is None else checksum["browser_download_url"])
    sys.exit(0)

sys.exit(1)
PY
}

parse_release_fallback() {
  local releases_json="$1"
  local asset_pattern="$2"
  local requested_tag="$3"
  local current_tag=""
  local current_prerelease=""
  local current_draft=""
  local current_asset_name=""
  local current_asset_url=""
  local current_checksum_url=""
  local selected_tag=""
  local selected_asset_name=""
  local selected_asset_url=""
  local selected_checksum_url=""

  finalize_release() {
    if [[ -z "$current_tag" || -z "$current_asset_url" || "$current_draft" == "true" ]]; then
      return 1
    fi

    if [[ -n "$requested_tag" && "$current_tag" != "$requested_tag" ]]; then
      return 1
    fi

    if ! channel_matches "$current_prerelease"; then
      return 1
    fi

    selected_tag="$current_tag"
    selected_asset_name="$current_asset_name"
    selected_asset_url="$current_asset_url"
    selected_checksum_url="$current_checksum_url"
    return 0
  }

  while IFS= read -r line; do
    if [[ "$line" =~ ^[[:space:]]*\"url\":[[:space:]]\"https://api\.github\.com/repos/[^/]+/[^/]+/releases/[0-9]+\" ]]; then
      if finalize_release; then
        break
      fi

      current_tag=""
      current_prerelease=""
      current_draft=""
      current_asset_name=""
      current_asset_url=""
      current_checksum_url=""
      continue
    fi

    if [[ "$line" =~ ^[[:space:]]*\"tag_name\":[[:space:]]\"([^\"]+)\" ]]; then
      current_tag="${BASH_REMATCH[1]}"
      continue
    fi

    if [[ "$line" =~ ^[[:space:]]*\"prerelease\":[[:space:]](true|false) ]]; then
      current_prerelease="${BASH_REMATCH[1]}"
      continue
    fi

    if [[ "$line" =~ ^[[:space:]]*\"draft\":[[:space:]](true|false) ]]; then
      current_draft="${BASH_REMATCH[1]}"
      continue
    fi

    if [[ "$line" =~ ^[[:space:]]*\"browser_download_url\":[[:space:]]\"([^\"]+)\" ]]; then
      local asset_url="${BASH_REMATCH[1]}"
      local asset_name="${asset_url##*/}"

      if [[ "$asset_name" =~ $asset_pattern ]]; then
        current_asset_name="$asset_name"
        current_asset_url="$asset_url"
      elif [[ "$asset_name" == "SHA256SUMS.txt" ]]; then
        current_checksum_url="$asset_url"
      fi
    fi
  done <<<"$releases_json"

  if [[ -z "$selected_tag" ]]; then
    finalize_release || true
  fi

  if [[ -n "$selected_tag" ]]; then
    printf '%s\n%s\n%s\n%s\n' \
      "$selected_tag" \
      "$selected_asset_name" \
      "$selected_asset_url" \
      "$selected_checksum_url"
    return 0
  fi

  return 1
}

resolve_release() {
  local asset_pattern="$1"
  local requested_tag
  local releases_json
  requested_tag="$(normalize_requested_tag)"

  if [[ -n "${XPDITE_RELEASES_JSON:-}" ]]; then
    releases_json="${XPDITE_RELEASES_JSON}"
  else
    releases_json="$(
      curl -fsSL \
        -H "Accept: application/vnd.github+json" \
        -H "User-Agent: ${USER_AGENT}" \
        "$RELEASES_API"
    )"
  fi

  if command -v python3 >/dev/null 2>&1; then
    parse_release_with_python "$releases_json" "$asset_pattern" "$requested_tag"
    return
  fi

  if command -v python >/dev/null 2>&1; then
    XPDITE_RELEASES_JSON="$releases_json" \
    XPDITE_ASSET_PATTERN="$asset_pattern" \
    XPDITE_CHANNEL="$CHANNEL" \
    XPDITE_REQUESTED_TAG="$requested_tag" \
    python - <<'PY'
import json
import os
import re
import sys

asset_pattern = re.compile(os.environ["XPDITE_ASSET_PATTERN"])
channel = os.environ["XPDITE_CHANNEL"]
requested_tag = os.environ["XPDITE_REQUESTED_TAG"]

releases = json.loads(os.environ["XPDITE_RELEASES_JSON"])

for release in releases:
    if release.get("draft"):
        continue

    tag_name = release.get("tag_name", "")
    prerelease = bool(release.get("prerelease"))

    if requested_tag and tag_name != requested_tag:
        continue

    if channel == "beta" and not prerelease:
        continue
    if channel == "stable" and prerelease:
        continue
    if channel not in {"beta", "stable", "latest", "any"}:
        print(f"Unsupported XPDITE_CHANNEL value: {channel}", file=sys.stderr)
        sys.exit(2)

    asset = next(
        (item for item in release.get("assets", []) if asset_pattern.match(item.get("name", ""))),
        None,
    )
    if asset is None:
        continue

    checksum = next(
        (item for item in release.get("assets", []) if item.get("name") == "SHA256SUMS.txt"),
        None,
    )

    print(tag_name)
    print(asset["name"])
    print(asset["browser_download_url"])
    print("" if checksum is None else checksum["browser_download_url"])
    sys.exit(0)

sys.exit(1)
PY
    return
  fi

  parse_release_fallback "$releases_json" "$asset_pattern" "$requested_tag"
}

download_file() {
  local url="$1"
  local destination="$2"
  curl -fL --progress-bar -H "User-Agent: ${USER_AGENT}" "$url" -o "$destination"
}

verify_checksum() {
  local asset_path="$1"
  local sums_path="$2"
  local asset_name
  local expected
  local actual
  local expected_lower
  local actual_lower

  asset_name="$(basename "$asset_path")"
  expected="$(
    awk -v target="$asset_name" '
      NF >= 2 && $2 == target {
        print $1
        exit
      }
    ' "$sums_path"
  )"

  if [[ -z "$expected" ]]; then
    fail "Could not find checksum entry for ${asset_name} in SHA256SUMS.txt"
  fi

  if command -v shasum >/dev/null 2>&1; then
    actual="$(shasum -a 256 "$asset_path" | awk '{ print $1 }')"
  elif command -v sha256sum >/dev/null 2>&1; then
    actual="$(sha256sum "$asset_path" | awk '{ print $1 }')"
  else
    fail "Missing required checksum tool: shasum or sha256sum"
  fi

  actual_lower="$(printf '%s' "$actual" | tr '[:upper:]' '[:lower:]')"
  expected_lower="$(printf '%s' "$expected" | tr '[:upper:]' '[:lower:]')"

  if [[ "$actual_lower" != "$expected_lower" ]]; then
    fail "Checksum verification failed for ${asset_name}"
  fi
}

main() {
  local asset_pattern=''
  local mount_dir=''
  local selected_tag=''
  local selected_asset_name=''
  local selected_asset_url=''
  local selected_checksum_url=''
  local tmpdir=''
  local asset_path=''
  local checksum_path=''
  local installed_app=''
  local source_app=''
  local release_output=''

  need_cmd curl

  case "$OS_NAME" in
    Darwin)
      case "$ARCH_NAME" in
        arm64|aarch64)
          asset_pattern='^Xpdite-.*-mac-arm64\.dmg$'
          ;;
        x86_64)
          fail "Current releases only publish Apple Silicon macOS builds."
          ;;
        *)
          fail "Unsupported macOS architecture: $ARCH_NAME"
          ;;
      esac
      ;;
    Linux)
      fail "Linux release artifacts are not published yet. Use the manual release downloads for supported platforms."
      ;;
    *)
      fail "This installer supports macOS only. On Windows, use scripts/install.ps1."
      ;;
  esac

  release_output="$(resolve_release "$asset_pattern")" \
    || fail "Could not find a matching Xpdite release for channel '${CHANNEL}'."

  selected_tag="$(printf '%s\n' "$release_output" | sed -n '1p')"
  selected_asset_name="$(printf '%s\n' "$release_output" | sed -n '2p')"
  selected_asset_url="$(printf '%s\n' "$release_output" | sed -n '3p')"
  selected_checksum_url="$(printf '%s\n' "$release_output" | sed -n '4p')"

  if [[ -z "$selected_tag" || -z "$selected_asset_url" ]]; then
    fail "Resolved release metadata is incomplete."
  fi

  log "Selected release ${selected_tag}"
  log "Installer asset ${selected_asset_name}"

  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'tag=%s\nasset=%s\nurl=%s\nchecksum=%s\n' \
      "$selected_tag" \
      "$selected_asset_name" \
      "$selected_asset_url" \
      "${selected_checksum_url:-none}"
    exit 0
  fi

  need_cmd hdiutil
  need_cmd ditto
  tmpdir="$(mktemp -d)"
  asset_path="${tmpdir}/${selected_asset_name}"
  checksum_path="${tmpdir}/SHA256SUMS.txt"
  mount_dir="${tmpdir}/mount"
  mkdir -p "$mount_dir"

  cleanup() {
    local cleanup_mount_dir="${1:-}"
    local cleanup_tmpdir="${2:-}"
    local keep_download="${3:-0}"

    if [[ -n "$cleanup_mount_dir" && -d "$cleanup_mount_dir" ]]; then
      hdiutil detach "$cleanup_mount_dir" -quiet >/dev/null 2>&1 || true
    fi

    if [[ "$keep_download" != "1" && -n "$cleanup_tmpdir" && -d "$cleanup_tmpdir" ]]; then
      rm -rf "$cleanup_tmpdir"
    fi
  }
  trap "cleanup '$mount_dir' '$tmpdir' '$KEEP_DOWNLOAD'" EXIT

  log "Downloading installer"
  download_file "$selected_asset_url" "$asset_path"

  if [[ -n "$selected_checksum_url" ]]; then
    log "Downloading release checksums"
    download_file "$selected_checksum_url" "$checksum_path"
    log "Verifying checksum"
    verify_checksum "$asset_path" "$checksum_path"
  else
    warn "Release checksums were not published for ${selected_tag}; skipping verification."
  fi

  log "Mounting disk image"
  hdiutil attach "$asset_path" -mountpoint "$mount_dir" -nobrowse -quiet
  source_app="$(find "$mount_dir" -type d -name '*.app' -prune -print | sed -n '1p')"
  [[ -n "$source_app" ]] || fail "Could not locate the Xpdite app bundle inside the disk image."

  installed_app="${INSTALL_DIR}/$(basename "$source_app")"

  if mkdir -p "$INSTALL_DIR" 2>/dev/null; then
    rm -rf "$installed_app"
    ditto "$source_app" "$installed_app"
    if command -v xattr >/dev/null 2>&1; then
      xattr -dr com.apple.quarantine "$installed_app" >/dev/null 2>&1 || true
    fi
  else
    need_cmd sudo
    sudo mkdir -p "$INSTALL_DIR"
    sudo rm -rf "$installed_app"
    sudo ditto "$source_app" "$installed_app"
    if command -v xattr >/dev/null 2>&1; then
      sudo xattr -dr com.apple.quarantine "$installed_app" >/dev/null 2>&1 || true
    fi
  fi

  log "Installed Xpdite to ${installed_app}"
  warn "Xpdite is not notarized yet, so direct macOS downloads may still show a security prompt."
}

main "$@"
