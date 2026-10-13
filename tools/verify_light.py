#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_light.py — 验证红绿灯显示距离补丁是否生效（不写死地址，自动定位）

用法:
    python3 tools/verify_light.py [期望值]      # 默认 3000

证据:
  A) 指令层: 用 locate_light 的签名扫描，确认 threshold/crossdistmax 块已是 movz 常量
  B) 数据层: 在进程可写内存里搜 m_stLightControl 结构体
     (判据: switch ∈ {0,1}，threshold == 期望值，crossdistmax == 期望值，
      crossdistmin 在合理区间)
"""
import os, re, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SIG = bytes.fromhex('e00000b4' '082040b9' '1f0d0071' '81000054' '083040b9' '890340f9')
NOP3 = bytes.fromhex('1f2003d5' * 3)


def parse_elf(d):
    e_phoff = struct.unpack_from('<Q', d, 0x20)[0]
    e_phentsize = struct.unpack_from('<H', d, 0x36)[0]
    e_phnum = struct.unpack_from('<H', d, 0x38)[0]
    loads = []
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        p_type, _, p_off, p_va, _, p_fsz, _, _ = struct.unpack_from('<IIQQQQQQ', d, o)
        if p_type == 1:
            loads.append((p_va, p_va + p_fsz, p_off, p_off + p_fsz))
    return loads


def find_light_blocks(d):
    """返回 {'threshold': (block, field), 'crossdistmax': (block, field), '__patched__': [...]}
    复用 locate_light 的分组逻辑（按键名序列 + 字段 +4 递增），不写死字段偏移窗口。"""
    import locate_light as LL
    loads = parse_elf(d)
    lo = hi = 0
    for va, ve, o, oe in loads:
        if va == o:
            lo, hi = o, oe
            break

    rows = []
    i = lo
    while True:
        j = d.find(LL.SIG, i, hi)
        if j < 0:
            break
        field = ((struct.unpack_from('<I', d, j + LL.STR_IN_BLOCK)[0] >> 10) & 0xfff) * 4
        rows.append((j, field, LL.nearest_key_before(d, lo, j), False))
        i = j + 4
    patched = []
    i = lo
    while True:
        j = d.find(LL.SIG_PATCHED_MID, i, hi)
        if j < 0:
            break
        g = j - 4
        if g >= lo and (struct.unpack_from('<I', d, g)[0] & 0xffe0001f) == 0x52800008 \
           and (struct.unpack_from('<I', d, g + 16)[0] & 0xffe0001f) == 0x52800008 \
           and d[g + 20:g + 24] == LL.SIG_PATCHED_TAIL:
            field = ((struct.unpack_from('<I', d, g + LL.STR_IN_BLOCK)[0] >> 10) & 0xfff) * 4
            rows.append((g, field, LL.nearest_key_before(d, lo, g), True))
            patched.append((g, field, None))
        i = j + 4
    rows.sort(key=lambda r: r[0])

    res = {}
    for grp in LL.group_light_blocks(rows):
        for b, field, k, pat in grp:
            if k and k[0] in ('threshold', 'crossdistmax'):
                res[k[0]] = (b, field)
    if patched:
        res['__patched__'] = patched
    return res


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    pkg = os.environ.get('PKG', 'com.baidu.BaiduMap')

    def sh(*a):
        return subprocess.run(['adb', 'shell', *a], capture_output=True, text=True).stdout

    pid = sh('pidof %s' % pkg).strip()
    if not pid:
        print('!! %s 没在跑，先启动它（或设 PKG=... 指定包名）' % pkg)
        return
    pid = int(pid)
    print('pkg =', pkg, ' pid =', pid)

    maps = sh('cat /proc/%d/maps' % pid)
    base = None
    for l in maps.splitlines():
        if 'libBaiduMapAutoEngine' in l and 'r-xp' in l:
            base = int(l.split('-')[0], 16); break
    if base is None:
        print('!! so 未加载'); return
    print('so base = %#x' % base)

    # 读磁盘上的 so（用 apktool 工程里的），做指令层判断
    apkdir = os.environ.get('APKDIR', os.path.join(os.path.dirname(HERE), '_work', 'apktool_full'))
    so_path = os.path.join(apkdir, 'lib', 'arm64-v8a', 'libBaiduMapAutoEngine.so')
    if not os.path.exists(so_path):
        print('!! 找不到 %s' % so_path); return
    d = open(so_path, 'rb').read()
    blocks = find_light_blocks(d)
    print('\n[A] 指令层（扫磁盘 so）')
    okA = True
    # 已补丁的块: field -> (block, imm)
    patched = {}
    for b, f, _ in blocks.get('__patched__', []):
        patched[f] = (b, (struct.unpack_from('<I', d, b)[0] >> 5) & 0xffff)

    # 关键字段偏移：随版本会变（20.15.2 是 0x10c/0x118，20.16.3 是 0x104/0x110）
    orig_field = {}
    if 'threshold' in blocks:
        orig_field['threshold'] = blocks['threshold'][1]
    if 'crossdistmax' in blocks:
        orig_field['crossdistmax'] = blocks['crossdistmax'][1]
    # 若磁盘 so 已是补丁态（原始块识别不到），从补丁态反推字段偏移：
    # 补丁态里 __patched__ 会给出所有被改块的 field，红绿灯区按 +4 递增取相邻两个
    if not orig_field and '__patched__' in blocks:
        fs = sorted({f for _, f, _ in blocks['__patched__']})
        if len(fs) >= 2:
            orig_field['threshold'] = fs[0]
            orig_field['crossdistmax'] = fs[-1]

    for name in ('threshold', 'crossdistmax'):
        # 先看原始态
        if name in orig_field and orig_field[name] in patched:
            b, v = patched[orig_field[name]]
            mark = 'OK' if v == want else '值不符(期望%d，实际%d)' % (want, v)
            print('  %-14s block=%#x field=+%#x  movz w8,#%d  %s'
                  % (name, b, orig_field[name], v, mark))
            if v != want:
                okA = False
            continue
        if name in orig_field:
            b = blocks[name][0]
            print('  %-14s block=%#x field=+%#x  原始未打补丁' % (name, b, orig_field[name]))
            okA = False
            continue
        # 原始态没识别到 → 整块都被改过，按「红绿灯区 + movz」猜
        cands = [(f, b, v) for f, (b, v) in patched.items()]
        cands.sort()
        idx = 0 if name == 'threshold' else (len(cands) - 1)
        if cands:
            f, b, v = cands[idx]
            mark = 'OK' if v == want else '值不符(期望%d，实际%d)' % (want, v)
            print('  %-14s block=%#x field=+%#x  movz w8,#%d  %s  (由补丁态反推)'
                  % (name, b, f, v, mark))
            if v != want:
                okA = False
            continue
        print('  %-14s 未定位到' % name)
        okA = False

    # 数据层：按磁盘 so 里识别到的字段偏移来读（版本无关）
    print('\n[B] 数据层（扫进程内存里的 m_stLightControl）')
    found_data = False
    if not orig_field or 'threshold' not in orig_field or 'crossdistmax' not in orig_field:
        print('  跳过：磁盘 so 里没定位到字段偏移（见 [A] 的提示）')
    else:
        f_t = orig_field['threshold']
        f_x = orig_field['crossdistmax']
        f_sw = f_t - 4                     # switch 紧挨在 threshold 前
        span = f_x - f_t
        print('  字段偏移（从 so 读出）: switch=+%#x threshold=+%#x crossdistmax=+%#x' % (f_sw, f_t, f_x))
        P = struct.pack('<i', want)
        cand = []
        for l in maps.splitlines():
            m = re.match(r'^([0-9a-f]+)-([0-9a-f]+) (\S+) \S+ \S+ \S+\s*(.*)$', l)
            if not m:
                continue
            a, b2 = int(m.group(1), 16), int(m.group(2), 16)
            perm, name = m.group(3), m.group(4)
            if 'w' not in perm or 'x' in perm:
                continue
            if 'dalvik' in name or '.art' in name or '.oat' in name or '.vdex' in name:
                continue
            sz = b2 - a
            if sz > 64 * 1024 * 1024:
                continue
            out = subprocess.run(['adb', 'shell',
                'dd if=/proc/%d/mem bs=1048576 skip=%d count=%d 2>/dev/null'
                % (pid, a // 1048576, sz // 1048576 + 1)], capture_output=True).stdout
            if not out:
                continue
            for off in range(0, len(out) - span - 8, 4):
                if out[off:off + 4] != P:
                    continue
                if out[off + span:off + span + 4] != P:
                    continue
                sw = struct.unpack_from('<i', out, off - 4)[0]
                if sw not in (0, 1):
                    continue
                cmin = struct.unpack_from('<i', out, off + (f_x - f_t) - 4)[0]
                if not (0 <= cmin <= 500):
                    continue
                cand.append((hex(a + off - 4), name, sw,
                             struct.unpack_from('<i', out, off)[0],
                             cmin,
                             struct.unpack_from('<i', out, off + span)[0]))
                break
        if cand:
            seen = set(); uniq = []
            for c in cand:
                if c[1] in seen: continue
                seen.add(c[1]); uniq.append(c)
            print('  命中 %d 处（%d 个不同区域）:' % (len(cand), len(uniq)))
            print('  %-16s %-28s %-6s %-8s %-9s %s'
                  % ('addr', 'region', 'switch', 'thresh', 'crossmin', 'crossmax'))
            for c in uniq[:8]:
                print('  %-16s %-28s %-6d %-8d %-9d %d' % c)
            found_data = True
            print('\n  ✓ switch/threshold/crossdistmax 全部符合预期 → 补丁生效、云控已被绕过')
        else:
            print('  未找到。可能还没进过导航；先跑一次导航再重试。')

    print('\n结论: 指令层 %s；数据层 %s' % ('OK' if okA else 'FAIL',
                                          'OK' if found_data else '未确认'))


if __name__ == '__main__':
    main()
