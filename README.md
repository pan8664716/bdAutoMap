# 百度车机地图（com.baidu.naviauto）仪表屏定制 —— 修改与迭代文档

> 目标设备：8.8" 仪表屏，**1920×620**（横屏超宽比），通过仪表投屏把车机地图投上去。
> 已验证版本：**20.15.2 (1462)** 全流程通过；**20.16.3 (1471)** 全流程通过；**21.13.2 (1580) 比亚迪特供版** 全流程通过（新增鉴权绕过，见 §11）。
> 当前交付包：红绿灯显示距离 **2000m**，21.13.2 另有鉴权绕过补丁。
> ABI：arm64-v8a only。
> 所有产物在 `_work/` 下，`tools/` 里是自动化脚本。
> **本仓库只收录 `README.md` + `tools/` + `_work/keys/bmap.keystore`**；反编译产物、原始/构建 apk、so、截图（`_work/`、`shots/`）一律不入库，见 `.gitignore`。

---

## 0. TL;DR —— 换版本后怎么最快搞定

```bash
# 1. 拿到新版 apk，放到 _work/baidumap.apk（替换掉旧的）
# 2. 全量反编译
apktool d -f -o _work/apktool_full _work/baidumap.apk

# 3. 「地图显示大小」两档 —— 全自动，一条命令（见 §3）
python3 tools/patch_display_size_auto.py _work/apktool_full

# 4. 红绿灯显示距离 —— 全自动，一条命令（见 §4）
python3 tools/locate_light.py _work/apktool_full/lib/arm64-v8a/libBaiduMapAutoEngine.so --patch 2000

# 4.5 鉴权绕过（21.13.2 起必须，否则换签后弹「鉴权解析失败」并 3.75s 自杀，见 §11）
python3 tools/patch_auth_bypass.py _work/apktool_full

# 5. 打包 + 重签 + 装机
./tools/build.sh

# 6. 验证
PKG=<包名> python3 tools/verify_light.py 3000
```

所有脚本都是**按内容签名定位**、不写死地址/行号/方法名，换版本后直接能用：
- `locate_light.py` 按 6 条固定指令签名扫 `.text` 定位 so 里的解析点
- `patch_display_size_auto.py` 按资源名/字段名/方法特征（含方法名）定位，自动适配混淆变化
- `verify_light.py` 同样按签名扫描，不依赖地址

**已在两个版本上验证脚本可用**：

| | 20.15.2 (1462) | 20.16.3 (1471) | 21.13.2 (1580) |
|---|---|---|---|
| `locate_light.py` | ✅ | ✅ 自动找到 `0x1dddee8`/`0x1dddf6c` | ✅ 自动找到 `0x263eca4`/`0x263ed28` |
| `patch_display_size_auto.py` | ✅ 产物与手工改逐字节一致 | ✅ 自动识别 `K4()`/`F3()` | ✅ 自动识别 `r4()`/`l3()` |
| `patch_auth_bypass.py` | 不需要 | 不需要 | ✅ 7 处（新增） |
| 构建产物 | ✅ 已装机验证 | ✅ `_work/out/naviauto_20.16.3_light3000_size06-08.apk` | ✅ `_work/out/naviauto_21.13.2_light2000_size06-08_authfix.apk` |

---

## 1. 环境与资产清单

| 项 | 值 |
|---|---|
| 设备 | MuMu 模拟器 `emulator-5554`（`adb shell id` = root；`su` 首次弹窗点允许后永久 root） |
| 复现仪表屏 | `adb shell wm size 620x1920` + 旋转 → 实际 **1920×620**（`wm size` 里显示 `Override size: 620x1920`） |
| 包名 / 版本 | `com.baidu.naviauto` / 20.15.2 (1462) |
| ABI | **仅 arm64-v8a**（apk 里只有 `lib/arm64-v8a/`，改 so 只需改这一份） |
| 原始包备份 | `/sdcard/bmbak/orig_base.apk`、`/sdcard/bmbak/naviauto_data.tgz` |
| 本地原始 apk | `_work/baidumap.apk`（sha1 `6c37d363…` 的 so 就是从它里面出来的） |
| 改包工程 | `_work/apktool_full/`（apktool 3.0.3 全量反编译，含 smali + res） |
| 签名 keystore | `_work/keys/bmap.keystore`，口令 `123456`，别名 `bmap`，dname `CN=baidu,OU=baidu,O=baidu,L=bj,ST=bj,C=cn` |
| 重签工具 | `/tmp/uber-apk-signer.jar`（v1.3.0） |
| 目标 so | `_work/apktool_full/lib/arm64-v8a/libBaiduMapAutoEngine.so`（41,196,768 字节） |
| JDK | 26（Homebrew） |

**签名说明**：换签后 `AuthController.getSignatureSHA1()` 只是把 SHA1 传给 native 鉴权，**实测地图/导航功能正常**。唯一现象是 TTS 资源报
`BaiduTTS: init_file_domain fopen res failed!` —— 属换签后正常现象，不影响使用。

**keystore SHA1 / SHA256**（要写进云控白名单时用得上）：
```
SHA1   : A2:D2:26:E6:2D:94:AF:7C:79:D3:AC:6D:9A:1C:02:2C:08:85:DA:3C
SHA256 : 8A:20:E6:83:5B:29:2E:F9:82:A0:5A:4E:CF:FF:3D:98:58:9B:9A:6E:14:FD:9D:DF:25:22:C3:CF:BB:97:F1:32
```

---

## 2. 构建 / 装机 / 回滚

### 2.1 一条命令（推荐）

```bash
./tools/build.sh --light 3000      # 改红绿灯距离=3000m，然后打包+重签+装机
./tools/build.sh                    # so 已改好，只打包+重签+装机
./tools/build.sh --so-only          # 只打包+重签，不装机

# 产物归档（建议改名，带版本+改动内容，便于回滚到某个版本）
cp _work/signed/patched_raw-signed.apk \
   _work/out/naviauto_<版本>_light<距离>_size06-08.apk
```

> ⚠️ `build.sh` 里的 `adb` 操作是按**当前设备实际包名**来的。
> 20.15.2 是 `com.baidu.naviauto`，20.16.3 是 `com.baidu.BaiduMap`，
> 换版本时记得同步改 `build.sh` 里的 `am force-stop` / 包名。

`build.sh` 内部做的事：

```bash
# 1) 可选 patch so
python3 tools/locate_light.py <so> --patch <米数>

# 2) 重打包
apktool b _work/apktool_full -o _work/patched_raw.apk

# 3) 重签
java -jar /tmp/uber-apk-signer.jar -a _work/patched_raw.apk \
  --ks _work/keys/bmap.keystore --ksAlias bmap --ksPass 123456 --ksKeyPass 123456 \
  -o _work/signed --allowResign --skipZipAlign

# 4) 装机
adb shell "am force-stop com.baidu.naviauto"
adb install -r -d _work/signed/patched_raw-signed.apk
```

### 2.2 手动等价命令

```bash
cd _work
apktool b apktool_full -o patched_raw.apk
java -jar /tmp/uber-apk-signer.jar -a patched_raw.apk --ks keys/bmap.keystore \
  --ksAlias bmap --ksPass 123456 --ksKeyPass 123456 -o signed --allowResign --skipZipAlign
adb install -r -d signed/patched_raw-signed.apk
```

### 2.3 三个必须记住的坑

| 坑 | 说明 |
|---|---|
| `adb install` 必须加 `-d` | 换签后 versionCode 不变，不加 `-d` 会报 downgrade 失败 |
| 首次换签要先卸载原包 | 签名不匹配无法覆盖安装；已做过一次，之后 `-r -d` 即可 |
| 别用 `rm -rf` | 本机沙箱会拒绝；用 `mv` 或逐个删 |
| **so 备份别放 `lib/` 里** | apktool 会把 `lib/**` 下**所有**文件打进 apk。`.so.bak`（46MB 未压缩）会让包体从 152MB 涨到 178MB。备份放 `_work/so_orig.bak`；`build.sh` 会自动体检并移走 |

### 2.4 回滚

```bash
./tools/restore_so.sh                       # 从 _work/so_orig.bak 还原 so
# 或从原始 apk 里重新取（注意别把产物写进 lib/）：
unzip -p _work/baidumap_2016_3.apk lib/arm64-v8a/libBaiduMapAutoEngine.so \
  > _work/apktool_full/lib/arm64-v8a/libBaiduMapAutoEngine.so
```

> 备份位置：`_work/so_orig.bak`（20.16.3 原始，sha1 `db137ead…`）。
> **不要在 `lib/` 目录下留任何非 `.so` 文件。**

校验值（判断 so 处于哪个状态）：

| 状态 | sha1 |
|---|---|
| 原始（未改） | `6c37d3634223b051b618163470041fe0ca7f89e9` |
| 已打红绿灯补丁（3000m） | `2eddecba6ae178ce5549b6a05a1ba08cc7a9b3e0` |

---

## 3. 改动一：「地图显示大小调整」增加两档（0.6f / 0.8f）

**状态：✅ 已验证通过。**

> **自动化程度：全自动**。`tools/patch_display_size_auto.py` 会一次改完
> 资源（strings/ids/public/layout）、20 个 `R$id.smali` 字段、
> 以及 `BASettingDisplayComponent.smali` 的字段声明 + 3 个方法体。

```bash
python3 tools/patch_display_size_auto.py _work/apktool_full          # 打补丁（幂等）
python3 tools/patch_display_size_auto.py _work/apktool_full --check  # 只检查，不写盘
```

脚本行为（已在两个版本、干净工程上验证）：
- **全部按内容定位**：`ba_setting_navi_adjust_small`（strings）、`map_size_too_big`
  （ids/public/R$id）、`map_size_small`（layout）、第一个 `RadioButton` 字段（组件）。
- **方法名不写死**：靠方法体特征找「点击处理」（含 `RadioGroup;I)V` + `map_size_small:I`）、
  「findViewById 绑定」（含 `findViewById` + `RadioButton`）、「回显」（含
  `auto_map_overlay_extra_scale` + `getFloat` + `cmpg-float`）。实测：
  20.15.2 里是 `j4()`/`r3()`/`x4()`/`U4()`，20.16.3 里是 `K4()`/`F3()`，
  **脚本都自动认出来了**。
- **缩放 setter 也不写死**：从点击处理方法体里 `invoke-direct {p0, p1}, ...->X(F)V` 反推。
- **空闲字段名自动挑**：遍历该类已用字段，从 `y1/z1/x1/w1/...` 里选未占用的。
  （20.15.2 手工用的是 `y0/z0`，脚本用的是 `y1/z1`，**效果等价**，只是名字不同。）
- `public.xml` 的 ID 自动取该 type 的 `max+1`，**不会撞已有 ID**。
- 幂等：已打过的直接跳过。

> 另有一个早期版本 `tools/patch_display_size.py`（只做资源+字段，方法体要手工）。
> 保留它是因为逻辑更简单、便于排查；日常用 `_auto` 版即可。

原版设置页「地图显示大小调整」只有 6 档：小 1.0 / 标准 1.1 / 大 1.2 / 特大 1.3（对应 `map_size_small` 等）。
仪表屏 1920×620 太扁，需要更小的缩放才能显示全，因此新增 **最小 0.6f** 和 **更小 0.8f**。

### 3.1 涉及文件一览（共 4 类、26 个文件）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `smali_classes20/com/baidumap/settings/ui/component/display/BASettingDisplayComponent.smali` | 核心逻辑（3 个方法） |
| 2 | `res/values/strings.xml` | 加两个字符串 |
| 3 | `res/values/ids.xml` | 加两个 id |
| 4 | `res/values/public.xml` | 加 2 个 id + 2 个 string 的固定 ID |
| 5 | `res/layout/ba_layout_sub_page_display_map_size_item.xml` | RadioGroup 里插两个 RadioButton |
| 6 | 20 个 `R$id.smali` 副本 | 同步补字段（见 §3.5） |

### 3.2 核心 smali：`BASettingDisplayComponent.smali`（脚本自动改，此处供理解）

类路径：`smali_classes20/com/baidumap/settings/ui/component/display/BASettingDisplayComponent.smali`

#### (a) `j4(...)` —— 点击档位时写值

原方法只有 small/standard/big/too_big 四个分支，重写为 6 个分支：

```smali
.method private static final j4(Lcom/baidumap/settings/ui/component/display/BASettingDisplayComponent;Landroid/widget/RadioGroup;I)V
    .locals 1
    const-string p1, "this$0"
    invoke-static {p0, p1}, Lkotlin/jvm/internal/Intrinsics;->checkNotNullParameter(Ljava/lang/Object;Ljava/lang/String;)V

    sget p1, Lcom/baidu/autonavi/business/settings/R$id;->map_size_smallest:I   # 新增
    if-ne p2, p1, :cond_0
    const p1, 0x3f19999a    # 0.6f
    invoke-direct {p0, p1}, ...->r3(F)V
    return-void

    :cond_0
    sget p1, Lcom/baidu/autonavi/business/settings/R$id;->map_size_smaller:I    # 新增
    if-ne p2, p1, :cond_1
    const p1, 0x3f4ccccd    # 0.8f
    invoke-direct {p0, p1}, ...->r3(F)V
    return-void

    :cond_1
    ... 原 small=1.0 / standard=1.1 / big=1.2 / too_big=1.3 保持不变
.end method
```

> `.locals 1` 且复用 `p1` 存立即数，避免加寄存器。

#### (b) `x4()` —— 找控件并绑定

原方法里依次 `findViewById` 了 6 个 RadioButton 存字段。在 small 之前插入两个：

```smali
sget v0, Lcom/baidu/autonavi/business/settings/R$id;->map_size_smallest:I
invoke-virtual {p0, v0}, ...->findViewById(I)Landroid/view/View;
move-result-object v0
check-cast v0, Landroid/widget/RadioButton;
iput-object v0, p0, ...->y0:Landroid/widget/RadioButton;   # 新增字段 y0

sget v0, Lcom/baidu/autonavi/business/settings/R$id;->map_size_smaller:I
invoke-virtual {p0, v0}, ...->findViewById(I)Landroid/view/View;
move-result-object v0
check-cast v0, Landroid/widget/RadioButton;
iput-object v0, p0, ...->z0:Landroid/widget/RadioButton;   # 新增字段 z0
```

> 用的 `y0` / `z0` 是该类里**未占用的**字段名（Kotlin 混淆后的小写+数字命名空间）。

#### (c) `U4()` —— 进入设置页时回显当前档位

读设置值 `auto_map_overlay_extra_scale`（默认 1.1f），然后在原分支链**最前面**插入两个判断：

```smali
    const-string v0, "auto_map_overlay_extra_scale"
    const v1, 0x3f8ccccd    # 1.1f
    invoke-static {v0, v1}, Lcom/baidu/navisdk/comapi/setting/BNSettingManager;->getFloat(Ljava/lang/String;F)F
    move-result v0

    # ↓↓↓ 新增
    const v2, 0x3f19999a    # 0.6f
    cmpg-float v2, v0, v2
    if-eqz v2, :cond_smallest
    const v2, 0x3f4ccccd    # 0.8f
    cmpg-float v2, v0, v2
    if-eqz v2, :cond_smaller
    goto :goto_size_head
    # ↑↑↑ 新增

    :cond_smallest
    iget-object v2, p0, ...->y0:Landroid/widget/RadioButton;
    if-nez v2, :cond_smallest_set
    return-void
    :cond_smallest_set
    const/4 v3, 0x1
    invoke-virtual {v2, v3}, Landroid/widget/CompoundButton;->setChecked(Z)V
    return-void

    :cond_smaller
    iget-object v2, p0, ...->z0:Landroid/widget/RadioButton;
    if-nez v2, :cond_smaller_set
    return-void
    :cond_smaller_set
    const/4 v3, 0x1
    invoke-virtual {v2, v3}, Landroid/widget/CompoundButton;->setChecked(Z)V
    return-void

    :goto_size_head
    ... 原有 6 档回显逻辑
```

> ⚠️ **踩坑记录**：这里必须用 `if-eqz`（相等则跳进分支）。一开始写成 `if-nez` 是反的，回显永远不对。

### 3.3 资源改动

**`res/values/strings.xml`**（插在 `ba_setting_navi_adjust_small` 之后）：
```xml
<string name="ba_setting_navi_adjust_smaller">更小</string>
<string name="ba_setting_navi_adjust_smallest">最小</string>
```

**`res/values/ids.xml`**：
```xml
<id name="map_size_smallest" />
<id name="map_size_smaller" />
```

**`res/values/public.xml`**（必须给固定 ID，否则 aapt 重新分配会和别的 id 撞）：
```xml
<public type="id"     name="map_size_smallest" id="0x7f0b0ecb" />
<public type="id"     name="map_size_smaller" id="0x7f0b0ecc" />
<public type="string" name="ba_setting_navi_adjust_smaller"  id="0x7f1207cd" />
<public type="string" name="ba_setting_navi_adjust_smallest" id="0x7f1207ce" />
```

> 选这两个 ID 的方法：在 `public.xml` 里找该 type 段的**最大 ID + 1 / +2**，确保没被占用。

**`res/layout/ba_layout_sub_page_display_map_size_item.xml`**：
在 `<RadioGroup android:id="@id/ba_map_size">` 内、`map_size_small` 之前插两个：

```xml
<RadioButton android:textSize="@dimen/ba_text_body_3" android:gravity="center"
    android:id="@id/map_size_smallest" android:layout_width="0.0dp"
    android:layout_height="match_parent" android:button="@null"
    android:text="@string/ba_setting_navi_adjust_smallest"
    android:layout_weight="1.0" style="@style/BASettingRadioStyle" />

<RadioButton android:textSize="@dimen/ba_text_body_3" android:gravity="center"
    android:id="@id/map_size_smaller" android:layout_width="0.0dp"
    android:layout_height="match_parent" android:button="@null"
    android:text="@string/ba_setting_navi_adjust_smaller"
    android:layout_weight="1.0" style="@style/BASettingRadioStyle" />
```

### 3.4 档位数值对照表（改档位只动 `j4` 的立即数）

| 档位 id | 文本 | 缩放 |
|---|---|---|
| `map_size_smallest` | 最小 | `0x3f19999a` = **0.6f** |
| `map_size_smaller` | 更小 | `0x3f4ccccd` = **0.8f** |
| `map_size_small` | 小 | `0x3f800000` = 1.0f |
| `map_size_standard` | 标准 | `0x3f8ccccd` = 1.1f |
| `map_size_big` | 大 | `0x3f99999a` = 1.2f |
| `map_size_too_big` | 特大 | `0x3fa66666` = 1.3f |

float 编码速查（IEEE754 小端 hex）：
`0.6f=0x3f19999a` `0.7f=0x3f333333` `0.8f=0x3f4ccccd` `0.9f=0x3f666666` `1.0f=0x3f800000`

### 3.5 20 个 `R$id.smali` 副本同步

smali 里所有 `R$id` 类都是 `public.xml` 的镜像，**必须逐个补上**新字段，否则 `sget` 会 NoSuchFieldError：

```smali
.field public static final map_size_smallest:I = 0x7f0b0ecb
.field public static final map_size_smaller:I = 0x7f0b0ecc
```

需要改的 20 个文件（换版本后可能变动，用下面命令重新列出）：

```bash
cd _work/apktool_full
grep -rl "map_size_too_big:I" --include="R\$id.smali" . | sort
```

当前清单（20 个）：
```
smali/com/baidu/BaiduMap/R$id.smali
smali_classes2/com/baidu/autonavi/business/wechatiot/R$id.smali
smali_classes2/com/baidu/autonavi/foundation/apireplace/R$id.smali
smali_classes3/com/baidu/autonavi/impl/developer/R$id.smali
smali_classes3/com/baidu/autonavi/lbslibraryimpl/R$id.smali
smali_classes4/com/baidu/autonavi/mapinit/R$id.smali
smali_classes9/com/baidu/naviinit/R$id.smali
smali_classes20/com/baidumap/newenergy/R$id.smali
smali_classes22/com/baidu/autonavi/business/asr/R$id.smali
smali_classes22/com/baidu/autonavi/business/home/R$id.smali
smali_classes24/com/baidu/autonavi/business/login/R$id.smali
smali_classes24/com/baidu/autonavi/business/mycar/R$id.smali
smali_classes25/com/baidu/autonavi/business/onwaysearch/R$id.smali
smali_classes26/com/baidu/autonavi/business/poidetail/R$id.smali
smali_classes26/com/baidu/autonavi/business/pronavi/R$id.smali
smali_classes26/com/baidu/autonavi/business/routeresult/R$id.smali
smali_classes27/com/baidu/autonavi/business/routesearch/R$id.smali
smali_classes27/com/baidu/autonavi/business/settings/R$id.smali
smali_classes28/com/baidu/autonavi/business/track/R$id.smali
smali_classes28/com/baidu/autonavi/business/usercenter/R$id.smali
```

> 注意：`grep -rl` 的输出顺序按目录扫描，实际执行时以上面命令的输出为准，别照抄这段列表的顺序。

这 20 个文件**不用手工改**，`tools/patch_display_size.py` 会自动处理（遍历整个工程找
所有含 `map_size_too_big:I` 的 `R$id.smali`，在它后面插两个字段）。
若想单独做，等价命令：

```bash
cd _work/apktool_full
for f in $(grep -rl "map_size_too_big:I" --include="R\$id.smali" .); do
  grep -q "map_size_smallest:I" "$f" && continue
  perl -0pi -e 's|^(\.field public static (?:final )?map_size_too_big:I = 0x[0-9a-f]+)$|$1\n\n.field public static map_size_smallest:I = 0x7f0b0ecb\n\n.field public static map_size_smaller:I = 0x7f0b0ecc|m' "$f"
done
```

### 3.6 验证

1. 装机后进「设置 → 显示 → 地图显示大小调整」，应看到 **最小 / 更小 / 小 / 标准 / 大 / 特大** 六档。
2. 选「最小」→ 弹「需重启地图生效」→ 立即重启 → 地图应缩小，1920×620 下能显示全。
3. 退出设置页再进，选中项应回显正确（这一步最容易被 `if-eqz` 写反坑到）。
4. 截图留档在 `shots/`（如 `dlg_smallest.png`、`map_060.png`）。

---

## 4. 改动二：红绿灯显示距离改远（改 so）

**状态：✅ 已验证通过（3000m）。**

### 4.1 为什么必须改 so，不能改云控

云控配置文件 `/sdcard/Android/data/com.baidu.naviauto/NaviConfig/cloudcommand.bin`（纯 JSON）里有：

```json
"light_detail": { "switch": 1, "threshold": 1000 }
```

`threshold` = 红绿灯图标/倒计时开始显示的距离（米）。

**但是**：App 每次启动都会向服务端重新拉取并覆盖该文件。
实测把 3000 写进去 + `chattr +i` 锁死，重启后照样被改回 1000；旁证是 `cloudcommand.bin.tmp`（服务端真实下发）里是 `{"switch":1,"threshold":600}`。

所以只能改 so，把赋值指令变成常量。

### 4.2 so 内部结构（关键事实）

```
libBaiduMapAutoEngine.so (41,196,768 B)
  LOAD#1  off=0x0        vaddr=0x0         filesz=0x26954b0   ← vaddr == fileoff
  LOAD#2  off=0x26954b0  vaddr=0x26964b0
  LOAD#3  off=0x2737c48  vaddr=0x2739c48
```

✅ 第一个 LOAD 段覆盖到 `0x26954b0`，而 `.text` 是 `VMA=0x970f00 size=0x1d1b3c8`（结束于 `0x2692c c8`），**完全在 LOAD#1 里且 `vaddr == fileoff`**。
→ **`.text` 内 patch 偏移 = vaddr，不需要换算。**

`light_detail` 字符串在 `.rodata` 的 `0x4eecea`，全 so **只有一处引用**：解析函数 `0x1945a9c`（`..._ZN9_baidu_vi21nanopb_map_set_string...` 的某个巨函数，符号表被剥离所以看不出名字）。

该函数把各键写进配置结构体（结构体基址 = `[x28]`，`x28` 来自 `[sp,#0x28]`，是全局 `0x2959c58 + 0x308` 指向的对象）：

| 键 | 取值指令 vaddr | 写入字段 |
|---|---|---|
| `threshold` | `0x1948ac8` | `+0x10c` ← **红绿灯显示距离** |
| `backthreshold` | `0x1948af4` | `+0x110`（消失回滞） |
| `crossdistmin` | `0x1948b20` | `+0x114` |
| `crossdistmax` | `0x1948b4c` | `+0x118` ← **取坐标上限，必须 ≥ threshold** |
| `NeedDiffTime` | `0x1948b78` | `+0x11c` |
| `DiffTime` | `0x1948ba4` | `+0x120` |

每个键的代码块都是**同一套 7 条指令模板**：

```asm
cbz  x0, skip          ; e0 00 00 b4
ldr  w8, [x0, #0x20]   ; 08 20 40 b9   (cJSON 类型)
cmp  w8, #0x3          ; 1f 0d 00 71
b.ne skip              ; 81 00 00 54
ldr  w8, [x0, #0x30]   ; 08 30 40 b9   (数值) ★ 就是这条要改
ldr  x9, [x28]         ; 89 03 40 f9
str  w8, [x9, #0xNNN]  ; 28 .. .. b9
```

### 4.3 补丁方案

把 `threshold` 和 `crossdistmax` 两块改成：

```asm
movz w8, #3000   ; 52817708   ← 原 cbz，换成常量
nop              ; d503201f
nop              ; d503201f
nop              ; d503201f
movz w8, #3000   ; 52817708   ← 原 ldr w8,[x0,#0x30]
ldr  x9, [x28]   ; 89 03 40 f9   (不动)
str  w8, [x9,#0x10c / #0x118]   (不动)
```

**为什么要把守卫也 nop 掉**：如果只改 `ldr`，当云控不下发 `light_detail` 键（`cbz x0` 命中）时会跳过整块，常量就不生效。
nop 掉守卫后**无条件写入**，与云控内容彻底解耦。

**为什么 `crossdistmax` 也要改**：`GetLightDetailedPos` 里有
`if (GetCCloudRPData.m_stLightControl.nCrossDistMax == 0) return;`
若 `crossdistmax < threshold`，取不到坐标 → 图标画不出来。所以两者都要 ≥ 目标距离。

**`backthreshold` 保持原样**：云控没下发，不影响显示。

字节对照（offset `0x1948ab8` 和 `0x1948b3c`，两块一样）：

| | 原始 | 补丁后 |
|---|---|---|
| +0 | `e0 00 00 b4` (cbz) | `08 77 81 52` (movz w8,#3000) |
| +4 | `08 20 40 b9` | `1f 20 03 d5` (nop) |
| +8 | `1f 0d 00 71` | `1f 20 03 d5` |
| +12 | `81 00 00 54` | `1f 20 03 d5` |
| +16 | `08 30 40 b9` (ldr) | `08 77 81 52` (movz w8,#3000) |

### 4.4 自动化脚本 `tools/locate_light.py`

不写死地址，按**6 条固定指令签名**全 `.text` 扫描定位，再往前找最近的 `adrp+add` 字符串引用确定键名 —— 所以**换版本后直接能用**。

```bash
# 只定位（看清单，确认键名和字段对得上）
python3 tools/locate_light.py <libBaiduMapAutoEngine.so>

# 定位 + 打补丁
python3 tools/locate_light.py <libBaiduMapAutoEngine.so> --patch 3000
```

对原始 so 的输出示例：

```
text  : fileoff 0x0 .. 0x26954b0  (vaddr==fileoff, patch 偏移直接用 vaddr)

找到 52 个候选块，红绿灯区 (字段 +0x100..+0x140)：
block@       field    key                    keyref@
0x1948ab8    +0x10c   threshold              0x1948aa8
0x1948ae4    +0x110   backthreshold          0x1948ad4
0x1948b10    +0x114   crossdistmin           0x1948b00
0x1948b3c    +0x118   crossdistmax           0x1948b2c
0x1948b68    +0x11c   NeedDiffTime           0x1948b58
0x1948b94    +0x120   DiffTime               0x1948b84
0x1948bc0    +0x124   SwitchLongLink         0x1948bb0
0x1948c18    +0x12c   StopNum                0x1948c04
0x1948c98    +0x130   switch                 0x1948c88
0x1948cc4    +0x134   b_t                    0x1948cb4
0x1948cf0    +0x138   a_t                    0x1948ce0
```

脚本特性：
- 幂等：已打补丁的 so 再跑会识别出「已打过补丁的块」并**直接改立即数**（3000 → 2500 这种改档很方便）。
- 校验：打补丁前会断言块首是 `cbz`，不匹配就跳过并提示，不会误伤。
- 已验证：用脚本对原始 so 打 3000，产物 sha1 与手工改的完全一致（`2eddecba…`）。

### 4.5 立即数编码速查

`movz w8, #imm16` = `0x52800008 | (imm16 << 5)`

| 距离 | 指令 | 小端字节 |
|---|---|---|
| 1000 | `52807d08` | `08 7d 80 52` |
| 2000 | `5280fa08` | `08 fa 80 52` |
| 2500 | `52813888` | `88 38 81 52` |
| 3000 | `52817708` | `08 77 81 52` |
| 5000 | `52827108` | `08 71 82 52` |

> 上限 `imm16 = 65535`，即最大 65km，够用。

### 4.6 验证方法（三层，从强到弱）

**① 指令层**（确认 so 真的加载了改后的字节）：

```bash
PID=$(adb shell pidof com.baidu.naviauto | tr -d '\r')
BASE=$(adb shell "grep 'r-xp' /proc/$PID/maps | grep libBaiduMapAutoEngine" | cut -d- -f1)
A=$(python3 -c "print(0x$BASE + 0x1948ac8)")
adb shell "dd if=/proc/$PID/mem bs=1 skip=$A count=16 2>/dev/null | xxd"
# 期望: 0877 8152 8903 40f9 280d 01b9   (movz w8,#3000 / ldr x9,[x28] / str w8,[x9,#0x10c])
```

**② 运行时结构体层**（★ 决定性证据 —— 直接读引擎内存里的配置）：

```bash
python3 - <<'EOF'
import subprocess, struct
PID=int(subprocess.run(['adb','shell','pidof com.baidu.naviauto'],capture_output=True,text=True).stdout)
maps=subprocess.run(['adb','shell','cat /proc/%d/maps'%PID],capture_output=True,text=True).stdout
base=[int(l.split('-')[0],16) for l in maps.splitlines()
      if 'libBaiduMapAutoEngine' in l and 'r-xp' in l][0]
def rd(addr,n):
    return subprocess.run(['adb','shell','dd if=/proc/%d/mem bs=1 skip=%d count=%d 2>/dev/null'%(PID,addr,n)],
                          capture_output=True).stdout
g=base+0x2959c58                      # 全局对象
ptr=struct.unpack_from('<Q', rd(g,0x20), 0)[0]
s=rd(ptr+0x308, 0x130)                # 配置结构体
for off in (0x108,0x10c,0x110,0x114,0x118,0x11c,0x120):
    print('+%#x = %d' % (off, struct.unpack_from('<i',s,off)[0]))
EOF
```

实测输出（云控文件里 threshold=1000、crossdistmax 根本没这键）：

```
+0x108 = 1      (switch)
+0x10c = 3000   ← 云控写 1000，这里是 3000   ★ patch 生效
+0x110 = 3000   (backthreshold)
+0x114 = 10     (crossdistmin，与云控一致 → 证明结构体确实被云控刷过)
+0x118 = 3000   ← 云控没有该键，被 so 强制 3000
+0x11c = 1
+0x120 = 200
```

> `+0x114` 与云控一致、`+0x10c`/`+0x118` 却是 3000 —— 这条对比就是「云控覆盖已被绕过」的铁证。

**③ 观感层**：导航中红绿灯图标/倒计时应在约 3km 处出现。

### 4.6.1 20.16.3 实测记录（2026-10-11）

**整包校验**：设备上装的 apk 与本地构建产物 **sha256 完全相同**
`3ed4d850daf0008cb9f9f7c298d6d0c4786171ed1b8022b5850f9cd068db6c3a`

**层1 — apk 内 so 字节**
```
threshold    @0x1dddee8  087781521f2003d51f2003d51f2003d508778152  OK
crossdistmax @0x1dddf6c  087781521f2003d51f2003d51f2003d508778152  OK
（对照原始 20.16.3：e00000b4082040b91f0d007181000054083040b9）
```

**层2 — 进程内存里的指令**（so base `0x6fdf6c7000`）
```
base+0x1dddee8 : 08778152 1f2003d5 1f2003d5 1f2003d5 08778152
base+0x1dddf6c : 08778152 1f2003d5 1f2003d5 1f2003d5 08778152
```

**层3 — 运行时结构体**（`PKG=com.baidu.BaiduMap python3 tools/verify_light.py 3000`）
```
[A] 指令层
  threshold      block=0x1dddee8 field=+0x104  movz w8,#3000  OK
  crossdistmax   block=0x1dddf6c field=+0x110  movz w8,#3000  OK

[B] 数据层
  字段偏移（从 so 读出）: switch=+0x100 threshold=+0x104 crossdistmax=+0x110
  命中 14 处（14 个不同区域）:
  addr             region                       switch thresh   crossmin  crossmax
  0x6f622bd120     [anon:scudo:secondary]       1      3000     10        3000
  0x6f81884188     [anon:stack_and_tls:8444]    1      3000     10        3000
  ...（其余同）
  ✓ switch/threshold/crossdistmax 全部符合预期

结论: 指令层 OK；数据层 OK
```

**对照云控文件**（设备上仍是服务端下发的原值）：
```json
"light_detail": {"switch": 1, "threshold": 1000}      // 无 crossdistmax 键
```
内存里却是 `switch=1, threshold=3000, crossdistmax=3000` —— **云控覆盖被完全绕过**，这是补丁生效的决定性证据。

**补充说明**：日志层（§4.7）需要真正进入导航路线后才会出现
`Trafficlight[%d]: ... accdist=%d` 记录；本次会话日志只有 5 行（未进导航），
若要拿观感/日志证据，需实际跑一段导航后再看。

### 4.7 引擎日志（辅助排查）

```
/sdcard/Android/data/com.baidu.naviauto/BaiduMap/bnav/naviautoenginelog/
  DIAG_D-NNN-<时间>-<pid>.log.zst   → zstd -d 解压
  DIAG_D-NNN-<时间>-<pid>.log       → 明文
```

关注关键字：

```bash
grep -E "GetLightDetailedPos|BuildLightDetialData|Trafficlight\[|nCrossDistMax|LightControl" DIAG_D-*.log
```

- `Trafficlight[%d]: ... accdist=%d` —— 灯的距离；看有没有 2000~3000 量级的。
- `CRoute::GetLightDetailedPos GetCCloudRPData.m_stLightControl.nCrossDistMax == 0` —— 出现就说明 `crossdistmax` 还是 0，坐标取不到。

### 4.8 云控文件收尾（已处理）

之前为实验改过 `cloudcommand.bin` 并加了 `chattr +i`。现已：

```bash
adb shell "chattr -i /sdcard/Android/data/com.baidu.naviauto/NaviConfig/cloudcommand.bin"
adb shell "mv .../cloudcommand.bin /sdcard/bmbak/cloudcommand.bin.mine"
```

App 会自动重新拉取生成。**改 so 后不需要再动这个文件。**

---

## 5. 其他已知事实（避免重复劳动）

- **反汇编全量**：`objdump -d libBaiduMapAutoEngine.so > /tmp/dis.txt`（764 万行，764MB），grep 定位很快。
- **符号表**：该 so 的 `.dynsym` 只导出 1803 个 JNI 入口（`Java_com_baidu_mapautosdk_jni_*`），内部 C++ 符号**已剥离**，objdump 显示的函数名都是「离得最近的导出符号 + 偏移」，不可信，要靠字符串交叉引用定位。
- **可用工具**：`objdump` / `nm` / `zstd` / `apktool 3.0.3` / JDK 26。**无 radare2**。
- **其他 so 里没有 `light_detail`**：只有 `libBaiduMapAutoEngine.so` 有（已全目录扫描确认）。
- **相关但未改的键**（后续可继续挖）：
  - `greenlightdist`（`.rodata 0x4fd36f`）、`greenlightspeed`（`0x51a43d`）—— 绿波带
  - `rg_greenlightdist` → 结构体 `+0xc3c`、`rg_greenlightspeed` → `+0xc38`
  - `greenWavePlayDistThresh` / `greenWaveMinDist` / `greenWaveShortDist` —— 云控里是 150/150/200
  - `crossdistmin`（`+0x114`，当前 10）配合 `crossdistmax` 控制取点区间
- **签名校验结论**：`AuthController.getSignatureSHA1()` 只把 SHA1 传给 native 鉴权，换签后 App 功能正常，无需绕过。

---

## 6. 目录约定

```
baiduMapv20/
├── README.md                  ← 本文档
├── tools/
│   ├── locate_light.py        ← 定位 + patch 红绿灯显示距离（版本无关）
│   ├── patch_display_size.py  ← 「显示大小」两档的资源/字段自动化（版本无关）
│   ├── verify_light.py        ← 验证补丁是否生效（版本无关）
│   ├── patch_auth_bypass.py   ← 鉴权绕过（21.13.2 起必须，见 §11）
│   ├── build.sh               ← 打包 + 重签 + 装机 一条命令
│   └── restore_so.sh          ← so 还原
├── shots/                     ← 验证截图留档（本地，不入库）
└── _work/                     ← 反编译/构建工作区（本地，不入库）
    ├── apktool_full/          ← **当前在改的**反编译工程（改这里）
    ├── apktool_full_20152/    ← 20.15.2 的工程留档（对照用，勿改）
    ├── baidumap_2016_3.apk    ← 20.16.3 原始包
    ├── baidumap.apk           ← 20.15.2 原始包
    │   ├── lib/arm64-v8a/
    │   │   ├── libBaiduMapAutoEngine.so       ← 已改
    │   │   └── libBaiduMapAutoEngine.so.bak   ← 原始
    │   ├── smali*/res/        ← §3 的改动
    ├── keys/bmap.keystore     ← 自签证书
    ├── patched_raw.apk        ← 重打包产物
    ├── signed/patched_raw-signed.apk  ← 最终装机包
    ├── refs/                  ← 手工改动的参考样例（换版本时对照用）
    │   ├── BASettingDisplayComponent.smali.patched
    │   ├── BASettingDisplayComponent.diff
    │   ├── res_values_*.diff
    │   └── Rid_all.diff
    └── orig_smali/            ← 未改动的原始反编译（对照用，勿改）
```

> 说明：上表中 `shots/` 与 `_work/` 全部内容**仅本地存在**，不进 git（体积大且属反编译产物）。
> 仓库内只有 `README.md`、`tools/`、`_work/keys/bmap.keystore` 与 `.gitignore`。

---

## 7. 换版本 checklist

- [ ] 新版 apk 覆盖 `_work/baidumap.apk`，记下 versionName / versionCode
- [ ] `apktool d -f -o _work/apktool_full _work/baidumap.apk`（**先备份旧工程**，因为 §3 的手改会被覆盖）
- [ ] `python3 tools/locate_light.py <so>` 确认 `threshold` / `crossdistmax` 的字段仍是 `+0x10c` / `+0x118`（若变了，说明结构体布局改了，要重新确认消费端）
- [ ] `python3 tools/locate_light.py <so> --patch 3000`
- [ ] `python3 tools/patch_display_size_auto.py _work/apktool_full`（资源 + R$id + 3 个方法体全自动）
- [ ] `python3 tools/patch_auth_bypass.py _work/apktool_full`（**21.13.2 起必须**，见 §11）
- [ ] `./tools/build.sh`
- [ ] 装机后确认：**不再弹「鉴权解析失败」、进程不自杀**
- [ ] 三层验证（§4.6）
- [ ] 更新本文档里的版本号、sha1、字段表

---

## 8. 版本差异记录（换版本必看）

`tools/locate_light.py` 是按指令签名定位的，**地址会随版本变，脚本会自动找到新地址**。
下面记录各版本实测值，方便对照判断「结构体布局有没有大改」。

### 8.1 版本对照表

| | **20.15.2 (1462)** | **20.16.3 (1471)** | **21.13.2 (1580)** |
|---|---|---|---|
| 包名 | `com.baidu.naviauto` | `com.baidu.BaiduMap` | `com.baidu.BaiduMap` |
| 原始 apk | `_work/baidumap.apk` (152,619,909 B) | `_work/baidumap_2016_3.apk` (157,513,608 B) | `百度地图车机版比亚迪特供版-21.13.2.apk` (153,678,227 B) |
| `libBaiduMapAutoEngine.so` | 41,196,768 B / sha1 `6c37d363…` | 46,578,952 B / sha1 `db137ead…` | 73,576,480 B / sha1 `6adc5a7e…` |
| `.text` 范围（section） | `0x0 .. 0x26954b0` | `0x0 .. 0x2ba8300` | `0x109c500 .. 0x44c0290` |
| `light_detail` 字符串 | `0x4eecea` | `0x580eba` | `0x89577f` |
| 解析函数（light_detail 引用点） | `0x1948a7c` | `0x1dddeac` | `0x263ec68` |
| `threshold` 块 / 字段 | `0x1948ab8` / **`+0x10c`** | `0x1dddee8` / **`+0x104`** | `0x263eca4` / **`+0x15c`** |
| `backthreshold` 块 / 字段 | `0x1948ae4` / `+0x110` | `0x1dddf14` / `+0x108` | `0x263ecd0` / `+0x160` |
| `crossdistmin` 块 / 字段 | `0x1948b10` / `+0x114` | `0x1dddf40` / `+0x10c` | `0x263ecfc` / `+0x164` |
| `crossdistmax` 块 / 字段 | `0x1948b3c` / **`+0x118`** | `0x1dddf6c` / **`+0x110`** | `0x263ed28` / **`+0x168`** |
| 签名补丁（手工改） | `0x1948ab8` / `0x1948b3c` | 由脚本自动得出 | 由脚本自动得出 |
| 已构建产物 | `_work/signed/…`（已装机验证） | `_work/out/naviauto_20.16.3_light2000_size06-08.apk` | `_work/out/naviauto_21.13.2_light2000_size06-08_authfix.apk`（155,783,921 B） |
| 补丁后 so sha1（3000m） | `2eddecba…` | `5edc487b…` | — |
| 补丁后 so sha1（2000m） | — | `78fbbb76…` | `a76fd234…` |
| smali 方法名 | `j4()` / `r3()` / `x4()` / `U4()` | `K4()` / `F3()` / `x4()` / `U4()`（脚本自动识别） | `r4()` / `l3()` / `x4()` / `U4()`（脚本自动识别） |
| 鉴权校验 | 无 | 无 | **有**（`authConfig.dat`，见 §11） |

> ⚠️ **字段偏移会整体平移**（20.15.2 `+0x10c` → 20.16.3 `+0x104` → 21.13.2 `+0x15c`，平移了 +0x58）。
> 这说明 `m_stLightControl` 在结构体里的位置会变，**但键的相对顺序完全一致**
> （threshold → backthreshold → crossdistmin → crossdistmax，字段 +4 递增）。
> 脚本靠「键名 + 字段 +4 递增」分组识别，所以不受影响。
>
> 21.13.2 起 `locate_light.py` / `verify_light.py` 已**去掉写死的 `0x100..0x140` 字段窗口**，
> 改为按「键名属于 light_detail 键集 + keyref 紧贴块前 16 字节 + 字段 +4 递增」聚组，
> 任意偏移都能认。早期版本因为写死窗口，在 21.13.2 上会漏掉整组（只认出 `routeplan_switch` 等无关块）。
>
> 如果哪天这个递增关系也断了，说明结构体布局大改，需要按 §4.6 的方法
> 重新确认消费端（`GetLightDetailedPos`）读的是哪个字段。

### 8.2 20.16.3 的脚本实测输出

```bash
$ python3 tools/locate_light.py _work/apktool_full/lib/arm64-v8a/libBaiduMapAutoEngine.so
text  : fileoff 0x0 .. 0x2ba8300  (vaddr==fileoff, patch 偏移直接用 vaddr)

找到 52 个候选块，红绿灯区 (字段 +0x100..+0x140)：
block@       field    key                    keyref@
0x1dddee8    +0x104   threshold              0x1ddded8
0x1dddf14    +0x108   backthreshold          0x1dddf04
0x1dddf40    +0x10c   crossdistmin           0x1dddf30
0x1dddf6c    +0x110   crossdistmax           0x1dddf5c
0x1dddf98    +0x114   NeedDiffTime           0x1dddf88
0x1dddfc4    +0x118   DiffTime               0x1dddfb4
...
```

键名识别全部正确，直接 `--patch` 即可。

### 8.3 显示大小两档：资源 ID 会变

`tools/patch_display_size.py` 的 ID 是**自动取该 type 的 max+1**，所以不同版本会不一样：

| | 20.15.2 | 20.16.3 |
|---|---|---|
| `map_size_smallest` | `0x7f0b0ecb` | `0x7f0b0ec0` |
| `map_size_smaller` | `0x7f0b0ecc` | `0x7f0b0ec1` |
| `ba_setting_navi_adjust_smaller` | `0x7f1207cd` | `0x7f1207bc` |
| `ba_setting_navi_adjust_smallest` | `0x7f1207ce` | `0x7f1207bd` |
| 新增字段名 | 手工 `y0`/`z0`；脚本 `y1`/`z1` | 脚本 `y1`/`z1` |

只要 `public.xml`、`R$id.smali`、smali 里的 `sget` 三处一致就行（脚本会保证），
**不要跨版本照抄 ID**。

### 8.4 设备侧注意

20.16.3 的包名是 `com.baidu.BaiduMap`，所以：

```bash
adb shell "am force-stop com.baidu.BaiduMap"
adb install -r -d _work/signed/patched_raw-signed.apk
# 验证时指定包名
PKG=com.baidu.BaiduMap python3 tools/verify_light.py 3000
```

`tools/verify_light.py` 默认包名是 `com.baidu.BaiduMap`，可用环境变量 `PKG=` 覆盖。

---

## 9. 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-10-11 | 20.15.2 | 「显示大小」加 0.6f/0.8f 两档（手工 smali+res，已验证） |
| 2026-10-11 | 20.15.2 | 红绿灯显示距离 1000→3000m（改 so，已验证：内存结构体 +0x10c=+0x118=3000） |
| 2026-10-11 | — | 抽出 `tools/` 三个脚本；补全本文档 |
| 2026-10-11 | 20.16.3 | 用脚本重新定位成功（threshold `+0x104`、crossdistmax `+0x110`）；工程迁到 `_work/apktool_full`，20.15.2 留档为 `apktool_full_20152` |
| 2026-10-11 | 20.16.3 | 全流程跑通：`locate_light --patch 3000` + `patch_display_size_auto` + `build.sh`，产物 `_work/out/naviauto_20.16.3_light3000_size06-08.apk`（签名校验通过） |
| 2026-10-11 | — | 修 `patch_display_size_auto.py` 回显段格式化参数个数不匹配（30 个 `%s` / 19 个实参）导致的崩溃 |
| 2026-10-11 | 20.16.3 | 修 `verify_light.py` 数据层判据：原来写死 `off-8` 当 switch，20.16.3 字段偏移变了会漏判；改为**从磁盘 so 自动读出字段偏移**再扫内存 |
| 2026-10-11 | 20.16.3 | **三层验证全部通过**（详见 §4.6 实测记录） |
| 2026-10-11 | 20.16.3 | 红绿灯距离 3000 → **2000**（一条命令改档），重编译重签装机，三层验证再次通过；产物 `_work/out/naviauto_20.16.3_light2000_size06-08.apk` |
| 2026-10-11 | — | 修 `locate_light.py` 改档分支：原来把字段偏移写死成 20.15.2 的 `0x10c/0x118`，导致 20.16.3 上「3000 改 2000」匹配不到；改为按「红绿灯组 field 最小/最大」识别 |
| 2026-10-12 | 21.13.2 | 新版本适配：`locate_light.py`/`verify_light.py` 去掉写死字段窗口（改为键名+字段+4递增聚组），自动找到 `threshold @0x263eca4/+0x15c`、`crossdistmax @0x263ed28/+0x168` |
| 2026-10-12 | 21.13.2 | 新增 `tools/patch_auth_bypass.py`（7 处），绕过新增的 `authConfig.dat` 鉴权校验；修 static 方法误写成实例方法导致的 `IncompatibleClassChangeError` |
| 2026-10-12 | 21.13.2 | 全流程跑通：`locate_light --patch 2000` + `patch_display_size_auto` + `patch_auth_bypass` + `build.sh`；产物 `_work/out/naviauto_21.13.2_light2000_size06-08_authfix.apk`，三层验证通过、启动不再自杀 |
| 2026-10-11 | — | **修体积暴涨 bug**：so 备份 `.bak` 误放在 `lib/arm64-v8a/` 里，被 apktool 打进 apk，包体 152→178MB。备份改放 `_work/so_orig.bak`；`build.sh` 增加打包前 `lib/` 体检 + 自动移走误放文件；`locate_light.py` 也加同样提示 |

---

---

## 11. 改动三：鉴权绕过（21.13.2 起必须）

**状态：✅ 已验证通过。**

### 11.1 现象

换签安装 21.13.2 后：
1. 启动弹 Toast「**鉴权解析失败，请检查鉴权文件的正确性**」
2. 约 3.75 秒后进程被 `killProcess(myPid())` 杀掉 → 表现为「**自动 crash**」
3. 偶尔能进地图但一直卡启动页（引擎初始化失败被兜底重试）

### 11.2 根因

21.13.2 起 SDK 新增了**离线鉴权文件校验**（20.16.3 没有这条链路）：

```
EngineController$b.handleMessage   (msg.what == 0x11，启动 3 秒后)
  ├─ AuthController.verifyAuthentication()     ← 校验 authConfig.dat
  ├─ AuthController.loadAuthConfigSuccess()    ← 文件是否解析成功
  └─ 二者任一 false
        → Toast「鉴权解析失败，请检查鉴权文件的正确性」(duration 3000)
        → AndroidUtil.runOnUiThread(new d.e(), 0x3a98=15000ms? 实测 3.75s)
        → AuthController.a() → Process.killProcess(myPid())
```

`assets/authConfig.dat`（8,608 B，加密二进制）里签的是**原始包的签名/包名/厂商信息**，
校验在 native 层（`libBaiduMapAutoEngine.so` 的
`Java_com_baidu_mapautosdk_jni_JNIAuthentication_loadFile` / `_authenticate`）：

| 函数 | 21.13.2 vaddr |
|---|---|
| `..._JNIAuthentication_init` | `0x11385c4` |
| `..._JNIAuthentication_loadFile` | `0x11388c8` |
| `..._JNIAuthentication_authenticate` | `0x1138d50` |

**重签后签名变了 → native 校验必然失败 → 走 killSelf 分支。**
改 `authConfig.dat` 文件内容没用（签名对不上），所以从 **Java 层把判定短路**。

### 11.3 补丁点（共 7 处）

`tools/patch_auth_bypass.py`，全部按「类描述符 + 方法签名」内容锚定，不写死 `smali_classesN`：

| # | 类 | 方法 | 改成 |
|---|---|---|---|
| 1 | `AuthController` | `verifyAuthentication()Z` | `return true` |
| 2 | `AuthController` | `loadAuthConfigSuccess()Z` | `return true` |
| 3 | `AuthController` | `static authFailed(String,Z)V` | `return-void`（不弹窗、不 killSelf） |
| 4 | `AuthStrategyV1`(`f`) | `j()Z` | `return true`（native authenticate 结果） |
| 5 | `EngineController$b`(`d$b`) | `static c()V` | `return-void`（去掉 killProcess） |
| 6 | `EngineController$b`(`d$b`) | `static d()V` | `return-void`（去掉 killProcess） |
| 7 | `AuthStrategyV0`(`e`) | `j()Z` | `return true`（LBS 分支） |

> ⚠️ **踩坑**：`authFailed` 和 `d$b.c()/d()V` 是 **static** 方法，
> 第一次改写成实例方法（少了 `static`）→ 运行时报
> `java.lang.IncompatibleClassChangeError: The method 'void ...authFailed(String,boolean)'
> was expected to be of type static but instead was found to be of type virtual`
> → 直接 FATAL EXCEPTION 卡启动页。脚本已修正为保留 `static`。

```bash
python3 tools/patch_auth_bypass.py _work/apktool_full          # 打补丁（幂等）
python3 tools/patch_auth_bypass.py _work/apktool_full --check  # 只检查
```

### 11.4 验证

```
安装后启动 → 无鉴权 Toast，进程 PID 长时间不变（实测 >120s 存活），地图正常渲染
logcat 无 FATAL EXCEPTION / IncompatibleClassChangeError
```

### 11.5 21.13.2 其他版本差异

| 项 | 变化 |
|---|---|
| versionCode / versionName | 1580 / 21.13.2 |
| dex 数量 | 30 个（20.16.3 是 29 个） |
| `libBaiduMapAutoEngine.so` | 73,576,480 B（20.16.3 是 46,578,952 B，大了 58%） |
| `.text` 是独立 section | `.text @0x109c500`，**不再从 0 开始**（脚本按 ELF LOAD 段自动定位） |
| `R$id.smali` 副本数 | 25 个（20.16.3 是 20 个） |
| `BASettingDisplayComponent` | `smali_classes22`（20.16.3 在 `smali_classes20`） |
| 显示大小 setter | `l3(F)V`（20.16.3 是 `F3`） |
| 新增鉴权校验 | 见上 |


## 10. 待办 / 可继续挖

- [x] 20.16.3 上把两项改动完整走一遍（脚本 → build，已产出 apk）
- [x] 20.16.3 的 apk 装机后按 §4.6 做三层验证 —— 全部通过（见 §4.6.1）
- [ ] 实际跑一段导航，抓 `Trafficlight[...] accdist=` 日志做观感验证
- [ ] 2000m 观感确认（若嫌近/嫌远，改档命令见 §4.5）
- [ ] `backthreshold`（消失回滞）要不要一起抬？当前保持云控值
- [ ] 绿波带相关键（`greenlightdist` / `greenlightspeed` / `greenWave*`）能否也抬距离
- [ ] `crossdistmin`（当前 10）配合 `crossdistmax` 的取点区间是否需要调
