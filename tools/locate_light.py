#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
locate_light.py — 在新版 libBaiduMapAutoEngine.so 中定位红绿灯显示距离解析点

用法:
    python3 tools/locate_light.py <libBaiduMapAutoEngine.so>              # 只定位
    python3 tools/locate_light.py <libBaiduMapAutoEngine.so> --patch 3000 # 定位并改 so

原理
----
云控 JSON 的 light_detail 每次启动会被服务端覆盖，改文件无效。
但解析函数在读完 cJSON 数值后会把结果写进引擎配置结构体，
所以直接 patch so 里的赋值指令即可强制显示距离。

该解析函数里每个数值键都是同一套 7 条指令模板:

    cbz  x0, skip          ; e0 00 00 b4
    ldr  w8, [x0, #0x20]   ; 08 20 40 b9   (cJSON 类型)
    cmp  w8, #0x3          ; 1f 0d 00 71
    b.ne skip              ; 81 00 00 54
    ldr  w8, [x0, #0x30]   ; 08 30 40 b9   (数值)
    ldr  x9, [x28]         ; 89 03 40 f9   (配置结构体基址)
    str  w8, [x9, #imm*4]  ; 28 .. .. b9

因此用「6 条固定指令」做签名全 .text 扫描即可定位，与版本无关；
再往前找最近的 adrp+add 字符串引用，就知道是哪个键。

补丁内容（threshold / crossdistmax 两块）:
    把守卫 4 条 (cbz/ldr/cmp/b.ne) 换成 movz w8,#IMM + 3×nop，
    再把取值 ldr w8,[x0,#0x30] 换成 movz w8,#IMM。
    这样即使云控不下发该键，也会无条件写入 IMM 米。
"""
import os, struct, sys

SIG = bytes.fromhex(
    'e00000b4'   # cbz  x0, skip
    '082040b9'   # ldr  w8,[x0,#0x20]
    '1f0d0071'   # cmp  w8,#0x3
    '81000054'   # b.ne skip
    '083040b9'   # ldr  w8,[x0,#0x30]
    '890340f9'   # ldr  x9,[x28]
)
STR_IN_BLOCK = 24        # str 在块内的相对偏移
NOP = bytes.fromhex('1f2003d5')

# 已打过补丁后的块: movz w8,#IMM ; nop nop nop ; movz w8,#IMM ; ldr x9,[x28] ; str w8,[x9,#imm]
SIG_PATCHED_MID = bytes.fromhex('1f2003d5' '1f2003d5' '1f2003d5')  # 3×nop
SIG_PATCHED_TAIL = bytes.fromhex('890340f9')                        # ldr x9,[x28]


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


def cstr(d, off, n=96):
    e = d.find(b'\x00', off)
    return d[off:min(e, off + n)].decode('utf-8', 'replace')


def nearest_key_before(d, lo, pos, max_back=0x3000):
    """从 pos 往前找最近的一条 adrp+add 字符串引用，返回 (字符串, adrp偏移) 或 None"""
    for i in range(pos - 4, max(lo, pos - max_back), -4):
        w = struct.unpack_from('<I', d, i)[0]
        if (w & 0x9f000000) != 0x90000000:
            continue
        immhi = (w >> 5) & 0x7ffff
        immlo = (w >> 29) & 3
        imm = (immhi << 2) | immlo
        if imm & (1 << 20):
            imm -= 1 << 21
        page = (i & ~0xfff) + (imm << 12)
        reg = w & 31
        for k in range(1, 9):
            w2 = struct.unpack_from('<I', d, i + 4 * k)[0]
            if (w2 & 0xff800000) == 0x91000000:
                rd = w2 & 31
                rn = (w2 >> 5) & 31
                sh = (w2 >> 22) & 3
                imm12 = (w2 >> 10) & 0xfff
                if rd == rn and sh == 0:
                    s = cstr(d, page + imm12)
                    if s and len(s) < 40 and all(32 < ord(ch) < 127 for ch in s):
                        return s, i
                break
    return None


LIGHT_KEYS = (
    'threshold', 'backthreshold', 'crossdistmin', 'crossdistmax',
    'NeedDiffTime', 'DiffTime', 'SwitchLongLink', 'StopNum',
    'OptimiseVoicePlayDist', 'StatusDiffTime', 'switch', 'b_t', 'a_t',
)


def group_light_blocks(rows):
    """把候选块按「键名属于 light_detail 键集 + keyref 在块前 16 字节 + 字段 +4 递增」
    聚成组，返回所有满足条件的组（按块地址排序）。不依赖字段偏移窗口。"""
    cand = []
    for row in sorted(rows, key=lambda r: r[0]):
        b, field, k = row[0], row[1], row[2]
        pat = row[3] if len(row) > 3 else False
        if not k:
            continue
        name, kref = k
        if name not in LIGHT_KEYS:
            continue
        if kref != b - 16:          # adrp+add 紧贴在守卫前 4 条指令
            continue
        cand.append((b, field, k, pat))

    groups, cur = [], []
    for it in cand:
        if cur and not (it[1] == cur[-1][1] + 4 and it[0] > cur[-1][0]):
            if len(cur) >= 3:
                groups.append(cur)
            cur = []
        cur.append(it)
    if len(cur) >= 3:
        groups.append(cur)

    # 只保留同时含 threshold 和 crossdistmax 的组（红绿灯组）
    out = []
    for g in groups:
        names = {it[2][0] for it in g}
        if 'threshold' in names and 'crossdistmax' in names:
            out.append(g)
    return out


def main():
    path = sys.argv[1]
    imm = None
    if '--patch' in sys.argv:
        imm = int(sys.argv[sys.argv.index('--patch') + 1])

    d = bytearray(open(path, 'rb').read())
    loads = parse_elf(d)
    lo = hi = 0
    for va, ve, o, oe in loads:
        if va == o:
            lo, hi = o, oe
            break
    print('file :', path)
    print('text : fileoff 0x%x .. 0x%x  (vaddr==fileoff, patch 偏移直接用 vaddr)' % (lo, hi))

    blocks = []
    i = lo
    while True:
        j = d.find(SIG, i, hi)
        if j < 0:
            break
        blocks.append(j)
        i = j + 4

    # 已打补丁的块： movz | nop nop nop | movz | ldr x9,[x28] | str
    patched_blocks = []
    i = lo
    while True:
        j = d.find(SIG_PATCHED_MID, i, hi)
        if j < 0:
            break
        g = j - 4                                   # 块起点(第一条 movz)
        if g >= lo and (struct.unpack_from('<I', d, g)[0] & 0xffe0001f) == 0x52800008 \
           and (struct.unpack_from('<I', d, g + 16)[0] & 0xffe0001f) == 0x52800008 \
           and d[g + 20:g + 24] == SIG_PATCHED_TAIL:
            patched_blocks.append(g)
        i = j + 4

    # 统一收集：原始态块 + 补丁态块，都带 (addr, field, key, patched)
    rows = []
    for b in blocks:
        field = ((struct.unpack_from('<I', d, b + STR_IN_BLOCK)[0] >> 10) & 0xfff) * 4
        k = nearest_key_before(d, lo, b)
        rows.append((b, field, k, False))
    for g in patched_blocks:
        field = ((struct.unpack_from('<I', d, g + STR_IN_BLOCK)[0] >> 10) & 0xfff) * 4
        k = nearest_key_before(d, lo, g)      # adrp+add 引用没被改，键名仍可读出
        rows.append((g, field, k, True))
    rows.sort(key=lambda r: r[0])
    blocks = [r[0] for r in rows]

    # ── 红绿灯组识别（不写死字段偏移窗口）───────────────────────────────
    # 关键不变量：每个键的 adrp+add 字符串引用固定在块起点前 16 字节（4 条指令）。
    # 组内特征：键名属于 light_detail 的键集，且字段偏移严格 +4 递增。
    # 20.15.2 是 +0x10c..，20.16.3 是 +0x104..，21.13.2 是 +0x15c.. —— 窗口不写死。
    print('\n找到 %d 个候选块；按键序列 + 字段 +4 递增分组：' % len(rows))
    print('%-12s %-8s %-22s %-10s %s' % ('block@', 'field', 'key', 'state', 'keyref@'))

    light = []                     # (block, field, key, patched)
    for grp in group_light_blocks(rows):
        for b, field, k, pat in grp:
            light.append((b, field, k, pat))
            print('%-12s +%-7s %-22s %-10s %s'
                  % (hex(b), hex(field), k[0] if k else '?',
                     '已补丁' if pat else '原始', hex(k[1]) if k else '-'))
        print('  ↑ 红绿灯组: field +%#x .. +%#x（%d 个键）'
              % (grp[0][1], grp[-1][1], len(grp)))

    if patched_blocks:
        print('\n已打过补丁的块（仍是红绿灯区、值为 movz 常量）：')
        for g in patched_blocks:
            field = ((struct.unpack_from('<I', d, g + 24)[0] >> 10) & 0xfff) * 4
            v = struct.unpack_from('<I', d, g + 16)[0]
            imm16 = (v >> 5) & 0xffff
            print('  block=%-12s field=+%-7s movz w8,#%d' % (hex(g), hex(field), imm16))

    # 体检：lib/ 里不要有非 .so 文件（会被 apktool 打进 apk）
    libdir = os.path.dirname(path)
    if os.path.basename(libdir) and os.path.isdir(libdir):
        junk = [f for f in os.listdir(libdir)
                if os.path.isfile(os.path.join(libdir, f)) and not f.endswith('.so')]
        if junk:
            print('\n[!] %s 里有非 .so 文件，会被 apktool 打进 apk（体积暴涨）:' % libdir)
            for f in junk:
                print('    %s  (%d B)' % (f, os.path.getsize(os.path.join(libdir, f))))
            print('    建议移到工程外，例如: mv %s ../' % os.path.join(libdir, junk[0]))

    if imm is None:
        print('\n(只定位。加 --patch <米数> 直接改 so)')
        return

    word = (0x52800000 | ((imm & 0xffff) << 5) | 8).to_bytes(4, 'little')
    print('\n=== patch IMM=%d  movz w8,#%#x = %s ===' % (imm, imm & 0xffff, word.hex()))

    # 收集目标：同时考虑「未打补丁的原始块」和「已打补丁的块」
    # 字段偏移随版本变（20.15.2: 0x10c/0x118，20.16.3: 0x104/0x110），
    # 所以不写死偏移，改用「红绿灯组里 field 最小=threshold、最大=crossdistmax」的关系。
    wanted = {'threshold', 'crossdistmax'}
    targets = {}                                   # name -> (block, field, patched)
    for b, field, k, pat in light:
        if k and k[0] in wanted:
            targets.setdefault(k[0], (b, field, pat))

    if targets:
        print('  命中目标: %s' % ', '.join(
            '%s(block=%s field=+%#x %s)' % (n, hex(t[0]), t[1],
                                            '已补丁' if t[2] else '原始')
            for n, t in sorted(targets.items())))

    if not targets:
        print('!! 未匹配到 threshold/crossdistmax，请人工核对上表')
        return

    changed = 0
    for name, (b, field, pat) in sorted(targets.items()):
        k = (name, b)
        cur = struct.unpack_from('<I', d, b)[0]
        if (cur & 0xffe0001f) == 0x52800008:
            # 已是补丁态：直接改立即数（守卫那条 + 取值那条）
            old_imm = (cur >> 5) & 0xffff
            if old_imm == (imm & 0xffff):
                print('  %-14s 已是 %d，无需修改' % (k[0], old_imm))
                continue
            d[b + 0:b + 4]   = word
            d[b + 16:b + 20] = word
            print('  %-14s field=+%-6s block=%s  %d -> %d  OK'
                  % (k[0], hex(field), hex(b), old_imm, imm & 0xffff))
            changed += 1
            continue
        if d[b:b + 4] != bytes.fromhex('e00000b4'):
            print('!! %s 守卫块签名不符，跳过' % k[0]); continue
        d[b + 0:b + 4]   = word   # cbz        -> movz w8,#IMM
        d[b + 4:b + 8]   = NOP    # ldr  [#0x20]
        d[b + 8:b + 12]  = NOP    # cmp  #0x3
        d[b + 12:b + 16] = NOP    # b.ne
        d[b + 16:b + 20] = word   # ldr  [#0x30] -> movz w8,#IMM
        print('  %-14s field=+%-6s block=%s  首次打补丁 OK' % (k[0], hex(field), hex(b)))
        changed += 1

    if changed == 0:
        print('无需写入。')
        return
    open(path, 'wb').write(bytes(d))
    print('已写回', path)


if __name__ == '__main__':
    main()
