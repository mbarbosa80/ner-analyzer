#!/bin/bash
# =============================================================================
#  NER Spatial Coverage Analyzer - installer for macOS (Apple Silicon)
#  (c) 2026 Marcelo Barbosa. Free software, GNU AGPL-3.0 - see LICENSE.txt and NOTICE.txt.
#
#  The macOS twin of setup.bat (3.0.0). One step, no administrator password:
#
#    1. checks the Mac (Apple Silicon, macOS 11 or later) and the package;
#    2. an existing installation is backed up, stopped and moved aside to
#       <target>.previous - its data\ folder is carried into the new one;
#    3. copies the application into the target folder;
#    4. unpacks the bundled Python 3.12 into .python/ and installs the bundled
#       packages into it - offline, nothing is downloaded;
#    5. registers a launch agent for this account (starts the server at
#       sign-in and again if it stops), starts it, opens the browser and puts
#       an "NER Analyzer" link on the Desktop;
#    6. removes the installation files: vendor/ in the target, then the
#       unzipped package and its zip (in the package's folder, one or two
#       levels up, or in Downloads).
#
#  Usage (in Terminal):   bash setup.command [target] [--no-services] [--keep-installer]
#  Or double-click setup.command in Finder (see QUICK-INSTALL for the
#  "unidentified developer" prompt).
#
#  Default target: ~/Applications/ner-analyzer
#  Written for the /bin/bash 3.2 macOS ships: no associative arrays, no
#  ${var,,}, no mapfile, no sed -i, no readlink -f.
# =============================================================================

set -u
VERSION_FILE="VERSION"
LABEL="com.marcelobarbosa.ner-analyzer"
PORT="${NER_PORT:-8000}"

say()  { printf '%s\n' "$*"; }
step() { printf '\n[%s] %s\n' "$1" "$2"; }
fail() {
    printf '\n[X] %s\n' "$*" >&2
    [ -n "${LOG:-}" ] && printf '%s FAILED: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG" 2>/dev/null
    pause_end
    exit 1
}
pause_end() {
    if [ -z "${NER_NOPAUSE:-}" ] && [ -t 0 ]; then
        printf '\nPress Enter to close this window.'
        read -r _ || true
    fi
}

SRC="$(cd "$(dirname "$0")" && pwd -P)"
TARGET=""
SERVICES=1
KEEP=0
for arg in "$@"; do
    case "$arg" in
        --no-services)    SERVICES=0 ;;
        --keep-installer) KEEP=1 ;;
        -h|--help)
            sed -n '2,28p' "$0"; exit 0 ;;
        -*) fail "unknown option: $arg" ;;
        *)  TARGET="$arg" ;;
    esac
done
[ -n "$TARGET" ] || TARGET="$HOME/Applications/ner-analyzer"
case "$TARGET" in /*) ;; *) TARGET="$PWD/$TARGET" ;; esac
TARGET="${TARGET%/}"

say ""
say "  NER Spatial Coverage Analyzer - installer for macOS"
say "  (c) 2026 Marcelo Barbosa. Free software, GNU AGPL-3.0."
say ""

# --- [1/6] the Mac and the package ------------------------------------------
step "1/6" "Checking this Mac and the package..."
[ -f "$SRC/MANIFEST.txt" ] || fail "no MANIFEST.txt beside setup.command - run the setup.command of an unzipped package, not of a development checkout."
[ -f "$SRC/$VERSION_FILE" ] || fail "no VERSION file in $SRC"
VERSION="$(tr -d ' \r\n' < "$SRC/$VERSION_FILE")"
RUNTIME="$(ls "$SRC"/vendor/python/cpython-3.12.*-install_only.tar.gz 2>/dev/null | head -n 1)"
[ -n "$RUNTIME" ] || fail "the package has no Python runtime in vendor/python/ - it is incomplete; download it again."
ls "$SRC"/vendor/wheels/*.whl >/dev/null 2>&1 || fail "the package has no Python packages in vendor/wheels/ - it is incomplete; download it again."

if [ -z "${NER_SETUP_ANY_PLATFORM:-}" ]; then
    [ "$(uname -s)" = "Darwin" ] || fail "this package is for macOS. On Windows use the Windows package (setup.bat)."
    ARCH="$(uname -m)"
    if [ "$ARCH" != "arm64" ] && [ "$(sysctl -n sysctl.proc_translated 2>/dev/null)" != "1" ]; then
        fail "this Mac has an Intel processor ($ARCH). This package is for Apple Silicon (M1 or later)."
    fi
    OSMAJOR="$(sw_vers -productVersion 2>/dev/null | cut -d. -f1)"
    [ -n "$OSMAJOR" ] && [ "$OSMAJOR" -ge 11 ] 2>/dev/null || fail "macOS 11 (Big Sur) or later is required; this Mac reports $(sw_vers -productVersion 2>/dev/null)."
fi

# The target must not be the package, inside it, or above it.
case "$TARGET/" in "$SRC/"*) fail "the target ($TARGET) is inside the package folder - choose another folder." ;; esac
case "$SRC/" in "$TARGET/"*) fail "the package folder is inside the target ($TARGET) - unzip the package somewhere else first." ;; esac
[ "$TARGET" != "$HOME" ] || fail "the target cannot be your home folder itself."

# A browser download marks every file it unzips as "from the internet"; the
# runtime would then be stopped by Gatekeeper the first time it runs. The
# files are this account's own, so taking the mark off needs no password.
if command -v xattr >/dev/null 2>&1; then
    xattr -dr com.apple.quarantine "$SRC" 2>/dev/null || true
fi

MODE="new"
if [ -e "$TARGET/data/ner.sqlite3" ] || [ -d "$TARGET/.python" ]; then MODE="update"; fi
say "    version $VERSION, Apple Silicon"
say "    target  $TARGET  ($MODE installation)"

mkdir -p "$TARGET/data" || fail "cannot create $TARGET"
LOG="$TARGET/data/setup.log"
printf '%s setup %s %s into %s (%s)\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$VERSION" "$MODE" "$TARGET" "$SRC" >> "$LOG"

# --- [2/6] an existing installation ------------------------------------------
PREV=""
if [ "$MODE" = "update" ]; then
    step "2/6" "Backing up and stopping the installed version..."
    if [ -x "$TARGET/.python/bin/python3" ] && [ -f "$TARGET/tools/backup.py" ]; then
        ( cd "$TARGET" && PYTHONNOUSERSITE=1 "$TARGET/.python/bin/python3" -s tools/backup.py ) >> "$LOG" 2>&1 \
            || fail "the backup of the installed data failed - nothing was changed. See $LOG."
        say "    backup written under $TARGET/data/"
    else
        say "    (no runtime in the installed copy - the data folder is kept as it is)"
    fi
    if [ "$SERVICES" = "1" ] && command -v launchctl >/dev/null 2>&1; then
        launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || true
    fi
    if [ -f "$TARGET/mac/stop.command" ]; then
        NER_NOPAUSE=1 bash "$TARGET/mac/stop.command" >> "$LOG" 2>&1 || true
    fi
    PREV="$TARGET.previous"
    rm -rf "$PREV"
    mv "$TARGET" "$PREV" || fail "could not move $TARGET aside (is a file in it open?). Nothing was changed."
    mkdir -p "$TARGET" || { mv "$PREV" "$TARGET"; fail "could not create $TARGET - the previous version is back in place."; }
    mv "$PREV/data" "$TARGET/data" || { rm -rf "$TARGET"; mv "$PREV" "$TARGET"; fail "could not carry data/ across - the previous version is back in place."; }
    say "    previous version kept in $PREV (its data/ is now in the new installation)"
    LOG="$TARGET/data/setup.log"
else
    step "2/6" "No earlier installation in $TARGET."
fi

rollback() {
    # Put the previous installation back, data first, so a failed update
    # never leaves the person without a working copy.
    if [ -n "$PREV" ] && [ -d "$PREV" ]; then
        say "    restoring the previous version..."
        mv "$TARGET/data" "$PREV/data" 2>/dev/null && rm -rf "$TARGET" && mv "$PREV" "$TARGET"
        if [ "$SERVICES" = "1" ] && [ -f "$HOME/Library/LaunchAgents/$LABEL.plist" ]; then
            launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/$LABEL.plist" >/dev/null 2>&1 || true
        fi
    fi
}

# --- [3/6] the application ------------------------------------------------------
step "3/6" "Copying the application..."
( cd "$SRC" && tar --exclude './data' --exclude './setup.command' -cf - . ) | ( cd "$TARGET" && tar -xf - ) \
    || { rollback; fail "copying the application failed. See $LOG."; }
mkdir -p "$TARGET/data"
chmod +x "$TARGET"/mac/*.command 2>/dev/null || true

# --- [4/6] Python and the packages ---------------------------------------------
step "4/6" "Unpacking Python and installing the packages (offline, about a minute)..."
rm -rf "$TARGET/.python" "$TARGET/python"
tar -xzf "$TARGET/vendor/python/$(basename "$RUNTIME")" -C "$TARGET" || { rollback; fail "unpacking the Python runtime failed."; }
mv "$TARGET/python" "$TARGET/.python" || { rollback; fail "could not place the Python runtime."; }
command -v xattr >/dev/null 2>&1 && xattr -dr com.apple.quarantine "$TARGET" 2>/dev/null
PY="$TARGET/.python/bin/python3"
"$PY" -s -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version" >> "$LOG" 2>&1 \
    || { rollback; fail "the bundled Python does not start on this Mac. See $LOG."; }
( cd "$TARGET" && PYTHONNOUSERSITE=1 "$PY" -s -m pip install --disable-pip-version-check --no-index \
      --find-links vendor/wheels --no-deps --ignore-installed -q -r requirements-lock-mac.txt ) >> "$LOG" 2>&1 \
    || { rollback; fail "installing the bundled packages failed. See $LOG."; }
( cd "$TARGET" && PYTHONNOUSERSITE=1 "$PY" -s tools/check_env.py ) >> "$LOG" 2>&1 \
    || { rollback; fail "a component does not load. See $LOG."; }
date '+%Y-%m-%d %H:%M:%S' > "$TARGET/.python/.deps-installed"
say "    Python $("$PY" -s -c 'import platform; print(platform.python_version())'), all components load"

# --- [5/6] the server -----------------------------------------------------------
if [ "$SERVICES" = "1" ]; then
    step "5/6" "Starting the server and registering it for this account..."
    NER_NOPAUSE=1 bash "$TARGET/mac/autostart.command" >> "$LOG" 2>&1 \
        || { rollback; fail "the server could not be registered. See $LOG."; }
    up=0
    i=0
    while [ $i -lt 45 ]; do
        if curl -fsS "http://127.0.0.1:$PORT/healthz" 2>/dev/null | grep -q "\"$VERSION\""; then up=1; break; fi
        sleep 2; i=$((i + 1))
    done
    if [ "$up" = "1" ]; then
        say "    the server answers on http://127.0.0.1:$PORT/"
        cat > "$HOME/Desktop/NER Analyzer.webloc" 2>/dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>URL</key><string>http://127.0.0.1:$PORT/</string></dict></plist>
EOF
        open "http://127.0.0.1:$PORT/" 2>/dev/null || true
    else
        say "    [!] the server did not answer within 90 s. It may still be starting:"
        say "        open http://127.0.0.1:$PORT/ in a minute, or see $TARGET/data/server.log"
    fi
else
    step "5/6" "Not starting anything (--no-services). Start it with mac/start.command."
fi

# --- [6/6] the installation files ------------------------------------------------
step "6/6" "Removing the installation files..."
rm -rf "$TARGET/vendor"
if [ -n "$PREV" ] && [ -d "$PREV" ]; then rm -rf "$PREV"; fi
printf '%s installed %s (%s)\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$VERSION" "$MODE" >> "$LOG"

say ""
say "  Installed - version $VERSION"
say "  in $TARGET"
[ "$MODE" = "update" ] && say "  (the data is where it was; a backup is under data/)"
say ""

if [ "$KEEP" = "0" ]; then
    ZIP="ner-analyzer-$VERSION-macos-arm64.zip"
    PARENT="$(dirname "$SRC")"
    # The unzipped package: only a folder that is one (MANIFEST.txt and this
    # script in it), never anything else.
    if [ -f "$SRC/MANIFEST.txt" ] && [ -f "$SRC/setup.command" ] && [ "$SRC" != "$HOME" ] && [ "$SRC" != "/" ]; then
        rm -rf "$SRC"
        # Archive Utility unzips into a folder named after the zip; remove it
        # when it is left empty - only that folder, never Downloads itself.
        case "$(basename "$PARENT")" in
            ner-analyzer-*) rmdir "$PARENT" 2>/dev/null || true ;;
        esac
    fi
    for d in "$PARENT" "$(dirname "$PARENT")" "$HOME/Downloads"; do
        rm -f "$d/$ZIP" "$d/$ZIP.sha256" 2>/dev/null
    done
    say "  The installation files were removed."
fi
pause_end
exit 0
