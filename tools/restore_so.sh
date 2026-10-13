#!/usr/bin/env bash
# restore_so.sh — 把 so 还原成原始版本（用于重新开始 / 排查）
#
# 用法:
#   tools/restore_so.sh                # 从 _work/so_orig.bak 还原
#   tools/restore_so.sh <某个.bak>     # 从指定备份还原
#
# 注意: 备份绝不能放在 lib/ 目录下，否则会被 apktool 打进 apk（包体暴涨 ~19MB）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SO="$ROOT/_work/apktool_full/lib/arm64-v8a/libBaiduMapAutoEngine.so"
BAK="${1:-$ROOT/_work/so_orig.bak}"

if [ ! -f "$BAK" ]; then
  echo "找不到备份 $BAK"
  echo "可从原始 apk 里取（注意别写进 lib/）:"
  echo "  unzip -p $ROOT/_work/baidumap_2016_3.apk lib/arm64-v8a/libBaiduMapAutoEngine.so > $ROOT/_work/so_orig.bak"
  echo "  tools/restore_so.sh"
  exit 1
fi

cp "$BAK" "$SO"
echo "已还原: $SO  <-  $BAK"
shasum -a 1 "$SO"

# 体检：lib/ 下不该有非 .so 文件
JUNK="$(find "$ROOT/_work/apktool_full/lib" -type f ! -name '*.so' 2>/dev/null || true)"
if [ -n "$JUNK" ]; then
  echo "[!] lib/ 下有会被打包的非 .so 文件，正在移出:"
  echo "$JUNK" | while read -r f; do
    echo "    $f -> $ROOT/_work/"
    mv "$f" "$ROOT/_work/"
  done
else
  echo "lib/ 干净（无非 .so 文件）"
fi
