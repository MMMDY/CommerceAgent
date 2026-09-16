#!/usr/bin/env bash
set -euo pipefail

release_id=""
output=""
report=""
soak_report=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-id) release_id="${2:-}"; shift 2 ;;
    --output) output="${2:-}"; shift 2 ;;
    --report) report="${2:-}"; shift 2 ;;
    --soak-report) soak_report="${2:-}"; shift 2 ;;
    *) echo "usage: $0 --release-id ID --output docs/releases/ID --report report.json --soak-report soak.json" >&2; exit 2 ;;
  esac
done
[[ "$release_id" =~ ^[a-z0-9][a-z0-9._-]{2,63}$ && -n "$output" && -n "$report" && -n "$soak_report" ]] || {
  echo "release-id, output, report and soak-report are required" >&2
  exit 2
}
[[ -f "$report" ]] || { echo "release report is unavailable" >&2; exit 2; }
[[ -f "$soak_report" ]] || { echo "bounded soak report is unavailable" >&2; exit 2; }
[[ -z "$(git status --porcelain)" ]] || { echo "worktree_not_clean" >&2; exit 1; }
commit="$(git rev-parse HEAD)"
dataset="evals/commerce_bench_zh/cases.jsonl"
rubric="evals/commerce_bench_zh/rubrics.json"
manifest_output="${output}/manifest.json"
python scripts/verify_soak_report.py "$soak_report" --min-duration 10m --min-samples 10 --max-errors 0 >/dev/null
python scripts/create_release_manifest.py --output "$manifest_output" >/dev/null
python - "$manifest_output" "$release_id" "$report" "$soak_report" <<'PY'
import json
import sys
from pathlib import Path

path, release_id, report, soak_report = sys.argv[1:]
manifest = json.loads(Path(path).read_text(encoding="utf-8"))
manifest["release_id"] = release_id
manifest["report"] = report
manifest["bounded_soak_report"] = soak_report
Path(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
tmp_summary="${output}/release-summary.md.tmp.$$"
cat > "$tmp_summary" <<EOF
# CommerceAgent ${release_id}

状态：\`internal beta / mock business data\`

候选源码 commit：\`${commit}\`
数据集 SHA-256：\`$(sha256sum "$dataset" | awk '{print $1}')\`
Rubric SHA-256：\`$(sha256sum "$rubric" | awk '{print $1}')\`
评测报告：\`${report}\`

本摘要只记录可脱敏的版本指纹，不包含 API key、数据库 URL、Judge prompt 或原始 payload。
正式 Release gate 需额外通过 \`scripts/release_check.py\` 和 bounded soak 校验：独立 Judge、30 条校准一致率至少 90%、300 case 三次运行完整、10 分钟 bounded soak 报告完成且无错误。
bounded soak 报告：\`${soak_report}\`；该证据不代表生产环境的长期稳定性保证。
EOF
mv -- "$tmp_summary" "${output}/release-summary.md"
printf 'release-evidence-created output=%s source_commit=%s\n' "$output" "$commit"
