# Phase N7 回滚 / Kill Switch 传播测量器

日期：2026-09-18

## 已实现

- `src/release/propagation.py` 提供 `evaluate_propagation()`；
- 只有观测到控制面变更后的真实请求，且没有继续命中被禁用版本/Skill，才可能返回 `pass`；
- 没有 post-change 请求观测时返回 `incomplete`，不会把“没有请求”误算为传播成功；
- 首个请求超过 60 秒、控制变更前出现请求或变更后仍有禁止命中时返回 `fail`；
- `scripts/check_propagation.py` 支持脱敏 JSON 证据检查，可用于回滚、停止和 tenant Skill kill switch；
- rollback 证据额外要求 `historical_run_reference_preserved=true`，明确证明历史 Run 仍保留不可变版本引用；缺失或为 false 时分别返回 `incomplete`/`fail`，不会只凭新请求未命中就判定回滚完成；
- 所有时间戳要求带时区，结果保留动作、耗时和失败原因。

## 验证

```text
conda run -n commerce pytest -q tests/unit/test_propagation.py
4 passed

conda run -n commerce python -m ruff check src/release/propagation.py tests/unit/test_propagation.py scripts/check_propagation.py
All checks passed

conda run -n commerce python -m mypy src/release/propagation.py
Success: no issues found in 1 source file
```

## 尚未勾选的验收项

该工具只定义并校验传播证据，当前没有真实生产控制面变更和 post-change 请求记录，因此 rollback、自动停止和 kill switch 的“一分钟内生效”验收仍保持 `[ ]`。
