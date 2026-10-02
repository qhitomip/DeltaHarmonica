# 开发说明

这是开发者文档，不是软件界面、宣传文案或内测说明。应用发布身份保持 v1.0.0 正式版。

## 环境与启动

Windows x64，Python 3.11 或 3.12。应用依赖仅 Mido、PySide6-Essentials，完整版本约束以 `pyproject.toml` 为准。

在仓库根目录执行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\run.ps1
```

如果使用 Python 3.12，将第一行的 `-3.11` 换为 `-3.12`。也可直接使用虚拟环境解释器执行 `-m delta_harmonica`。开发辅助 `.packages` 目录是本机依赖目录，不参与源码分发。

## 模块职责

| 模块 | 职责 |
| --- | --- |
| `app.py` | Qt 启动、单实例接入、窗口激活 |
| `ui.py` | 主界面、音轨对话框、用户操作和全局热键 |
| `midi.py` | 文件解析、候选排序、单音化、游戏音域适配 |
| `performer.py` | 演奏时间轴、状态、取消和线程清理 |
| `game_io.py` | 游戏音高/物理键映射、Windows SendInput |
| `audition.py` | Windows MIDI 合成试听，独立于游戏输入 |
| `storage.py` | 曲谱列表、偏好、演奏 JSON 读写及校验 |
| `presets.py` | 四个任务片段的固定音符和物理按键 |
| `themes.py` | 共享深浅样式、太阳／月亮切换图标 |
| `settings.py` | 热键、速度范围与常用倍速常量 |
| `speed_control.py` | 倍速按钮及弹出面板、快选、精确输入、长按微调 |
| `overlay.py` | 鼠标穿透、不抢焦点的状态悬浮窗 |
| `hotkey.py` | F12 低级键盘监听、长按抑制和注销 |
| `single_instance.py` | 用户目录锁及本机窗口唤醒通信 |

解析结果通过 `MidiAnalysis` 交给选轨界面，再由 `convert_analysis()` 转换。`convert(path)` 仍是直接读取文件并转换的接口。避免同一导入流程重复解析 MIDI。

## 保持的约束

- 启停来自同一热键；鼠标修饰键互斥，只允许一个音键。
- 演奏线程拥有游戏输入，取消请求与发键通过同一锁同步。
- 时序必须保持所选速度；不能用加长音符的方式拖慢整曲。
- 异常关闭和设备错误需可见；不能把失败伪装成完成。
- GUI 不内置模型、音频转换或旧格式迁移分支。
- 简谱/按键图是外部脚本产物，不能写成现有 UI 功能。
- 不为格式美化重排无关代码；补充测试应针对实际失败场景。

## 回归检查

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
git diff --check
```

测试使用模拟 MIDI 输出和模拟游戏输入，不应向实际游戏发键。开发测试代码不会打包成应用功能。游戏实测、自动化回归和正式包启动检查必须分别记录，不能相互替代。

历史 `docs/phase*`、`docs/initial-*` 等目录是过往决策和检查记录，可能描述已删除的功能。当前功能只以根目录 README、`docs/FEATURES.md` 和当前源码为准。

## 单 EXE 构建

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\build.ps1 -OutputDirectory 'dist/release-1.0.0'
```

输出 `dist/release-1.0.0/DeltaHarmonica.exe`。构建脚本优先虚拟环境，再查本机工具运行时，最后系统 Python。PyInstaller 及运行依赖需安装到选用的解释器环境。

`packaging/DeltaHarmonica.spec` 在封包前选定运行库：从 System32 读取列出的 VC++ DLL，从当前 Python 的 DLLs 目录读取 OpenSSL DLL。缺少文件会明确失败，需要准备相符的 Windows x64 构建环境；没有声称任意电脑都可直接复现此构建。正式包不依赖用户机器上安装 Python。

EXE 内包含 README、第三方声明、许可证和 DLL 哈希清单；不包含开发测试、历史阶段文档、制图脚本或模型。没有打包后再修改 DLL 的步骤。

每次交付检查文件版本/正式标记、单 EXE 独立启动、重复启动、关闭清理和包内依赖；不只检查打包命令退出码。版本由 `src/delta_harmonica/__init__.py` 提供给界面和 EXE 元数据，`pyproject.toml` 的包版本需同步维护。

## 当前边界

MIDI 解析与适配仍在 GUI 操作流程同步执行，极大文件可能短暂影响界面响应。此轮仅去除重复解析，未增加后台队列或做无关架构改造。主旋律推荐、八度适配和游戏输入效果仍需结合具体曲谱与游戏环境判断。


## 当前界面契约

默认 F6、3 秒、1.0x；热键 F1～F12；6 个常用档位，支持 25～150% 整数百分比。速度保存在每个 MidiSong，不再属于 Preferences。SpeedControl.percent 是已提交值，固定稳定播放，已删除原始时序模式及偏好字段。每次导入均要求用户确认音轨，每个候选行提供试听按钮。预设与普通歌曲同表保存，可删除，空列表保持为空；当前 preferences/library 格式为第 2 版，不迁移旧格式。

F1～F11 使用 RegisterHotKey + MOD_NOREPEAT，标识符在应用允许范围内。F12 使用仅筛选 F12 的 WH_KEYBOARD_LL 钩子，按下边沿通过 Qt 排队信号触发，抑制长按重复；切换设置/退出时注销，代次编号阻止旧排队事件触发新会话。钩子不存储其他按键，不写键盘日志，不发送输入。

Windows 不允许按普通方式注册 F12，依据：[Microsoft RegisterHotKey 文档](https://learn.microsoft.com/zh-cn/windows/win32/api/winuser/nf-winuser-registerhotkey)。原生注册/钩子安装检查与游戏内是否接收输入应分别判断。

主题通过 MainWindow 样式表向子窗口传播，浅色仅覆盖共享布局中的颜色；倍速面板不再持有独立固定颜色。手绘控件使用当前 palette 文字颜色。局内 overlay 保留自己的深色样式。Preferences.theme 仅接受 dark/light，未知或缺省使用 dark。

应用图标资源位于 `src/delta_harmonica/assets/`：`app.png` 是透明底母图，`app.ico` 包含 16、20、24、32、40、48、64、128、256 像素尺寸。Qt 从包内路径加载 ICO；构建配置同时将 ICO 嵌入 EXE 图标资源，并收集 assets。更换图标需同步更新两份资源并重新构建。
