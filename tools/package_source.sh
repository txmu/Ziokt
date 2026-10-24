#!/usr/bin/env bash
# ==============================================================================
# Ziokt, Corium, Shadow6 三部分联合源码包构建脚本 (package_source.sh)
# 规范: 严格遵循纯文本源码交换协议，并通过完整 Lean 4 形式化网关与安全预检
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATE_TAG=$(date +%Y-%m-%d)
OUTPUT_ZIP="${SCRIPT_DIR}/Ziokt-Corium-Shadow6-source-${DATE_TAG}.zip"

echo "========================================================================"
echo "    ZIOKT & CORIUM & SHADOW6 TRIPLE JOINT SOURCE PACKAGING"
echo "========================================================================"
echo "目标路径: ${OUTPUT_ZIP}"
echo ""

# Ensure git repositories are clean before packaging
for repo_name in Ziokt Corium Shadow6; do
    repo_path="${SCRIPT_DIR}/${repo_name}"
    if [ -d "${repo_path}/.git" ]; then
        uncommitted=$(git -C "${repo_path}" status --porcelain 2>/dev/null || true)
        if [ -n "${uncommitted}" ]; then
            echo "警告: ${repo_name} 存在未提交更改:"
            echo "${uncommitted}"
        else
            echo "✓ ${repo_name} 工作区干净 ($(git -C "${repo_path}" rev-parse --short HEAD))"
        fi
    fi
done

echo ""
echo "=== 正在执行联合源码打包与安全预检 (package_joint_source.py) ==="
python3 "${SCRIPT_DIR}/Ziokt/tools/package_joint_source.py" \
    --repositories-root "${SCRIPT_DIR}" \
    --output "${OUTPUT_ZIP}" \
    --evidence "${SCRIPT_DIR}/chain-switch-verification.json"

echo ""
echo "=== 打包产物 SHA-256 校验 ==="
sha256sum "${OUTPUT_ZIP}"
ls -lh "${OUTPUT_ZIP}" "${OUTPUT_ZIP}.sha256"

echo ""
echo "========================================================================"
echo "    ✅ 三部分联合源码包构建与交付验证成功完成!"
echo "========================================================================"
