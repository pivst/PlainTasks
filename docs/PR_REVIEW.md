# PR #1 审查与交付记录

审查日期：2026-10-14（Asia/Taipei）。目标：Windows 10 x64、Sublime Text 4215。

## 采纳结论

建议采纳 [PR #1](https://github.com/pivst/PlainTasks/pull/1) 作为重构基础，使用本地补丁后的构建交付。
PR 修复了 Python 3.14 下的 `cgi` 导入、正则全局 flag、弹窗整数参数、跨 view 的 edit token 和压缩包 HTML 资源读取。
移除 ST2/Python 2/3.3 路径符合本次 4215 目标；这份交付不承担老版本兼容。

审查的 PR head 为 `e4ec5a4d3bad650d09a26fa5313de6c37727349c`，base 为
`65639252b11d0979bd9c50119a74e2bec07deb80`。读取时 PR 为 OPEN、可合并、无评审和评论，
Linux/Windows/macOS 的 CI 均为 SUCCESS。[CI run](https://github.com/pivst/PlainTasks/actions/runs/38425236526)。
远端 PR 未合并；本地分支 `refactor/st4215-delivery` 已以其代码为基础完成下述修补。

## 补齐的问题

| 问题 | 影响 | 本地处理 |
| --- | --- | --- |
| 现代主题 scope 与真实语法不一致 | 完成正文/完成取消标签颜色丢失 | 查询实际 `comment.line.completed.todo`、`meta.tag.todo.*` scope |
| 字体 False 值没有输出 normal | 导出的现代主题继承模板斜体 | 明确输出 normal/bold 和 normal/italic |
| `style_for_scope()` 不含全局背景 | Mariana HTML 导出背景缺失；真实编辑器首次测试发现 | `body` 使用 `View.style()` |
| 对每段加粗/斜体文本使用 `strip('_*')` | `**_literal_**` 内的字面下划线被删 | 仅移除真实语法的 punctuation scope |
| 菜单打开 `${packages}/PlainTasks/...` 实体文件 | 压缩包中教程、默认设置、默认按键无法可靠打开 | 使用 `sublime.load_resource()` 创建副本；教程可练习，默认配置只读 |
| Windows 使用 CMD `start` 调 URL | 空格路径、`&` 查询参数可能被 shell 解释 | 用 `os.startfile()` 直接交给注册处理器 |
| 离线目标没有 dateutil | 英文月份及 dayfirst 等解析缺少完整能力 | 交付 dateutil 2.9.0.post0、six 1.17.0 完整运行库及许可证 |

独立单测补足字体、scope、字面字符和 Windows 处理器参数。Windows 处理器的单测只证明参数传递，不替代真实 ShellExecute 验收。

## 已完成验证

| 层次 | 环境与结果 | 本地证据 |
| --- | --- | --- |
| 独立回归 | Python 3.14.8，36/36；DeprecationWarning 当错误 | `validation/standalone.log` |
| 编译与格式 | SyntaxWarning 当错误；`git diff --check` | 本地检查通过 |
| 压缩安装 | 真正 Sublime 4215，macOS arm64，内嵌 Python 3.14.6，19/19 | `validation/macos-packed.json` 与 `.environment.json` |
| 源码目录安装 | 同一插件包解压后，真实 4215，19/19 | `validation/macos-loose.json` 与 `.environment.json` |
| 打包 | 显式允许列表、逐文件清单、SHA256、重复构建一致 | `dist/` 的 manifest 和 sha256 文件 |
| 安装恢复逻辑 | 临时 PowerShell 7.5.11 / macOS：解析、冲突、备份、幂等、用户改动保护、恢复、junction 拒绝 | `tests/windows_delivery_selftest.ps1` |
| Windows 官方编辑器文件 | 官方 4215 portable ZIP 的 PE machine 为 x64，版本字段为 4215 | 静态检查；没有运行 Windows 程序 |

两个真实编辑器测试的插件包 SHA256 都为
`71ce5d1fe911bcac9061b1c48cdb715ad2d58020ca6fc31db06bc6d1a015bc86`。
测试包括任务新建/完成恢复/取消恢复、多光标、归档、TaskPaper、日期和闰日、首字符 hover 与动作、
压缩资源菜单、HTML 转义/markup/配色、文件链接解析、Windows keymap 定义、中文空格路径的实际 CRLF 保存。

## Mac 隔离方式及“应用已损坏”处理

本机最初用命令行解压官方 ZIP，macOS 提示应用损坏，签名核验失败；不能把这次尝试算测试通过。
按 [Sublime 官方员工建议](https://forum.sublimetext.com/t/not-allowed-to-run-on-mac-with-os-15-5/76331)
改用 Finder / Archive Utility 解压后，原始应用签名有效。向签名应用内部加入测试 Data 文件又会破坏资源签名。
最终使用未修改的原始应用及 [官方 Safe Mode](https://www.sublimetext.com/docs/safe_mode.html)，
运行时核验实际 Packages 路径为 `~/Library/Application Support/Sublime Text (Safe Mode)/Packages`。

可复现入口：

```sh
python3 tools/test_macos4215.py \
  --app '/实际路径/Sublime Text.app' \
  --package dist/PlainTasks.sublime-package \
  --libraries /实际路径/dateutil-and-six \
  --output validation
```

加 `--loose` 检查源码目录模式。脚本先备份已有 Safe Mode 数据，点击通知 OK 后继续；
如果没有自动报告，按脚本提供的一行 console bootstrap 处理。实际两次最终运行自动完成了 19 项检查。
不修改应用签名或系统安全设置。Safe Mode 下的配置下次启动会被官方程序清空。

## 交付边界

Windows 机器暂不能连接。交付 ZIP 已包含完整离线库、可恢复安装脚本、真实编辑器测试和中文说明。
仍需在 Windows 10 / PowerShell 5.1 跑自动检查，并验收原生快捷键、Save As、浏览器/协议处理器、
文件跳转、显示缩放和弹窗视觉、重启持久化。Package Control 自动安装库也未作为本次离线方案的验证结果。

按 [WINDOWS_4215.md](WINDOWS_4215.md) 先在新 portable 副本验收，再安装到实际数据目录。
不能将 Mac 的 API 验证、CI 的 windows-latest 或 macOS 上的 PowerShell 7 测试称为 Windows 10 实机通过。
