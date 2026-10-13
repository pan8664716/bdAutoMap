#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_display_size_auto.py — 「地图显示大小调整」加两档（最小 0.6f / 更小 0.8f）

全自动版：连 BASettingDisplayComponent.smali 的 3 个方法体一起改，无需手工。

用法:
    python3 tools/patch_display_size_auto.py _work/apktool_full           # 打补丁（幂等）
    python3 tools/patch_display_size_auto.py _work/apktool_full --check   # 只检查

设计原则：**全部按内容锚点定位，不写死行号/字段名/方法名/资源 ID**，换版本直接可用。

自动完成:
    1) res/values/strings.xml   加 2 个字符串
    2) res/values/ids.xml       加 2 个 id
    3) res/values/public.xml    给上面 4 个资源分配固定 ID（自动避开已占用）
    4) res/layout/ba_layout_sub_page_display_map_size_item.xml  RadioGroup 插 2 个 RadioButton
    5) 所有 R$id.smali 同步补 2 个字段
    6) BASettingDisplayComponent.smali:
         - 字段声明（自动挑两个未占用的字段名）
         - 点击处理（RadioGroup.OnCheckedChangeListener 静态方法）重写为 6 档
         - findViewById 处插入两个 RadioButton 绑定
         - 回显方法插入 0.6/0.8 两个分支
"""
import os, re, sys

TXT_SMALLEST, TXT_SMALLER = '最小', '更小'
F_SMALLEST_TMPL = '0x3f19999a'   # 0.6f
F_SMALLER_TMPL  = '0x3f4ccccd'   # 0.8f

CMP_REL = 'smali_classes20/com/baidumap/settings/ui/component/display/BASettingDisplayComponent.smali'
LAYOUT_REL = 'res/layout/ba_layout_sub_page_display_map_size_item.xml'
CLS = 'Lcom/baidumap/settings/ui/component/display/BASettingDisplayComponent;'


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


def find_component(root):
    """按内容定位组件 smali（不依赖 smali_classes 编号）"""
    for dp, _, fs in os.walk(root):
        if 'BASettingDisplayComponent.smali' in fs:
            return os.path.join(dp, 'BASettingDisplayComponent.smali')
    return None


def method_span(text, must_have_all, must_have_any=None):
    """返回第一个同时包含 must_have_all 里所有子串的方法的 (start, end) 字符区间"""
    for m in re.finditer(r'(?m)^\.method[^\n]*\n', text):
        s = m.start()
        e = text.find('\n.end method', s)
        if e < 0:
            continue
        body = text[s:e]
        if all(k in body for k in must_have_all) and (not must_have_any or any(k in body for k in must_have_any)):
            return s, e
    return None


def free_field_names(text, n):
    """挑 n 个该类里未占用的字段名"""
    used = set(re.findall(r'(?m)^\.field[^\n]*?([A-Za-z_$][A-Za-z0-9_$]*)\s*:', text))
    cands = ['y1', 'z1', 'x1', 'w1', 'v1', 'u1', 't1', 's1', 'r1', 'q1', 'p1',
             'A0', 'B0', 'C0', 'D0', 'E0', 'F0', 'G0', 'H0', 'I0', 'J0', 'K0', 'L0']
    out = [c for c in cands if c not in used]
    assert len(out) >= n, '找不到足够的空闲字段名'
    return out[:n]


def main():
    root = sys.argv[1].rstrip('/')
    dry = '--check' in sys.argv
    log = []

    # ---------- 1. strings.xml ----------
    p = root + '/res/values/strings.xml'
    s = rd(p)
    if 'ba_setting_navi_adjust_smaller' not in s:
        m = re.search(r'(?m)^([ \t]*)<string name="ba_setting_navi_adjust_small">[^<]*</string>[ \t]*$', s)
        assert m, 'strings.xml: 找不到 ba_setting_navi_adjust_small 锚点'
        add = ('\n%s<string name="ba_setting_navi_adjust_smaller">%s</string>'
               '\n%s<string name="ba_setting_navi_adjust_smallest">%s</string>'
               % (m.group(1), TXT_SMALLER, m.group(1), TXT_SMALLEST))
        s = s[:m.end()] + add + s[m.end():]
        if not dry:
            wr(p, s)
        log.append('strings.xml')
    else:
        log.append('strings.xml (已存在)')

    # ---------- 2. ids.xml ----------
    p = root + '/res/values/ids.xml'
    s = rd(p)
    if 'map_size_smallest' not in s:
        m = re.search(r'(?m)^([ \t]*)<id name="map_size_too_big" />[ \t]*$', s)
        assert m, 'ids.xml: 找不到 map_size_too_big 锚点'
        add = ('\n%s<id name="map_size_smallest" />\n%s<id name="map_size_smaller" />'
               % (m.group(1), m.group(1)))
        s = s[:m.end()] + add + s[m.end():]
        if not dry:
            wr(p, s)
        log.append('ids.xml')
    else:
        log.append('ids.xml (已存在)')

    # ---------- 3. public.xml ----------
    p = root + '/res/values/public.xml'
    s = rd(p)
    if 'map_size_smallest' not in s:
        i_smallest, i_smaller = next_ids(s, 'id', 2)
        s_smaller, s_smallest = next_ids(s, 'string', 2)
        m = re.search(r'(?m)^([ \t]*)<public type="id" name="map_size_too_big"[^/]*/>[ \t]*$', s)
        assert m, 'public.xml: 找不到 map_size_too_big 锚点'
        add = ('\n%s<public type="id" name="map_size_smallest" id="%s" />'
               '\n%s<public type="id" name="map_size_smaller" id="%s" />'
               % (m.group(1), hex(i_smallest), m.group(1), hex(i_smaller)))
        s = s[:m.end()] + add + s[m.end():]
        m2 = re.search(r'(?m)^([ \t]*)<public type="string" name="ba_setting_navi_adjust_small"[^/]*/>[ \t]*$', s)
        assert m2, 'public.xml: 找不到 ba_setting_navi_adjust_small 锚点'
        add2 = ('\n%s<public type="string" name="ba_setting_navi_adjust_smaller" id="%s" />'
                '\n%s<public type="string" name="ba_setting_navi_adjust_smallest" id="%s" />'
                % (m2.group(1), hex(s_smaller), m2.group(1), hex(s_smallest)))
        s = s[:m2.end()] + add2 + s[m2.end():]
        if not dry:
            wr(p, s)
        ID_SMALLEST, ID_SMALLER = hex(i_smallest), hex(i_smaller)
        log.append('public.xml (id %s/%s, string %s/%s)'
                   % (hex(i_smallest), hex(i_smaller), hex(s_smaller), hex(s_smallest)))
    else:
        ID_SMALLEST, ID_SMALLER = None, None
        log.append('public.xml (已存在)')

    # ---------- 4. layout ----------
    p = root + '/' + LAYOUT_REL
    s = rd(p)
    if 'map_size_smallest' not in s:
        m = re.search(r'(?m)^([ \t]*)<RadioButton[^>]*android:id="@id/map_size_small"[^>]*/>[ \t]*$', s)
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
        log.append('layout')
    else:
        log.append('layout (已存在)')

    # ---------- 5. R$id.smali ----------
    if ID_SMALLEST is None:  # 已打过，从工程里读回
        for dp, _, fs in os.walk(root):
            if 'R$id.smali' in fs:
                t = rd(os.path.join(dp, 'R$id.smali'))
                mm = re.search(r'map_size_smallest:I = (0x[0-9a-f]+)', t)
                mm2 = re.search(r'map_size_smaller:I = (0x[0-9a-f]+)', t)
                if mm and mm2:
                    ID_SMALLEST, ID_SMALLER = mm.group(1), mm2.group(1)
                    break
        assert ID_SMALLEST, 'R$id.smali 里找不到 map_size_smallest，工程状态异常'

    n = 0
    for dirpath, _, files in os.walk(root):
        if 'R$id.smali' not in files:
            continue
        fp = os.path.join(dirpath, 'R$id.smali')
        t = rd(fp)
        if 'map_size_too_big:I' not in t or 'map_size_smallest:I' in t:
            continue
        m = re.search(r'(?m)^([ \t]*)\.field public static (?:final )?map_size_too_big:I = 0x[0-9a-f]+[ \t]*$', t)
        if not m:
            continue
        add = ('\n\n%s.field public static map_size_smallest:I = %s'
               '\n\n%s.field public static map_size_smaller:I = %s'
               % (m.group(1), ID_SMALLEST, m.group(1), ID_SMALLER))
        t = t[:m.end()] + add + t[m.end():]
        if not dry:
            wr(fp, t)
        n += 1
    log.append('R$id.smali × %d' % n if n else 'R$id.smali (已存在)')

    # ---------- 6. BASettingDisplayComponent.smali ----------
    fp = find_component(root)
    assert fp, '找不到 BASettingDisplayComponent.smali'
    t = rd(fp)
    changed = []

    # 6a. 字段声明
    F0 = F1 = None
    m = re.search(r'(?m)^\.field private (\w+):Landroid/widget/RadioButton;\n    \.annotation build Lorg/jetbrains/annotations/Nullable;\n    \.end annotation\n\.end field\n(?=\n\.field private (\w+):Landroid/widget/RadioButton;)', t)
    if 'map_size_smallest' not in t and '.field private y1:Landroid/widget/RadioButton;' not in t:
        # 在第一个 RadioButton 字段前插入
        m0 = re.search(r'(?m)^\.field private \w+:Landroid/widget/RadioButton;', t)
        assert m0, 'BASettingDisplayComponent: 找不到 RadioButton 字段锚点'
        F0, F1 = free_field_names(t, 2)
        add = ('.field private %s:Landroid/widget/RadioButton;\n'
               '    .annotation build Lorg/jetbrains/annotations/Nullable;\n'
               '    .end annotation\n'
               '.end field\n\n'
               '.field private %s:Landroid/widget/RadioButton;\n'
               '    .annotation build Lorg/jetbrains/annotations/Nullable;\n'
               '    .end annotation\n'
               '.end field\n\n' % (F0, F1))
        t = t[:m0.start()] + add + t[m0.start():]
        changed.append('字段 %s/%s' % (F0, F1))
    else:
        # 已打过：把新字段名找回来
        mm = re.search(r'->(\w+):Landroid/widget/RadioButton;', t)
        used = set(re.findall(r'(?m)^\.field[^\n]*?([A-Za-z_$][A-Za-z0-9_$]*)\s*:', t))
        for cand in ['y1', 'z1']:
            pass
        # 从回显方法里反推
        sp = method_span(t, ['"auto_map_overlay_extra_scale"', 'getFloat'])
        if sp:
            body = t[sp[0]:sp[1]]
            flds = re.findall(r'iget-object v\d+, p0, ' + re.escape(CLS) + r'->(\w+):Landroid/widget/RadioButton;', body)
            if len(flds) >= 6:
                F0, F1 = flds[0], flds[1]
        if F0 is None:
            F0, F1 = 'y1', 'z1'
        changed.append('字段 %s/%s (已存在)' % (F0, F1))

    # 6b. 点击处理重写
    sp = method_span(t, [CLS + 'Landroid/widget/RadioGroup;I)V', 'map_size_small:I'])
    assert sp, '找不到 RadioGroup 点击处理方法'
    head = t[sp[0]:t.find('\n', sp[0])]
    body = t[sp[0]:sp[1]]
    if 'map_size_smallest:I' not in body:
        mset = re.search(r'invoke-direct \{p0, p1\}, ' + re.escape(CLS) + r'->(\w+)\(F\)V', body)
        assert mset, '找不到缩放 setter 方法'
        SETTER = mset.group(1)
        mname = re.search(r'^\.method\s+(?:[\w\s]*?)(\w+)\(', head).group(1)
        new = (
            '.method %s\n'
            '    .locals 1\n'
            '\n'
            '    const-string p1, "this$0"\n'
            '\n'
            '    invoke-static {p0, p1}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V\n'
            '\n'
            '    sget p1, Lcom/baidu/autonavi/business/settings/R$id;->map_size_smallest:I\n'
            '\n'
            '    if-ne p2, p1, :cond_0\n'
            '\n'
            '    const p1, %s    # 0.6f\n'
            '\n'
            '    invoke-direct {p0, p1}, %s->%s(F)V\n'
            '\n'
            '    return-void\n'
            '\n'
            '    :cond_0\n'
            '    sget p1, Lcom/baidu/autonavi/business/settings/R$id;->map_size_smaller:I\n'
            '\n'
            '    if-ne p2, p1, :cond_1\n'
            '\n'
            '    const p1, %s    # 0.8f\n'
            '\n'
            '    invoke-direct {p0, p1}, %s->%s(F)V\n'
            '\n'
            '    return-void\n'
            '\n'
            '    :cond_1\n'
            '    sget p1, Lcom/baidu/autonavi/business/settings/R$id;->map_size_small:I\n'
            '\n'
            '    if-ne p2, p1, :cond_2\n'
            '\n'
            '    const/high16 p1, 0x3f800000    # 1.0f\n'
            '\n'
            '    invoke-direct {p0, p1}, %s->%s(F)V\n'
            '\n'
            '    return-void\n'
            '\n'
            '    :cond_2\n'
            '    sget p1, Lcom/baidu/autonavi/business/settings/R$id;->map_size_standard:I\n'
            '\n'
            '    if-ne p2, p1, :cond_3\n'
            '\n'
            '    const p1, 0x3f8ccccd    # 1.1f\n'
            '\n'
            '    invoke-direct {p0, p1}, %s->%s(F)V\n'
            '\n'
            '    return-void\n'
            '\n'
            '    :cond_3\n'
            '    sget p1, Lcom/baidu/autonavi/business/settings/R$id;->map_size_big:I\n'
            '\n'
            '    if-ne p2, p1, :cond_4\n'
            '\n'
            '    const p1, 0x3f99999a    # 1.2f\n'
            '\n'
            '    invoke-direct {p0, p1}, %s->%s(F)V\n'
            '\n'
            '    return-void\n'
            '\n'
            '    :cond_4\n'
            '    sget p1, Lcom/baidu/autonavi/business/settings/R$id;->map_size_too_big:I\n'
            '\n'
            '    if-ne p2, p1, :cond_5\n'
            '\n'
            '    const p1, 0x3fa66666    # 1.3f\n'
            '\n'
            '    invoke-direct {p0, p1}, %s->%s(F)V\n'
            '\n'
            '    :cond_5\n'
            '    return-void\n'
            % (head.replace('.method ', '', 1), F_SMALLEST_TMPL, CLS, SETTER,
               F_SMALLER_TMPL, CLS, SETTER, CLS, SETTER, CLS, SETTER, CLS, SETTER, CLS, SETTER)
        )
        t = t[:sp[0]] + new + t[sp[1]:]
        changed.append('点击处理 %s() 重写为 6 档 (setter=%s)' % (mname, SETTER))

    # 6c. findViewById 绑定
    sp = method_span(t, ['map_size_small:I', 'findViewById', 'RadioButton'])
    assert sp, '找不到 findViewById 方法'
    body = t[sp[0]:sp[1]]
    if 'map_size_smallest:I' not in body:
        m = re.search(r'(?m)^([ \t]*)sget (v\d+), Lcom/baidu/autonavi/business/settings/R\$id;->map_size_small:I[ \t]*$', body)
        assert m, 'findViewById: 找不到 map_size_small 锚点'
        ind, reg = m.group(1), m.group(2)
        add = ('%ssget %s, Lcom/baidu/autonavi/business/settings/R$id;->map_size_smallest:I\n'
               '\n'
               '%sinvoke-virtual {p1, %s}, Landroid/view/View;->findViewById(I)Landroid/view/View;\n'
               '\n'
               '%smove-result-object %s\n'
               '\n'
               '%scheck-cast %s, Landroid/widget/RadioButton;\n'
               '\n'
               '%siput-object %s, p0, %s->%s:Landroid/widget/RadioButton;\n'
               '\n'
               '%ssget %s, Lcom/baidu/autonavi/business/settings/R$id;->map_size_smaller:I\n'
               '\n'
               '%sinvoke-virtual {p1, %s}, Landroid/view/View;->findViewById(I)Landroid/view/View;\n'
               '\n'
               '%smove-result-object %s\n'
               '\n'
               '%scheck-cast %s, Landroid/widget/RadioButton;\n'
               '\n'
               '%siput-object %s, p0, %s->%s:Landroid/widget/RadioButton;\n'
               '\n'
               % (ind, reg, ind, reg, ind, reg, ind, reg, ind, reg, CLS, F0,
                  ind, reg, ind, reg, ind, reg, ind, reg, ind, reg, CLS, F1))
        pos = sp[0] + m.start()
        t = t[:pos] + add + t[pos:]
        changed.append('findViewById 绑定 → %s/%s' % (F0, F1))

    # 6d. 回显
    sp = method_span(t, ['"auto_map_overlay_extra_scale"', 'getFloat', 'cmpg-float'])
    assert sp, '找不到回显方法'
    body = t[sp[0]:sp[1]]
    if '0x3f19999a' not in body:
        for lbl in (':cond_smallest', ':cond_smaller', ':goto_size_head'):
            assert lbl not in body, '回显方法里已存在标签 %s' % lbl
        m = re.search(r'(?m)^([ \t]*)move-result v0[ \t]*$', body)
        assert m, '回显: 找不到 move-result v0 锚点'
        ind = m.group(1)
        mloc = re.search(r'(?m)^([ \t]*)\.locals (\d+)[ \t]*$', body)
        if mloc and int(mloc.group(2)) < 4:
            body = body.replace(mloc.group(0), '%s.locals 4' % mloc.group(1))
            m = re.search(r'(?m)^([ \t]*)move-result v0[ \t]*$', body)
        add = (
            '\n'
            '%sconst v2, %s    # 0.6f\n'
            '\n'
            '%scmpg-float v2, v0, v2\n'
            '\n'
            '%sif-eqz v2, :cond_smallest\n'
            '\n'
            '%sconst v2, %s    # 0.8f\n'
            '\n'
            '%scmpg-float v2, v0, v2\n'
            '\n'
            '%sif-eqz v2, :cond_smaller\n'
            '\n'
            '%sgoto :goto_size_head\n'
            '\n'
            '%s:cond_smallest\n'
            '%siget-object v2, p0, %s->%s:Landroid/widget/RadioButton;\n'
            '\n'
            '%sif-nez v2, :cond_smallest_set\n'
            '\n'
            '%sreturn-void\n'
            '\n'
            '%s:cond_smallest_set\n'
            '%sconst/4 v3, 0x1\n'
            '\n'
            '%sinvoke-virtual {v2, v3}, Landroid/widget/CompoundButton;->setChecked(Z)V\n'
            '\n'
            '%sreturn-void\n'
            '\n'
            '%s:cond_smaller\n'
            '%siget-object v2, p0, %s->%s:Landroid/widget/RadioButton;\n'
            '\n'
            '%sif-nez v2, :cond_smaller_set\n'
            '\n'
            '%sreturn-void\n'
            '\n'
            '%s:cond_smaller_set\n'
            '%sconst/4 v3, 0x1\n'
            '\n'
            '%sinvoke-virtual {v2, v3}, Landroid/widget/CompoundButton;->setChecked(Z)V\n'
            '\n'
            '%sreturn-void\n'
            '\n'
            '%s:goto_size_head\n'
            % (ind, F_SMALLEST_TMPL, ind, ind, ind, F_SMALLER_TMPL, ind, ind, ind, ind,
               ind, CLS, F0, ind, ind, ind, ind, ind, ind, ind,
               ind, CLS, F1, ind, ind, ind, ind, ind, ind, ind)
        )
        pos = sp[0] + m.end()
        t = t[:pos] + add + t[pos:]
        changed.append('回显插入 0.6/0.8 分支')

    if changed and not dry:
        wr(fp, t)
    log.append('BASettingDisplayComponent.smali: ' + ('; '.join(changed) if changed else '已存在'))

    print('[%s]' % ('DRY-RUN' if dry else 'APPLIED'))
    for d in log:
        print('  -', d)


if __name__ == '__main__':
    main()
