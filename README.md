# MewCode

MewCode 是一个最小可用的命令行 AI 助手对话壳。当前版本只支持纯对话：不会运行工具、读取或写入项目文件、编辑代码，也不会执行 shell 命令。

## 安装

```powershell
python -m pip install -e .[dev]
```

## 配置

创建用户配置目录，并复制示例配置：

```powershell
New-Item -ItemType Directory -Force "$HOME\.mewcode"
Copy-Item .\examples\config.yaml "$HOME\.mewcode\config.yaml"
```

运行 MewCode 前，请先通过环境变量设置 API key。配置文件只保存 `env:OPENAI_API_KEY` 这类引用，不保存真实密钥。

编辑 `~/.mewcode/config.yaml`，把 `active` 设置为要使用的 profile：

```yaml
active: openai-main
profiles:
  - name: openai-main
    protocol: openai
    model: gpt-5.6
    base_url: https://api.openai.com/v1
    api_key: env:OPENAI_API_KEY
    thinking: false
```

## 运行

```powershell
mewcode
```

也可以使用：

```powershell
python -m mewcode
```

进入 REPL 后，输入 `/exit` 或 `/quit` 退出。对话历史只保存在当前进程内，程序退出后不会保存。
