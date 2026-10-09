#!/bin/sh
# Fetch the PINNED engine release and its two Lean checkers for the live forge.
# Every file is checked against the release's own SHASUMS.txt before it is used.
set -eu
TAG="${OO_ENGINE_TAG:-v2.0.1}"
BASE="https://github.com/fabio-rovai/open-ontologies/releases/download/${TAG}"
mkdir -p api/_bin
curl -fsSL -o api/_bin/SHASUMS.txt "${BASE}/SHASUMS.txt"
fetch() {
  curl -fsSL -o "api/_bin/$2" "${BASE}/$1"
  want=$(grep "  $1\$" api/_bin/SHASUMS.txt | awk '{print $1}')
  got=$(sha256sum "api/_bin/$2" | awk '{print $1}')
  [ -n "$want" ] || { echo "no checksum for $1 in SHASUMS.txt"; exit 1; }
  [ "$want" = "$got" ] || { echo "checksum mismatch for $1: want $want got $got"; exit 1; }
  chmod +x "api/_bin/$2"
  echo "  $2  $got"
}
fetch open-ontologies-x86_64-unknown-linux-gnu open-ontologies
fetch oo-cert-x86_64-unknown-linux-gnu oo-cert
fetch oo-shacl-x86_64-unknown-linux-gnu oo-shacl
echo "${TAG}" > api/_bin/TAG
echo "engine ${TAG} pinned"
