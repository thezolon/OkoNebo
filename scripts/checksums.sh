#!/usr/bin/env bash
# scripts/checksums.sh <version>
#
# Produces a SHA-256 checksum file for the named release.
# Run from the project root after `git tag vX.Y.Z` is in place.
#
# Usage:
#   bash scripts/checksums.sh v1.0.0
#
# Output:
#   release-v1.0.0-checksums.sha256

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 <version>   (e.g. v1.0.0)" >&2
    exit 1
fi

OUTFILE="release-${VERSION}-checksums.sha256"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "[checksums] creating source archive for $VERSION"

# Create a clean source tarball from the git tag
ARCHIVE="${TMPDIR}/OkoNebo-${VERSION}.tar.gz"
git archive --format=tar.gz --prefix="OkoNebo-${VERSION}/" \
    "$VERSION" -o "$ARCHIVE" 2>/dev/null \
    || { echo "[checksums] ERROR: tag '$VERSION' not found in git history" >&2; exit 1; }

# Also include a zip for Windows users
ARCHIVE_ZIP="${TMPDIR}/OkoNebo-${VERSION}.zip"
git archive --format=zip --prefix="OkoNebo-${VERSION}/" \
    "$VERSION" -o "$ARCHIVE_ZIP" 2>/dev/null

echo "[checksums] computing SHA-256"

# sha256sum (Linux) vs shasum -a 256 (macOS)
if command -v sha256sum &>/dev/null; then
    _sha256() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum &>/dev/null; then
    _sha256() { shasum -a 256 "$1" | awk '{print $1}'; }
else
    echo "[checksums] ERROR: no sha256 tool found (macOS: brew install coreutils)" >&2
    exit 1
fi

{
    echo "$(_sha256 "$ARCHIVE")  OkoNebo-${VERSION}.tar.gz"
    echo "$(_sha256 "$ARCHIVE_ZIP")  OkoNebo-${VERSION}.zip"
} > "$OUTFILE"

cp "$ARCHIVE"     "OkoNebo-${VERSION}.tar.gz"
cp "$ARCHIVE_ZIP" "OkoNebo-${VERSION}.zip"

echo "[checksums] written to $OUTFILE"
cat "$OUTFILE"
echo ""
echo "[checksums] release archives:"
echo "  OkoNebo-${VERSION}.tar.gz"
echo "  OkoNebo-${VERSION}.zip"
echo ""
echo "[checksums] attach $OUTFILE to the GitHub Release page."
