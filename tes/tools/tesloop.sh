#!/usr/bin/env bash
# tesloop.sh — 无人值守推进 tes/ 实验系统。
#
# 每轮循环起一个全新的 `kimi -p` 非交互会话（等价于手动 /new + /goal tes/goal.md），
# 执行 tesctl.py next 给出的恰好一个 action；run 收口（run-summary 完成）后停止，
# 等用户裁决 restart。评估串行性由「一次只跑一个 action」天然保证。
#
# 用法（建议放 tmux/nohup 里，完整 run 约 30+ 机时）：
#   tmux new -s tesloop 'tes/tools/tesloop.sh'                      # 默认任务
#   tmux new -s tesloop 'tes/tools/tesloop.sh <task>'               # 指定任务
# 位置参数 <task> 优先于 TESLOOP_TASK；任务 = tes/ 下含 config.json 的一级子目录。
# 注意：全机器同时只允许一个 tesloop 实例（测量纪律：任何时刻只能有一个构建/测量负载）。
# 环境变量：
#   TESLOOP_TASK       任务名（默认 grhsim-am-coremark，被位置参数覆盖）
#   TESLOOP_MODEL      kimi 会话的模型别名（默认 kimi-code/k3，传给 kimi -m；
#                      thinking effort 用模型自身默认 high，不强制覆盖）
#   TESLOOP_MAX_ITERS  兜底最大 action 数（默认 80，防死循环）
#   TESLOOP_RETRIES    kimi 会话失败的重试次数（默认 3，应对网络抖动等瞬时故障）
#   TESLOOP_RETRY_DELAY 重试间隔秒数（默认 300）
set -uo pipefail

cd "$(dirname "$0")/../.."   # playground 仓库根
ROOT="$(pwd)"
TASK="${1:-${TESLOOP_TASK:-grhsim-am-coremark}}"
if [[ ! -f "tes/$TASK/config.json" ]]; then
  echo "[tesloop] 任务不存在：tes/$TASK/（无 config.json）" >&2
  exit 1
fi
MODEL="${TESLOOP_MODEL:-kimi-code/k3}"
MAX_ITERS="${TESLOOP_MAX_ITERS:-80}"
RETRIES="${TESLOOP_RETRIES:-3}"
RETRY_DELAY="${TESLOOP_RETRY_DELAY:-300}"
LOG_DIR="build/logs/tesloop"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/tesloop-$(date +%Y%m%d-%H%M%S).log"

# 防多实例（与评估用的 build/tes/LOCK 无关，只锁 loop 本身）
exec 9>"build/logs/tesloop.lock"
if ! flock -n 9; then
  echo "[tesloop] 已有 tesloop 实例在跑，退出" | tee -a "$LOG"
  exit 1
fi

next_json() {
  python3 tes/tools/tesctl.py --task "$TASK" next --json
}

say() { echo "[tesloop] $(date -Is) $*" | tee -a "$LOG"; }

say "启动：task=$TASK model=$MODEL（effort 用模型默认） max_iters=$MAX_ITERS log=$LOG"
# 模型别名预检：未配置时提醒（不致命，kimi -m 会以明确报错失败）
if ! grep -qF "[models.\"$MODEL\"]" "${KIMI_CODE_HOME:-$HOME/.kimi-code}/config.toml" 2>/dev/null; then
  say "警告：config.toml 中未找到模型别名 \"$MODEL\"，请先在 ~/.kimi-code/config.toml 配置（如 [models.\"kimi-code/k3\"]）"
fi
prev_type=""
for ((i = 1; i <= MAX_ITERS; i++)); do
  na="$(next_json)"
  if [[ -z "$na" ]]; then
    say "tesctl next 无输出（状态损坏？），停止待人工检查"
    exit 1
  fi
  type="$(printf '%s' "$na" | python3 -c 'import sys,json; print(json.load(sys.stdin)["type"])')"
  say "iter $i: next=$type"

  # run-summary 完成后 next 变为 run-closed：run 已收口，停。
  # （run-init 且 prev_type 非空是防御性分支：正常流程会先经过 run-closed。）
  if [[ "$type" == "run-closed" || ( "$type" == "run-init" && -n "$prev_type" ) ]]; then
    say "run 已收口（$type）。停止，等用户裁决 restart。"
    exit 0
  fi

  say "iter $i: 起新 kimi 会话执行 action=$type"
  rc=0
  for ((attempt = 1; attempt <= RETRIES; attempt++)); do
    kimi -m "$MODEL" -p "读取 $ROOT/tes/goal.md 并严格遵循其中定义：推进 tes/ 实验系统恰好一个 action \
（python3 tes/tools/tesctl.py --task $TASK next 给出的那个，当前为 $type），完成后停止，\
不得自发开始下一个 action。多任务歧义时任务为 $TASK（tesctl 加 --task $TASK 前缀）。" \
      2>&1 | tee -a "$LOG"
    rc=$?   # pipefail 已开：kimi 失败时 rc 为 kimi 的退出码，不会被 tee 吞掉
    if (( rc == 0 )); then
      break
    fi
    say "kimi 会话退出码 $rc（第 $attempt/$RETRIES 次）"
    if (( attempt < RETRIES )); then
      say "${RETRY_DELAY}s 后重试（新会话，状态机断点续跑）"
      sleep "$RETRY_DELAY"
    fi
  done
  if (( rc != 0 )); then
    say "连续 $RETRIES 次失败（网络中断/token 用尽等），停止待人工检查；恢复后重跑本脚本即可续跑（日志见 $LOG）"
    exit "$rc"
  fi

  na2="$(next_json)"
  if [[ "$na2" == "$na" ]]; then
    say "action 后状态机未推进（next 仍是 $type），停止待人工检查（日志见 $LOG）"
    exit 1
  fi
  prev_type="$type"
done

say "达到 MAX_ITERS=$MAX_ITERS 仍未收口，停止待人工检查"
exit 1
