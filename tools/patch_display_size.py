#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_display_size.py — 「地图显示大小调整」加两档（最小 0.6f / 更小 0.8f）的**机械部分**

用法:
    python3 tools/patch_display_size.py _work/apktool_full          # 打补丁（幂等）
    python3 tools/patch_display_size.py _work/apktool_full --check  # 只检查

自动完成（纯资源/字段，与版本无关）:
    1) res/values/strings.xml   加 2 个字符串
    2) res/values/ids.xml       加 2 个 id
    3) res/values/public.xml    给上面 4 个资源分配固定 ID（自动避开已占用）
    4) res/layout/ba_layout_sub_page_display_map_size_item.xml  RadioGroup 插 2 个 RadioButton
    5) 所有 R$id.smali 同步补 2 个字段
    6) BASettingDisplayComponent.smali 插 2 个字段声明 y0 / z0

**不自动完成**（需人工，见 docs/README.md §3.2）:
    BASettingDisplayComponent.smali 里 j4() / x4() / U4() 三个方法体。
    参考 _work/refs/BASettingDisplayComponent.smali.patched 直接对照改写。
"""
import os, re, sys

ID_SMALLEST, ID_SMALLER = '0x7f0b0ecb', '0x7f0b0ecc'
TXT_SMALLEST, TXT_SMALLER = '最小', '更小'
CMP = 'smali_classes20/com/baidumap/settings/ui/component/display/BASettingDisplayComponent.smali'


def rd(p):
    with open(p, encoding='utf-8') as f:
        return f.read()


def wr(p, s):
    with open(p, 'w', encoding='utf-8') as f:
        f.write(s)


def next_ids(xml, type_name, count):
    used = {int(m.group(1), 16)
            for m in re.finditer(r'<public type="%s" name="[^"]+" id="(0x[0-9a-f]+)"' % type_name, xml)}
    nxt = max(used) + 1
    out = []
    for _ in range(count):
        while nxt in used:
            nxt += 1
        out.append(nxt)
        used.add(nxt)
        nxt += 1
    return out


def main():
    root = sys.argv[1].rstrip('/')
    dry = '--check' in sys.argv
    done = []

    p = root + '/res/values/strings.xml'
    s = rd(p)
    if 'ba_setting_navi_adjust_smaller' not in s:
        m = re.search(r'^([ \t]*)<string name="ba_setting_navi_adjust_small">[^<]*</string>[ \t]*$', s, re.M)
        assert m, 'strings.xml: 找不到 ba_setting_navi_adjust_small 锚点'
        add = ('\n%s<string name="ba_setting_navi_adjust_smaller">%s</string>'
               '\n%s<string name="ba_setting_navi_adjust_smallest">%s</string>'
               % (m.group(1), TXT_SMALLER, m.group(1), TXT_SMALLEST))
        s = s[:m.end()] + add + s[m.end():]
        if not dry:
            wr(p, s)
        done.append('strings.xml')
    else:
        done.append('strings.xml (已存在)')

    p = root + '/res/values/ids.xml'
    s = rd(p)
    if 'map_size_smallest' not in s:
        m = re.search(r'^([ \t]*)<id name="map_size_too_big" />[ \t]*$', s, re.M)
        assert m, 'ids.xml: 找不到 map_size_too_big 锚点'
        add = ('\n%s<id name="map_size_smallest" />\n%s<id name="map_size_smaller" />'
               % (m.group(1), m.group(1)))
        s = s[:m.end()] + add + s[m.end():]
        if not dry:
            wr(p, s)
        done.append('ids.xml')
    else:
        done.append('ids.xml (已存在)')

    p = root + '/res/values/public.xml'
    s = rd(p)
    if 'map_size_smallest' not in s:
        i_smallest, i_smaller = next_ids(s, 'id', 2)
        s_smaller, s_smallest = next_ids(s, 'string', 2)
        m = re.search(r'^([ \t]*)<public type="id" name="map_size_too_big"[^/]*/>[ \t]*$', s, re.M)
        assert m, 'public.xml: 找不到 map_size_too_big 锚点'
        add = ('\n%s<public type="id" name="map_size_smallest" id="%s" />'
               '\n%s<public type="id" name="map_size_smaller" id="%s" />'
               % (m.group(1), hex(i_smallest), m.group(1), hex(i_smaller)))
        s = s[:m.end()] + add + s[m.end():]
        m2 = re.search(r'^([ \t]*)<public type="string" name="ba_setting_navi_adjust_small"[^/]*/>[ \t]*$', s, re.M)
        assert m2, 'public.xml: 找不到 ba_setting_navi_adjust_small 锚点'
        add2 = ('\n%s<public type="string" name="ba_setting_navi_adjust_smaller" id="%s" />'
                '\n%s<public type="string" name="ba_setting_navi_adjust_smallest" id="%s" />'
                % (m2.group(1), hex(s_smaller), m2.group(1), hex(s_smallest)))
        s = s[:m2.end()] + add2 + s[m2.end():]
        if not dry:
            wr(p, s)
        done.append('public.xml (id %s/%s, string %s/%s)'
                    % (hex(i_smallest), hex(i_smaller), hex(s_smaller), hex(s_smallest)))
    else:
        done.append('public.xml (已存在)')

    p = root + '/res/layout/ba_layout_sub_page_display_map_size_item.xml'
    s = rd(p)
    if 'map_size_smallest' not in s:
        m = re.search(r'^([ \t]*)<RadioButton[^>]*android:id="@id/map_size_small"[^>]*/>[ \t]*$', s, re.M)
        assert m, 'layout: 找不到 map_size_small 锚点'
        ind = m.group(1)
        tpl = ('%s<RadioButton android:textSize="@dimen/ba_text_body_3" android:gravity="center" '
               'android:id="@id/%s" android:layout_width="0.0dp" android:layout_height="match_parent" '
               'android:button="@null" android:text="@string/%s" android:layout_weight="1.0" '
               'style="@style/BASettingRadioStyle" />\n')
        add = (tpl % (ind, 'map_size_smallest', 'ba_setting_navi_adjust_smallest')
               + tpl % (ind, 'map_size_smaller', 'ba_setting_navi_adjust_smaller'))
        s = s[:m.start()] + add + s[m.start():]
        if not dry:
            wr(p, s)
        done.append('layout')
    else:
        done.append('layout (已存在)')

    n = 0
    for dirpath, _, files in os.walk(root):
        if 'R$id.smali' not in files:
            continue
        fp = os.path.join(dirpath, 'R$id.smali')
        t = rd(fp)
        if 'map_size_too_big:I' not in t or 'map_size_smallest:I' in t:
            continue
        m = re.search(r'^([ \t]*)\.field public static (?:final )?map_size_too_big:I = 0x[0-9a-f]+[ \t]*$', t, re.M)
        if not m:
            continue
        add = ('\n\n%s.field public static map_size_smallest:I = %s'
               '\n\n%s.field public static map_size_smaller:I = %s'
               % (m.group(1), ID_SMALLEST, m.group(1), ID_SMALLER))
        t = t[:m.end()] + add + t[m.end():]
        if not dry:
            wr(fp, t)
        n += 1
    done.append('R$id.smali × %d' % n if n else 'R$id.smali (已存在)')

    fp = os.path.join(root, CMP)
    t = rd(fp)
    if 'y0:Landroid/widget/RadioButton' not in t:
        m = re.search(r'^\.field private y:Lcom/baidumap/settings/ui/view/BADrawableTextView;', t, re.M)
        assert m, 'BASettingDisplayComponent: 找不到 .field private y: 锚点'
        add = ('.field private y0:Landroid/widget/RadioButton;\n'
               '    .annotation build Lorg/jetbrains/annotations/Nullable;\n'
               '    .end annotation\n'
               '.end field\n\n'
               '.field private z0:Landroid/widget/RadioButton;\n'
               '    .annotation build Lorg/jetbrains/annotations/Nullable;\n'
               '    .end annotation\n'
               '.end field\n\n')
        t = t[:m.start()] + add + t[m.start():]
        if not dry:
            wr(fp, t)
        done.append('BASettingDisplayComponent 字段 y0/z0')
    else:
        done.append('BASettingDisplayComponent 字段 (已存在)')

    print('[%s]' % ('DRY-RUN' if dry else 'APPLIED'))
    for d in done:
        print('  -', d)
    print('')
    print('!! 仍需人工: BASettingDisplayComponent.smali 的 j4() / x4() / U4() 方法体')
    print('   对照 docs/README.md §3.2，或直接 diff _work/refs/BASettingDisplayComponent.smali.patched')


if __name__ == '__main__':
    main()
