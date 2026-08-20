#!/bin/bash
# One-time HPC setup for Konclude v0.7.0-1138 -- the exact build every
# result in this reproducibility pipeline (scripts/2_run_konclude_reasoning.sh,
# scripts/3_run_583_bisection.sh) was generated with. Based on
# "HOW TO MAKE KONCLUDE RUN ON HPC.txt":
#   1. Download + unzip the Linux x64 static build into ~/tools/konclude.
#   2. chmod +x the binary, smoke-test it.
#   3. If the smoke test fails on a missing libpcre.so.3 (common on HPC
#      login/compute nodes with a newer system PCRE), symlink a shim onto
#      libpcre.so.1 and point LD_LIBRARY_PATH at it.
#   4. Persist KONCLUDE_BIN (and LD_LIBRARY_PATH, if the shim was needed) in
#      ~/.bashrc, so a fresh login/job doesn't need this run again -- every
#      pipeline script here just calls "$KONCLUDE_BIN realisation ...".
#
# Safe to re-run: skips the download/unzip if the binary is already there,
# and only appends to ~/.bashrc once (guarded by a marker comment).
#
# Run from anywhere:
#   bash scripts/setup_konclude.sh
# Then either start a new shell, or `source ~/.bashrc`, to pick up
# KONCLUDE_BIN in the current one.

set -e

KONCLUDE_VERSION="v0.7.0-1138"
KONCLUDE_DIST="Konclude-${KONCLUDE_VERSION}-Linux-x64-GCC-Static-Qt5.12.10"
KONCLUDE_URL="https://github.com/konclude/Konclude/releases/download/${KONCLUDE_VERSION}/${KONCLUDE_DIST}.zip"
KONCLUDE_ROOT="$HOME/tools/konclude"
KONCLUDE_BIN="$KONCLUDE_ROOT/$KONCLUDE_DIST/Binaries/Konclude"
LIBSHIM_DIR="$KONCLUDE_ROOT/libshim"
BASHRC="$HOME/.bashrc"
MARKER="# --- Konclude (added by texture inference/scripts/setup_konclude.sh) ---"

echo "=== 1. Download + unzip ==="
if [ -x "$KONCLUDE_BIN" ]; then
    echo "Already installed at $KONCLUDE_BIN, skipping download."
else
    mkdir -p "$KONCLUDE_ROOT"
    cd "$KONCLUDE_ROOT"
    wget -nc "$KONCLUDE_URL"
    unzip -o "${KONCLUDE_DIST}.zip"
    cd - > /dev/null
fi

echo "=== 2. chmod +x ==="
chmod +x "$KONCLUDE_BIN"

echo "=== 3. Smoke test ==="
NEEDS_LIBSHIM=false
if "$KONCLUDE_BIN" > /tmp/konclude_smoketest.log 2>&1; then
    echo "Smoke test OK."
elif grep -q "libpcre.so.3" /tmp/konclude_smoketest.log; then
    echo "Missing libpcre.so.3 -- setting up the libshim workaround."
    NEEDS_LIBSHIM=true
    mkdir -p "$LIBSHIM_DIR"
    ln -sf /lib64/libpcre.so.1 "$LIBSHIM_DIR/libpcre.so.3"
    export LD_LIBRARY_PATH="$LIBSHIM_DIR:$LD_LIBRARY_PATH"
    if "$KONCLUDE_BIN" > /tmp/konclude_smoketest.log 2>&1; then
        echo "Smoke test OK after libshim fix."
    else
        echo "Smoke test still failing -- see /tmp/konclude_smoketest.log:"
        cat /tmp/konclude_smoketest.log
        exit 1
    fi
else
    echo "Smoke test failed for a reason other than libpcre.so.3 -- see /tmp/konclude_smoketest.log:"
    cat /tmp/konclude_smoketest.log
    exit 1
fi

echo "=== 4. Persisting to $BASHRC ==="
if grep -qF "$MARKER" "$BASHRC" 2>/dev/null; then
    echo "Already persisted (marker found in $BASHRC), leaving it as-is."
else
    {
        echo ""
        echo "$MARKER"
        echo "export KONCLUDE_BIN=\"$KONCLUDE_BIN\""
        if [ "$NEEDS_LIBSHIM" = true ]; then
            echo "export LD_LIBRARY_PATH=\"$LIBSHIM_DIR:\$LD_LIBRARY_PATH\""
        fi
    } >> "$BASHRC"
    echo "Added KONCLUDE_BIN (and LD_LIBRARY_PATH, if needed) to $BASHRC."
fi

echo "=== Done. KONCLUDE_BIN=$KONCLUDE_BIN ==="
echo "Start a new shell (or 'source ~/.bashrc') to pick it up automatically from now on."
