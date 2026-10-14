# Windows 10 / Sublime Text 4215 交付与验收

目标运行环境是 Windows 10 x64、Sublime Text build **4215** 及其内置 **Python 3.14**。
交付形式是 `PlainTasks.sublime-package` 加离线依赖、PowerShell 脚本和真实编辑器测试插件。
Windows 机器暂不可连接，因此必须在目标机器运行本流程后才能确认 Windows 验收完成。
Mac 上的真实 4215 测试、Python 单元测试及打包校验各有作用；它们不能替代 Windows 的原生窗口与按键验收。

## 内容与目录

解压 `PlainTasks-windows-4215.zip` 后得到：

| 文件/目录 | 用途 |
| --- | --- |
| `PlainTasks.sublime-package` | 可直接安装的插件 ZIP，根目录包含 `.python-version` 的 `3.14` |
| `PlainTasks.package-manifest.json` | 包内每个文件的 SHA256、大小及包的 SHA256 |
| `manifest.json`、`SHA256SUMS` | 交付包内容校验；源码 commit 及 `source_dirty` 标识 |
| `lib/python314/` | dateutil、six、zoneinfo 资源及发行元数据/许可证 |
| `windows/*.ps1` | 安装、隔离测试、恢复及公共函数 |
| `smoke/editor_smoke.py` | 只安装到测试副本 `Packages/User` 的真实 Sublime API 测试 |
| `README.zh-CN.md`、`WINDOWS_4215.md` | 操作和验收说明 |

插件压缩包采用显式允许列表，包含模块、语法、设置、主题、菜单、教程、HTML 模板、图标、许可证和依赖声明。
不把 `.git`、CI、tests、tools、docs 目录、缓存或开发环境装进插件包；测试和交付工具放在外层交付 ZIP。
离线库安装到数据目录的 `Lib\python314`。仅复制插件包不能保证日期解析完整：例如英文月份名称需要 dateutil。

## 1. 校验交付与准备官方编辑器

将 ZIP 和旁边的 `.sha256` 文件一起复制到 Windows。核对：

```powershell
Get-FileHash .\PlainTasks-windows-4215.zip -Algorithm SHA256
Get-Content .\PlainTasks-windows-4215.zip.sha256
```

SHA256 用于检测传输损坏；安装/测试脚本还会逐文件检查 `manifest.json`。
它不替代对下载来源的信任。使用下面的 Sublime 官方链接获取 4215 x64 portable ZIP，交付包不重新分发编辑器：

- [官方发布说明与下载页](https://www.sublimetext.com/download)
- [build 4215 x64 portable ZIP](https://download.sublimetext.com/sublime_text_build_4215_x64.zip)
- [官方命令行文档](https://www.sublimetext.com/docs/command_line.html)

使用普通用户 PowerShell，无需管理员权限。命令中的 `-ExecutionPolicy Bypass` 只作用于这一次 PowerShell 进程。

## 2. 隔离运行真实编辑器测试

在完整交付包的解压目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Test-PlainTasks4215.ps1 -PortableZip "$env:USERPROFILE\Downloads\sublime_text_build_4215_x64.zip" -WorkRoot "$env:USERPROFILE\Desktop\PlainTasks 验收 4215" -KeepOpen
$LASTEXITCODE
```

测试目录必须尚不存在，防止覆盖已有个人数据。脚本解压到新目录，检查 PE 的 x64 类型及文件版本 4215，创建紧邻 `sublime_text.exe` 的 `Data`，并以 `--multiinstance --debug` 启动独立实例。
官方 portable ZIP 的 `Data/KEEPME` 空标记文件可以保留；若还带有其他 `Data` 内容，脚本会停止。已有自用编辑器目录可作为只读来源：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Test-PlainTasks4215.ps1 -PortablePath 'C:\Tools\Sublime 4215' -WorkRoot "$env:USERPROFILE\Desktop\另一轮 PlainTasks 验收" -KeepOpen
```

来源目录的 `Data` 被排除，个人设置和许可证不会复制。测试只更改新副本；不会向正式 `%APPDATA%` 安装或终止正式 Sublime 进程。
脚本写入 UTF-8 无 BOM 的启动 marker，测试插件在加载后自动执行 `plain_tasks_smoke_test`，无需手工转义命令行 JSON。
等待时限默认 120 秒，可通过 `-TimeoutSeconds 180` 调整。

结果都留在 `WorkRoot`：

- `smoke-result.json`：真实 build、Python、平台、架构、插件来源、库搜索路径及每项结果。
- `smoke-result.html`：UTF-8 HTML 导出示例。
- `environment.json`：Windows/PowerShell 版本、编辑器文件版本/散列和 Authenticode 状态，便于复现。
- `debug.stdout.log`、`debug.stderr.log`：调试日志；加载失败或超时时先检查它们，再查看 Sublime 控制台。

脚本只有在报告确认 `4215`、Python `3.14`、`windows`、`x64` 且所有自动检查成功时才返回 **0**。超时、版本错误、包校验失败或测试失败返回 **1**。
成功报告中的 `manual_pending` 仍需下一步验收。未给 `-KeepOpen` 时尝试关闭本次测试窗口；测试输出保留以便分析。

## 3. Windows 原生验收

在保留的隔离窗口中用命令面板执行 **Tasks: New document**，保存到含空格和中文的目录。
逐项确认，并记录 Windows 版本、显示缩放、输入法与异常截图/控制台日志：

| 操作 | 通过标准 |
| --- | --- |
| 输入中文，`Ctrl+Enter` 新建，`Ctrl+D` 完成/恢复，`Alt+C` 取消/恢复 | 光标、任务符号、文本、时间标签正确，无快捷键冲突 |
| 多光标完成、`Ctrl+Shift+A` 归档、撤销 | 每项只处理一次，归档保留项目归属，撤销恢复原文 |
| `@due(+2w)` 后按 Tab；F4 添加 due 标签；右键 **Tasks: Show date picker** 切换月/年 | 相对日期正确展开，闰年/月末切换不报错，弹窗内容可读且可点击 |
| 鼠标悬停首字符的任务符号并点击完成 | 首字符位置也打开弹窗，缩放下无截断，点击动作生效 |
| **Tasks: Save as HTML…** 保存到中文/空格路径 | 原生保存窗口可用，生成 UTF-8 HTML，中文、HTML 转义及主题配色正确 |
| **Tasks: View as HTML** | 外部浏览器正常打开临时 HTML，无路径/编码错误 |
| 中文、空格、盘符的文件链接及行列跳转 | 打开正确文件并跳转，非法链接安全返回 |
| Tasks 菜单中的 Tutorial | 压缩包安装时能打开可编辑的 scratch 教程副本，教程任务可完成/恢复，原教程资源保持完整 |
| 关闭后再次启动隔离副本 | 插件重新加载正常，无控制台 traceback，CRLF 与用户设置保持 |

自动检查包含真实语法 scope、资源加载、日期库、任务操作、HTML、Windows keymap 定义及 CRLF/Unicode，但 keymap 定义通过不代表键盘实际事件已通过。

## 4. 正式安装或回滚

关闭将要安装的 Sublime 实例。在目标实例的控制台确认 `sublime.version()` 为 `'4215'`。
Portable 目录指紧邻 `sublime_text.exe` 的目录：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-PlainTasks.ps1 -PortablePath 'C:\Tools\Sublime 4215'
```

安装路径是 `C:\Tools\Sublime 4215\Data\Installed Packages\PlainTasks.sublime-package`。
正式非 portable 安装先用 **Preferences → Browse Packages** 查看实际 `Packages` 目录，其父目录就是 `-DataPath`。通常为：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-PlainTasks.ps1 -DataPath "$env:APPDATA\Sublime Text"
```

已有旧 `Sublime Text 3` 数据目录时，以目标编辑器实际选择的路径为准。
脚本检测旧 `Installed Packages\PlainTasks.sublime-package`、覆盖目录 `Packages\PlainTasks`，以及共享 `Lib\python314` 内的 dateutil/six 与其发行元数据。
一致的内容会跳过，字节码缓存不会触发冲突；不同内容先停止。
检查冲突后，加 `-BackupExisting` 才进行替换；这也可能更新其他插件共用的 dateutil/six，因此应同时检查这些插件。
旧文件移到数据目录 `PlainTasks Backups\时间戳`，输出 `restore.json`，保留备份目录完整内容。
不修改个人 `Packages\User` 设置、快捷键、其他插件或任务文档。

重启编辑器验收。如需恢复，先关闭 Sublime，然后运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Restore-PlainTasks.ps1 -JournalPath 'C:\实际数据目录\PlainTasks Backups\实际时间戳\restore.json'
```

恢复前再次检查安装目标内容。若已被用户修改，脚本停止，避免覆盖；新装且无旧版的包会移除，原版包、覆盖目录及依赖恢复。
安装中途失败会自动撤销本次已完成的复制/移动。保留 `ROLLED_BACK.txt` 或 `RESTORED.txt` 的记录，防止重复应用恢复日志。
若使用 Package Control 管理正式安装，应检查其自动更新设置，避免之后覆盖这份待验收的构建。

## 从源码重建

开发机有 Python 和 pip 时，可先下载固定依赖到一个临时目录；然后执行：

```text
python3 -m pip install --target /tmp/plaintasks-release-libs --no-compile python-dateutil==2.9.0.post0 six==1.17.0
python3 tools/build_release.py --libraries /tmp/plaintasks-release-libs
```

输出在 `dist/`，包含插件包、包清单、交付 ZIP 和各自 `.sha256`。
相同源文件/依赖在相同 Python/zlib 环境下，ZIP 排序、时间戳、权限及内容一致，可重现散列。
`source_dirty: true` 表示在记录的 commit 上还有本地改动；包内逐文件清单给出此次实际交付内容。

源码保留安装工具回归测试，可对完整解压交付包运行：

```powershell
powershell.exe -NoProfile -File .\tests\windows_delivery_selftest.ps1 -BundleRoot 'C:\交付包解压目录'
```

测试在新的临时目录复制一份交付包，验证冲突无改动、备份/恢复、个人设置保护、字节码缓存、失败自动回滚和清单校验。
可显式指定 `-RepositoryRoot` 和尚不存在的 `-TestRoot`；测试不启动编辑器、不修改传入的交付包或正式配置，且不装入用户交付 ZIP。
