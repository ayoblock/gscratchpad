# 打包脱敏校验（打包规范，R23 起）
# 用法：pwsh scripts/verify_apk_sanitize.ps1 <apk 路径> [更多 apk 路径...]
# 校验 release APK 内不含：测试用文档、测试用 WebDAV 地址/账号、千文件测试目录名等测试痕迹。
# 结构检查：不得存在 golden/ 语料资产（仅 debug 包允许）。
# 文本检查跳过 assets/vendor/**（三方库，数字表易撞 "123456" 等数字标记，且不含本工程测试数据）。
# 命中任一检查即 FAIL，退出码 1。
param(
    [Parameter(Mandatory = $true, ValueFromRemainingArguments = $true)]
    [string[]]$ApkPaths
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression.FileSystem

# 文本标记：测试 WebDAV（内网地址/端口/账号/口令）、测试文档名与正文特征、测试目录名。
# 123456 用数字边界防误报（如断电测试常量 "0123456789"、三方库数字表）。
$markers = @(
    '10\.42\.239\.39',                          # 测试 Alist 主机
    ':5244',                                    # 测试 Alist 端口
    '(?<![0-9a-zA-Z])123456(?![0-9])',          # 测试口令（带边界）
    'dav/backups',                              # 测试 WebDAV 路径
    'chatgpt-qichen',                           # 真机测试文档
    '奇琴伊察',                                 # 测试文档正文
    'big-sample',                               # 生成语料名
    'saf1000',                                  # SAF 千文件测试目录
    '郑居敬'                                    # 真机测试文档
)

$fail = $false
foreach ($apk in $ApkPaths) {
    if (-not (Test-Path -LiteralPath $apk)) { Write-Error "找不到 APK：$apk" }
    $zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path -LiteralPath $apk).Path)
    try {
        $hits = @()
        # 结构检查：golden 语料资产不得进 release
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -match '(^|/)golden/') {
                $hits += "$($entry.FullName)  结构命中：golden 语料资产进入 release"
            }
        }
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -match '^assets/vendor/') { continue }
            $stream = $entry.Open()
            try {
                $ms = New-Object System.IO.MemoryStream
                $stream.CopyTo($ms)
                $bytes = $ms.ToArray()
            } finally { $stream.Dispose(); $ms.Dispose() }
            if ($bytes.Length -eq 0) { continue }
            $text = [System.Text.Encoding]::UTF8.GetString($bytes)
            foreach ($m in $markers) {
                if ($text -match $m) {
                    $hits += "$($entry.FullName)  文本命中标记  $m"
                }
            }
        }
        $name = Split-Path $apk -Leaf
        if ($hits.Count -gt 0) {
            $fail = $true
            Write-Output "[$name] FAIL（$($hits.Count) 处命中）"
            $hits | Select-Object -First 20 | ForEach-Object { Write-Output "    $_" }
        } else {
            Write-Output "[$name] PASS（$($zip.Entries.Count) 个条目，无测试痕迹）"
        }
    } finally { $zip.Dispose() }
}
if ($fail) { exit 1 } else { exit 0 }
