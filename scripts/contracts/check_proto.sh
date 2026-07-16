#!/usr/bin/env bash
# Verifies the three gRPC proto contracts are byte-identical to the frozen copies.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

echo "== proto checksum verification =="
sha256sum -c contracts/proto/checksums.sha256

echo "== proto byte-for-byte diff =="
diff -u contracts/proto/basket.proto src/Services/Basket/Basket.API/Proto/basket.proto
diff -u contracts/proto/catalog.proto src/Services/Catalog/Catalog.API/Proto/catalog.proto
diff -u contracts/proto/ordering.proto src/Services/Ordering/Ordering.API/Proto/ordering.proto
echo "proto contracts unchanged"
