#!/usr/bin/env bash
set -euo pipefail

release_id=""
output=""
report=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-id) release_id="${2:-}"; shift 2 ;;
    --output) output="${2:-}"; shift 2 ;;
    --report) report="${2:-}"; shift 2 ;;
    *) echo "usage: $0 --release-id ID --output docs/releases/ID --report report.json" >&2; exit 2 ;;
  esac
done
[[ "$release_id" =~ ^[a-z0-9][a-z0-9._-]{2,63}$ && -n "$output" && -n "$report" ]] || {
  echo "release-id, output and report are required" >&2
  exit 2
}
[[ -f "$report" ]] || { echo "release report is unavailable" >&2; exit 2; }
[[ -z "$(git status --porcelain)" ]] || { echo "worktree_not_clean" >&2; exit 1; }
commit="$(git rev-parse HEAD)"
dataset="evals/commerce_bench_zh/cases.jsonl"
rubric="evals/commerce_bench_zh/rubrics.json"
mkdir -p "$output"
tmp_summary="${output}/release-summary.md.tmp.$$"
cat > "$tmp_summary" <<EOF
# CommerceAgent ${release_id}

状态：\`internal beta / mock business data\`

候选源码 commit：\`${commit}\`
数据集 SHA-256：\`$(sha256sum "$dataset" | awk '{print $1}')\`
Rubric SHA-256：\`$(sha256sum "$rubric" | awk '{print $1}')\`
评测报告：\`${report}\`

本摘要只记录可脱敏的版本指纹，不包含 API key、数据库 URL、Judge prompt 或原始 payload。
正式 Release gate 需额外通过 \`scripts/release_check.py\`：独立 Judge、30 条校准一致率至少 90%、300 case 三次运行完整、24 小时 soak 完成。
EOF
mv -- "$tmp_summary" "${output}/release-summary.md"
tmp_manifest="${output}/manifest.json.tmp.$$"
printf '{"release_id":"%s","source_commit":"%s","report":"%s"}\n' "$release_id" "$commit" "$report" > "$tmp_manifest"
mv -- "$tmp_manifest" "${output}/manifest.json"
printf 'release-evidence-created output=%s source_commit=%s\n' "$output" "$commit"
