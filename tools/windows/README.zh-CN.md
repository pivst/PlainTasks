# PlainTasks：Windows 10 / Sublime Text 4215 交付包

先将整个 ZIP 解压到一个目录，保留 `windows`、`smoke`、`lib` 和 `manifest.json`。
无需安装 Python 或管理员权限；使用 Windows 10 自带的 Windows PowerShell 5.1。
交付包包含 PlainTasks、离线 dateutil/six 库、自动测试及安装/恢复脚本，不包含 Sublime Text 或许可证。

## 先测试

从 [Sublime 官方下载页](https://www.sublimetext.com/download) 获取 build 4215 x64 portable ZIP。
[固定版本下载](https://download.sublimetext.com/sublime_text_build_4215_x64.zip)。
在交付包解压目录打开 PowerShell，执行（测试目录必须尚不存在）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Test-PlainTasks4215.ps1 -PortableZip "$env:USERPROFILE\Downloads\sublime_text_build_4215_x64.zip" -WorkRoot "$env:USERPROFILE\Desktop\PlainTasks 验收 4215" -KeepOpen
$LASTEXITCODE
```

脚本建立独立 portable 副本，只向副本的 `Data` 目录写入包和测试配置；返回 `0` 表示自动测试通过，`1` 表示失败。
目录里保存 `smoke-result.json`、HTML 示例、`environment.json` 和 `debug.*.log`。
`-KeepOpen` 保留测试窗口，便于完成 [WINDOWS_4215.md](WINDOWS_4215.md) 中的原生快捷键、保存窗口、浏览器、弹窗验收。
已有 4215 解压目录时，将 `-PortableZip ...` 改成 `-PortablePath 'C:\路径\Sublime 4215'`；该目录只作为复制来源，其 `Data` 不会被复制或修改。

## 安装与恢复

验收通过后关闭 Sublime。Portable 安装：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-PlainTasks.ps1 -PortablePath 'C:\Tools\Sublime 4215'
```

正式安装：先用 Sublime 的 **Preferences → Browse Packages** 确定数据目录。通常为 `%APPDATA%\Sublime Text`；如果继续使用旧的 `Sublime Text 3` 数据目录，以实际路径为准。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Install-PlainTasks.ps1 -DataPath "$env:APPDATA\Sublime Text"
```

有旧版 PlainTasks 或不同依赖库时，脚本先停止并列出冲突路径。检查后，在同一命令末尾加 `-BackupExisting`；旧文件移到数据目录的 `PlainTasks Backups`，输出完整恢复日志路径。个人 `Packages\User` 设置、快捷键和任务文件保留。
重启 Sublime 后检查功能；可用以下命令回滚（先关闭 Sublime）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows\Restore-PlainTasks.ps1 -JournalPath 'C:\实际路径\PlainTasks Backups\时间戳\restore.json'
```

详细目录、冲突处理、验收标准及本机测试边界见 [WINDOWS_4215.md](WINDOWS_4215.md)。
