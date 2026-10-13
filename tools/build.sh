#!/usr/bin/env bash
# build.sh — 一条命令：改 so -> 重打包 -> 重签 -> 装机
#
# 用法:
#   tools/build.sh                       # so/smali 已改好，只重打包+重签+装机
#   tools/build.sh --light 3000          # 先把红绿灯显示距离改成 3000 米再走完整流程
#   tools/build.sh --so-only             # 只打包重签，不装
#   PKG=com.baidu.naviauto tools/build.sh   # 手动指定包名（默认从 manifest 自动读）
#
# 前置:
#   - apktool 3.x 在 PATH
#   - _work/keys/bmap.keystore (口令 123456 / 别名 bmap)
#   - /tmp/uber-apk-signer.jar
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/_work"
APKDIR="${APKDIR:-$WORK/apktool_full}"   # 换版本时可 APKDIR=_work/apktool_full_21132 tools/build.sh
SO="$APKDIR/lib/arm64-v8a/libBaiduMapAutoEngine.so"
# 备份放到 _work/ 下，**绝不能**放在 lib/ 里（apktool 会把 lib/ 下所有文件打进 apk）
SO_BAK="${SO_BAK:-$WORK/so_orig.bak}"    # 换版本时指定对应的原始 so 备份
KS="$WORK/keys/bmap.keystore"
SIGNER="${SIGNER:-/tmp/uber-apk-signer.jar}"

LIGHT=""
SO_ONLY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --light)   LIGHT="$2"; shift 2 ;;
    --so-only) SO_ONLY=1; shift ;;
    *) echo "unknown arg: $1"; exit 2 ;;
  esac
done

# 包名：优先环境变量，其次从 manifest 自动读（换版本不用改脚本）
PKG="${PKG:-}"
if [ -z "$PKG" ]; then
  PKG="$(grep -o 'package="[^"]*"' "$APKDIR/AndroidManifest.xml" | head -1 | sed 's/package="//; s/"//')"
fi
echo "[i] 包名 = $PKG"

# 1) 可选：改红绿灯显示距离
if [ -n "$LIGHT" ]; then
  if [ ! -f "$SO_BAK" ]; then
    echo "[i] 首次运行，备份原始 so -> $SO_BAK"
    cp "$SO" "$SO_BAK"
  fi
  # 保险：清掉误放在 lib/ 里的 .bak（否则会被打进 apk，体积暴涨 ~19MB）
  for junk in "$APKDIR"/lib/*/*.bak "$APKDIR"/lib/*/*.so.bak; do
    [ -e "$junk" ] && { echo "[!] 发现会被打包的备份，移走: $junk"; mv "$junk" "$WORK/"; }
  done
  echo "[1/4] patch 红绿灯显示距离 = ${LIGHT}m"
  python3 "$ROOT/tools/locate_light.py" "$SO" --patch "$LIGHT"
else
  echo "[1/4] 跳过 so patch"
fi

# 1.5) 打包前体检：lib/ 里不该有非 .so 文件
echo "[i] lib/ 目录体检"
find "$APKDIR/lib" -type f ! -name '*.so' -print | while read -r f; do
  echo "  [!] 非 .so 文件（会被打进 apk）: $f"
done

# 2) 重打包
echo "[2/4] apktool b"
apktool b "$APKDIR" -o "$WORK/patched_raw.apk"

# 3) 重签
echo "[3/4] 重签"
rm -f "$WORK/signed/patched_raw-signed.apk" "$WORK/signed/patched_raw-signed.apk.idsig"
java -jar "$SIGNER" -a "$WORK/patched_raw.apk" \
  --ks "$KS" --ksAlias bmap --ksPass 123456 --ksKeyPass 123456 \
  -o "$WORK/signed" --allowResign --skipZipAlign

if [ "$SO_ONLY" = "1" ]; then
  echo "[4/4] --so-only，跳过装机。产物: $WORK/signed/patched_raw-signed.apk"
  exit 0
fi

# 4) 装机（换签后必须 -d）
echo "[4/4] adb install"
adb shell "am force-stop $PKG" || true
adb install -r -d "$WORK/signed/patched_raw-signed.apk"
echo "完成。验证: PKG=$PKG python3 tools/verify_light.py 3000"
