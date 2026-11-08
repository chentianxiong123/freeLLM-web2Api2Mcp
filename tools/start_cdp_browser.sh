#!/bin/bash
# 一键启动「CDP 真浏览器」：复制真实 profile（书签+历史+真实cookie）→ 删 Singleton → 起 Chrome 9222
#
# 思路（见用户文档：真实浏览器CDP复制Profile与指纹检测）：
#   - Chrome 官方限制默认 profile 不能开远程调试（必须非默认 --user-data-dir）
#   - 复制用户真实 profile 到专用目录 → 有书签+历史+真实 cookie（检测全过）
#   - 启动前删 Singleton*（否则报"正在现有的浏览器会话中打开"）
#
# 用法：
#   ./tools/start_cdp_browser.sh [profile_src] [profile_dst] [port]
#   默认：profile_src=~/.config/google-chrome, profile_dst=/home/a1/tutor-cdp-profile, port=9222
set -e
PROFILE_SRC="${1:-$HOME/.config/google-chrome}"
PROFILE_DST="${2:-/home/a1/tutor-cdp-profile}"
PORT="${3:-9222}"

# 首次复制真实 profile（已有则不重复，保留 cookie/书签/历史）
if [ ! -d "$PROFILE_DST" ]; then
  echo "[cdp] 复制真实 profile: $PROFILE_SRC -> $PROFILE_DST"
  cp -r "$PROFILE_SRC" "$PROFILE_DST"
fi

# 坑1：删 Singleton*（否则 Chrome 报"正在现有的浏览器会话中打开"）
rm -f "$PROFILE_DST"/Singleton* "$PROFILE_DST"/Default/Singleton*

# 已占用端口则先停（避免多实例抢 9222）
for pid in $(ss -ltnp 2>/dev/null | grep ":$PORT" | grep -oP 'pid=\K[0-9]+' | sort -u); do
  kill "$pid" 2>/dev/null && echo "[cdp] 停旧实例 $pid"
done
sleep 1

echo "[cdp] 启动 Chrome: --user-data-dir=$PROFILE_DST --remote-debugging-port=$PORT"
setsid nohup google-chrome \
  --user-data-dir="$PROFILE_DST" \
  --remote-debugging-port="$PORT" \
  --no-first-run --no-default-browser-check \
  --disable-quic --disable-http2 \
  > /tmp/cdp-tutor.log 2>&1 < /dev/null & disown

sleep 6
if curl -s "http://127.0.0.1:$PORT/json/version" | grep -q '"Browser"'; then
  echo "[cdp] ✅ 就绪: http://127.0.0.1:$PORT"
  curl -s "http://127.0.0.1:$PORT/json/version" | grep -o '"Browser": "[^"]*"'
else
  echo "[cdp] ❌ 未起来，日志:"; tail -8 /tmp/cdp-tutor.log
fi
