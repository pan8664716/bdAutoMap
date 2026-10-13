#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_auth_bypass.py — 绕过 21.13.2 新增的「鉴权文件（authConfig.dat）校验」

背景
----
21.13.2 起 App 启动时会走 AuthController 的离线鉴权：

    EngineController$b.handleMessage  (msg.what == 0x11)
        ├─ AuthController.verifyAuthentication()   → 校验 authConfig.dat 里的签名/包名
        ├─ AuthController.loadAuthConfigSuccess()  → 文件是否解析成功
        └─ 二者任一为 false
              → Toast「鉴权解析失败，请检查鉴权文件的正确性」
              → 3.75s 后 Process.killProcess(myPid())   ← 表现为「自动 crash」

authConfig.dat 的内容与**原始包的签名**绑定，重签后 native 层（libBaiduMapAutoEngine.so
里的 Java_..._JNIAuthentication_loadFile / _authenticate）必然校验失败。
改文件无效（签名对不上），因此从 Java 层把鉴权判定短路掉。

补丁点（全部按「类名 + 方法签名」内容锚定，不写死 smali_classes 编号）
--------------------------------------------------------------------
1. AuthController.verifyAuthentication()Z   → 恒 return true
2. AuthController.loadAuthConfigSuccess()Z  → 恒 return true
3. AuthController.authFailed(String,Z)V     → 直接 return（不弹窗、不 killSelf）
4. AuthStrategyV1.j()Z                      → 恒 return true（native authenticate 结果）
5. EngineController$b.c()/d()V              → 直接 return（兜底：去掉 killProcess）
6. AuthStrategyV0 走 LBS 分支时同理

用法:
    python3 tools/patch_auth_bypass.py _work/apktool_full_21132          # 打补丁（幂等）
    python3 tools/patch_auth_bypass.py _work/apktool_full_21132 --check  # 只检查
"""
import os, re, sys

TAG = 'AuthBypass'


def find_class(root, class_desc):
    """按 .class 声明里的类描述符定位 smali 文件（跨 smali_classesN 编号）"""
    for dp, _, fs in os.walk(root):
        for f in fs:
            if not f.endswith('.smali'):
                continue
            p = os.path.join(dp, f)
            with open(p, encoding='utf-8', errors='replace') as fh:
                head = fh.read(4096)
            if ('.class' in head) and (class_desc + ';' in head.split('\n#')[0]):
                # 精确：.class 那一行必须包含该描述符
                for line in head.splitlines():
                    if line.startswith('.class'):
                        if line.strip().endswith(class_desc + ';'):
                            return p
                        break
    return None


def method_span(text, signature):
    """返回方法签名对应的 (start, end) 字符区间（end 指向 .end method 之后）"""
    m = re.search(r'(?m)^\.method[^\n]*' + re.escape(signature) + r'\s*$', text)
    if not m:
        return None
    s = m.start()
    e = text.find('\n.end method', s)
    if e < 0:
        return None
    return s, e + len('\n.end method')


def replace_method(path, signature, new_body, dry=False):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    sp = method_span(text, signature)
    if not sp:
        return 'NOTFOUND'
    s, e = sp
    old = text[s:e]
    if new_body.strip() in old:
        return 'ALREADY'
    text = text[:s] + new_body.strip('\n') + text[e:]
    if not dry:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text)
    return 'PATCHED'


RET_TRUE = '''.method public {sig}
    .locals 1

    const/4 v0, 0x1

    return v0
.end method'''

RET_VOID = '''.method public {static}{sig}
    .locals 0

    return-void
.end method'''


def main():
    root = sys.argv[1]
    dry = '--check' in sys.argv
    print('[%s] %s  %s' % (TAG, root, '(DRY-RUN)' if dry else ''))

    plan = [
        # (类描述符, 方法签名, 新方法体模板, 是否 static)
        ('Lcom/baidu/mapautosdk/component/authentication/AuthController',
         'verifyAuthentication()Z', RET_TRUE, False),
        ('Lcom/baidu/mapautosdk/component/authentication/AuthController',
         'loadAuthConfigSuccess()Z', RET_TRUE, False),
        ('Lcom/baidu/mapautosdk/component/authentication/AuthController',
         'authFailed(Ljava/lang/String;Z)V', RET_VOID, True),
        ('Lcom/baidu/mapautosdk/component/authentication/f',
         'j()Z', RET_TRUE, False),
        ('Lcom/baidu/mapautosdk/d/d$b', 'c()V', RET_VOID, True),
        ('Lcom/baidu/mapautosdk/d/d$b', 'd()V', RET_VOID, True),
    ]

    # 可选：V0 策略（LBS 分支）里的 native 鉴权结果
    v0 = find_class(root, 'Lcom/baidu/mapautosdk/component/authentication/e')
    if v0:
        plan.append(('Lcom/baidu/mapautosdk/component/authentication/e',
                     'j()Z', RET_TRUE, False))

    changed = 0
    for cls, sig, tmpl, is_static in plan:
        path = find_class(root, cls)
        if not path:
            print('  %-46s %s' % (cls.split('/')[-1] + '.' + sig, 'CLASS-NOT-FOUND'))
            continue
        body = tmpl.format(sig=sig, static='static ' if is_static else '')
        r = replace_method(path, sig, body, dry=dry)
        if r == 'PATCHED':
            changed += 1
        print('  %-46s %-16s %s' % (cls.split('/')[-1] + '.' + sig, r,
                                    os.path.relpath(path, root)))

    print('[%s] %s，改动 %d 处' % (TAG, 'DRY-RUN 完成' if dry else '完成', changed))


if __name__ == '__main__':
    main()
