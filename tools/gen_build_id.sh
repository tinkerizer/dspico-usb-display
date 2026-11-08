#!/usr/bin/env bash
# Bumps the build number when DS sources change, and writes it to BuildId.h.
# The header is only rewritten on a change, so unchanged builds recompile nothing.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
header="$root/ds/common/BuildId.h"
state="$root/ds/.build_number"

hash="$(find "$root/ds/arm7/source" "$root/ds/arm9/source" "$root/ds/common" "$root/platform" \
    -type f ! -name BuildId.h -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"

number=0
saved_hash=""
if [[ -f "$state" ]]; then
    read -r number saved_hash < "$state"
fi

if [[ "$hash" != "$saved_hash" || ! -f "$header" ]]; then
    number=$((number + 1))
    echo "$number $hash" > "$state"
    printf '#pragma once\n\n#define BUILD_NUMBER %d\n' "$number" > "$header"
    echo "Build number $number"
fi
