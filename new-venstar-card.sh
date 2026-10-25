#!/usr/bin/env bash
# Linux/macOS launcher; compatible with the Bash 3.2 shipped by macOS.
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./new-venstar-card.sh --firmware-version VH6.93 --target DIRECTORY \
         (--credentials-dir DIRECTORY | --root-ca-pem FILE) [OPTIONS]

Build a Venstar VH CA-import card with a four-byte version stub, using fresh
credentials or the add-on's public CA. The version must match the thermostat.
The target can be a mounted FAT32 card or a staging directory. This script never
formats disks. Check the mount path and filesystem before writing to a card.

Options:
  --python EXECUTABLE       Python 3.11+ executable (default: $PYTHON or python3)
  --root-ca-pem FILE          Use the active public CA PEM without generating keys
  --firmware-version VERSION  Version shown on the thermostat About screen
  --dry-run                Validate and print the plan; write nothing
  --reuse-credentials      Explicitly reuse this installation's existing bundle
  --force                  Replace card output files; never overwrites keys
  -h, --help               Show this help

Install dependencies first with your selected interpreter:
  python3 -m pip install -r requirements.txt

Keep --credentials-dir separate from, and outside, the card's directory tree.
EOF
}

python_bin="${PYTHON:-python3}"
builder_args=()
while (($#)); do
    case "$1" in
        --python)
            if (($# < 2)) || [[ -z "$2" ]]; then
                printf '%s\n' 'Error: --python requires an executable.' >&2
                exit 2
            fi
            python_bin="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            builder_args+=("$1")
            shift
            ;;
    esac
done

script_dir="$(CDPATH= cd -- "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
if ! command -v "$python_bin" >/dev/null 2>&1; then
    printf 'Error: Python executable not found: %s\n' "$python_bin" >&2
    exit 127
fi
"$python_bin" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else "Python 3.11 or newer is required.")'
# The guarded expansion supports empty arrays with nounset on older macOS Bash.
exec "$python_bin" "$script_dir/build_sdcard.py" ${builder_args[@]+"${builder_args[@]}"}
