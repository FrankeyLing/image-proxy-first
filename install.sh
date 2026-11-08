#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
replace=0
fallback=0
extras=0
for option in "$@"; do
    case "$option" in
        --replace-existing) replace=1 ;;
        --with-python-fallback) fallback=1 ;;
        --extras) fallback=1; extras=1 ;;
        *) printf '%s\n' 'Unknown installer option.' >&2; exit 2 ;;
    esac
done
[ "$(uname -s)" = Linux ] || { echo 'This installer selects Linux precompiled binaries.' >&2; exit 2; }
case "$(uname -m)" in
    x86_64|amd64) platform=linux-x64 ;;
    aarch64|arm64) platform=linux-arm64 ;;
    *) echo 'Unsupported processor architecture.' >&2; exit 2 ;;
esac
(cd "$root/image-proxy-first" && sha256sum -c "$root/payload-sha256.txt")
codex_root=${CODEX_HOME:-"$HOME/.codex"}
parent="$codex_root/skills"
target="$parent/image-proxy-first"
mkdir -p "$parent"
[ ! -L "$target" ] || { echo 'Installed skill symlink rejected.' >&2; exit 2; }
if [ -e "$target" ] && [ "$replace" -ne 1 ]; then echo 'Skill exists; use --replace-existing to retain a backup and replace.' >&2; exit 2; fi
stage=$(mktemp -d "$parent/.image-proxy-stage.XXXXXXXX")
cp -R "$root/image-proxy-first/." "$stage/"
(cd "$stage" && sha256sum -c "$root/payload-sha256.txt")
sed "s@bin/linux-x64/@bin/$platform/@g" "$stage/scripts/proxy" > "$stage/scripts/proxy-selected"
mv "$stage/scripts/proxy-selected" "$stage/scripts/proxy"
chmod +x "$stage/scripts/proxy" "$stage/bin/$platform/image-proxy"
if [ -e "$target" ]; then
    mkdir -p "$codex_root/skill-backups"
    backup="$codex_root/skill-backups/image-proxy-first-$(date +%Y%m%d-%H%M%S)-$$"
    [ ! -e "$backup" ] || exit 2
    mv "$target" "$backup"
fi
mv "$stage" "$target"
"$target/bin/$platform/image-proxy" --version
if [ "$fallback" -eq 1 ]; then
    python3 -m venv "$target/.venv"
    "$target/.venv/bin/python" -m pip install 'Pillow>=11,<13'
    if [ "$extras" -eq 1 ]; then "$target/.venv/bin/python" -m pip install 'pillow-heif>=0.20,<2' 'rawpy>=0.23,<1'; fi
fi
printf '{"platform":"%s","entry_point":"scripts/proxy","python_default":false,"compile_at_runtime":false}\n' "$platform" > "$target/runtime.json"
printf 'Installed: %s\n' "$target"
