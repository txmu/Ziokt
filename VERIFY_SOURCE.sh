#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detect Corium directory
if [ -d "${SCRIPT_DIR}/corium" ]; then
    CORIUM_DIR="${SCRIPT_DIR}/corium"
elif [ -d "${SCRIPT_DIR}/Corium" ]; then
    CORIUM_DIR="${SCRIPT_DIR}/Corium"
elif [ -d "${SCRIPT_DIR}/../Corium" ]; then
    CORIUM_DIR="$(cd "${SCRIPT_DIR}/../Corium" && pwd)"
elif [ -d "${SCRIPT_DIR}/../corium" ]; then
    CORIUM_DIR="$(cd "${SCRIPT_DIR}/../corium" && pwd)"
else
    echo "Error: Cannot locate Corium directory" >&2
    exit 1
fi

# Detect Ziokt directory
if [ -d "${SCRIPT_DIR}/ziokt/tests" ] || [ -f "${SCRIPT_DIR}/ziokt/__init__.py" ]; then
    ZIOKT_DIR="${SCRIPT_DIR}"
elif [ -d "${SCRIPT_DIR}/ziokt" ]; then
    ZIOKT_DIR="${SCRIPT_DIR}/ziokt"
elif [ -d "${SCRIPT_DIR}/Ziokt" ]; then
    ZIOKT_DIR="${SCRIPT_DIR}/Ziokt"
elif [ -d "${SCRIPT_DIR}/../Ziokt" ]; then
    ZIOKT_DIR="$(cd "${SCRIPT_DIR}/../Ziokt" && pwd)"
else
    echo "Error: Cannot locate Ziokt directory" >&2
    exit 1
fi

echo "========================================================================"
echo "    ZIOKT & CORIUM SOVEREIGN SOURCE DISTRIBUTION: CI VERIFICATION"
echo "========================================================================"
echo "Corium directory: ${CORIUM_DIR}"
echo "Ziokt directory:  ${ZIOKT_DIR}"
echo ""

echo "=== [1/6] Running Corium CI Syntax Checks ==="
(
    cd "${CORIUM_DIR}"
    for file in *.sh ci/*.sh; do [ -f "$file" ] && bash -n "$file"; done
    python3 ci/static-checks.py
)

echo ""
echo "=== [2/6] Running Unified Consensus Kernel Tests ==="
python3 "${CORIUM_DIR}/test_consensus_core.py"

echo ""
echo "=== [3/6] Running Multi-Node Sovereign Disconnection Simulation ==="
python3 "${CORIUM_DIR}/test_multinode_sovereign.py"

echo ""
echo "=== [4/6] Running Content Fabric Sovereign Survival & Peer Repair ==="
PYTHONPATH="${ZIOKT_DIR}" python3 "${ZIOKT_DIR}/tests/test_content_sovereign_survival.py"

echo ""
echo "=== [5/6] Running Lean 4 Formal Verification (76 Theorems, 0 Sorry) ==="
(
    cd "${CORIUM_DIR}"
    bash formal/check_all_formal.sh
)

echo ""
echo "=== [6/6] Running CI Regression & Integration Test Suite ==="
(
    cd "${CORIUM_DIR}"
    python3 -m unittest -v test_engine_weights test_engine_governance_cli test_work_weight_policy test_ci_integration
)

echo ""
echo "========================================================================"
echo "    ✅ ALL SOURCE AND CI VERIFICATIONS PASSED SUCCESSFULLY!"
echo "========================================================================"
