#!/bin/sh
# Fetch the PINNED engine release and its two Lean checkers for the live forge.
# Each file must match TWO checksums: the release's own SHASUMS.txt, and the
# value written below in this repository. SHASUMS.txt alone is not enough,
# because it comes from the same place as the binaries, so whoever could
# replace one could replace both. A tag with no pinned values here is refused;
# to move to a new release, add its x86_64 Linux lines from its SHASUMS.txt.
set -eu
TAG="${OO_ENGINE_TAG:-v2.0.1}"
BASE="https://github.com/fabio-rovai/open-ontologies/releases/download/${TAG}"

pinned() {
  case "${TAG} $1" in
    "v2.0.1 open-ontologies-x86_64-unknown-linux-gnu") echo 7a54594aad74c572c993fb09f1d0ea3c661f2348592dde542bb8f2fdfeba3572 ;;
    "v2.0.1 oo-cert-x86_64-unknown-linux-gnu") echo 68223b4db193783a52bd2810a66ce2ad3a3780f963a5ef84753564c051e3e532 ;;
    "v2.0.1 oo-shacl-x86_64-unknown-linux-gnu") echo f965878d06c1a0ea9c80bb36b668dd02f0aec5ab4ccccb1474975af18de799da ;;
    *) echo "" ;;
  esac
}

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
  else shasum -a 256 "$1" | awk '{print $1}'; fi
}

mkdir -p api/_bin
curl -fsSL -o api/_bin/SHASUMS.txt "${BASE}/SHASUMS.txt"
fetch() {
  pin=$(pinned "$1")
  [ -n "$pin" ] || { echo "build.sh pins no checksum for $1 at ${TAG}"; exit 1; }
  curl -fsSL -o "api/_bin/$2" "${BASE}/$1"
  want=$(grep "  $1\$" api/_bin/SHASUMS.txt | awk '{print $1}')
  got=$(sha256 "api/_bin/$2")
  [ -n "$want" ] || { echo "no checksum for $1 in SHASUMS.txt"; exit 1; }
  [ "$want" = "$got" ] || { echo "checksum mismatch for $1 against SHASUMS.txt: want $want got $got"; exit 1; }
  [ "$pin" = "$got" ] || { echo "checksum mismatch for $1 against the value pinned in build.sh: want $pin got $got"; exit 1; }
  chmod +x "api/_bin/$2"
  echo "  $2  $got"
}
fetch open-ontologies-x86_64-unknown-linux-gnu open-ontologies
fetch oo-cert-x86_64-unknown-linux-gnu oo-cert
fetch oo-shacl-x86_64-unknown-linux-gnu oo-shacl
echo "${TAG}" > api/_bin/TAG
echo "engine ${TAG} pinned"
