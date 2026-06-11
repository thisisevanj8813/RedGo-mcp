#!/usr/bin/env bash
# RedGo: 启动带 CDP 调试端口的真实 Chrome（独立 profile，不碰日常 Chrome）。
# 首次启动后在打开的窗口里手动登录小红书，登录态持久化在 profile 目录。
# 等价于 `redgo launch-chrome` 子命令；本脚本是无 Python 环境时的备用入口。
set -euo pipefail

PORT="${REDGO_CDP_PORT:-9222}"
PROFILE_DIR="${REDGO_PROFILE_DIR:-$HOME/.redgo/chrome-profile}"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [[ ! -x "$CHROME" ]]; then
  echo "❌ 找不到 Chrome：$CHROME" >&2
  exit 1
fi

# 端口上已有活着的 CDP 实例 → 直接复用
if curl -s --max-time 2 "http://localhost:${PORT}/json/version" >/dev/null 2>&1; then
  echo "✅ localhost:${PORT} 已有可用的 CDP 实例，直接复用，无需重复启动。"
  exit 0
fi

# 端口被占但不是 CDP → 提示换端口
if lsof -nP -i ":${PORT}" >/dev/null 2>&1; then
  echo "❌ 端口 ${PORT} 被其他进程占用且不响应 CDP。换端口重试：" >&2
  echo "   REDGO_CDP_PORT=9223 $0   （MCP 侧对应设 REDGO_CDP_URL=http://localhost:9223）" >&2
  exit 1
fi

mkdir -p "$PROFILE_DIR"
echo "🚀 启动 Chrome（CDP 端口 ${PORT}，profile: ${PROFILE_DIR}）"
echo "   首次使用：请在打开的窗口里登录小红书（建议用非主力账号），登录完成后保持窗口开着。"

exec "$CHROME" \
  --remote-debugging-port="${PORT}" \
  --user-data-dir="$PROFILE_DIR" \
  --remote-allow-origins="http://localhost:${PORT}" \
  --no-first-run \
  --no-default-browser-check \
  "https://www.xiaohongshu.com"
