#!/usr/bin/env bash
# Refresh the vendored hev layer TypeScript client (app/vendor/hevlayer) from
# the sibling checkout. The client is unpublished, so the web app depends on it
# as an in-tree file: dep (file:vendor/hevlayer) and the web image bundles it at
# build time. Vendored — not injected from the sibling like the Python services
# — because npm bakes the file: link's relative path into the lockfile, and an
# out-of-tree ../../ link escapes the image filesystem root from /app.
#
# Run this whenever ../layer/clients/typescript changes, then commit the result.
set -euo pipefail

cd "$(dirname "$0")/.."

SRC="${LAYER_TS_CLIENT_SRC:-../layer/clients/typescript}"
DST="app/vendor/hevlayer"

[[ -d "$SRC/src" ]] || { echo "ERROR: $SRC/src not found (set LAYER_TS_CLIENT_SRC)"; exit 1; }

echo "==> Syncing $SRC -> $DST"
rm -rf "$DST"
mkdir -p "$DST"
cp "$SRC/package.json" "$SRC/README.md" "$SRC/tsconfig.json" "$DST/"
cp -R "$SRC/src" "$DST/src"

echo "==> Building dist (src only; the test tree needs @types/node we don't ship)"
printf '{"extends":"./tsconfig.json","include":["src/**/*.ts"],"exclude":["test"]}' \
  > "$DST/tsconfig.build.json"
app/node_modules/.bin/tsc -p "$DST/tsconfig.build.json"
rm -f "$DST/tsconfig.build.json"

echo "==> Done. Vendored hevlayer client refreshed:"
ls "$DST/dist/src/index.js"
echo "    Review & commit app/vendor/hevlayer, then redeploy the web image."
