# 《满庭芳：宋上繁华》AI Governor

这是一个面向 Steam Windows 版的本地自动经营基础工程，目标来自“满庭芳自动经营分析”方案：程序负责观察、持久化、执行和恢复，DeepSeek 负责视觉/战略推理，飞书自建应用负责双向远程控制。

当前版本是安全的 foundation scaffold：默认 `dry-run`，不会移动鼠标、输入键盘，也不会假装已经连接 Steam 或飞书。接入真实游戏前，需要完成窗口截图适配、游戏 UI 校准、执行后验证，以及用户自己的 DeepSeek/飞书凭据配置。

## 快速开始

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ai_governor.cli init
.\.venv\Scripts\python.exe -m ai_governor.cli status
.\.venv\Scripts\python.exe -m ai_governor.cli command 获取日报
```

复制 `.env.example` 为 `.env` 后，需要由启动环境注入变量；程序不会自动读取 `.env` 文件，避免把秘密加载行为藏在代码里。

## 当前边界

- AI provider 只有 DeepSeek；没有 GPT、Claude、Qwen 或隐式备用模型。
- 视觉默认按 `resources`、`map`、`events`、`build_menu`、`dialog` 区域工作；复杂画面先定位再放大。
- 数字状态可以通过 `memory-read` 接入显式的 Windows 只读内存 profile；地址必须由用户针对具体游戏版本校准，程序不猜地址、不做大范围扫描、不写进程内存。
- 日报通过 `获取日报` 等命令按需生成；重大事件通过 Feishu gateway 主动发送。
- 动作具有风险等级、幂等键、审计记录、暂停/恢复和恢复确认门槛。
- `GOVERNOR_EXECUTION_MODE=live` 当前仍会被明确阻断；只有完成真实窗口适配与执行后验证后才能开放。

## 目录

```text
src/ai_governor/
  actions.py       风险门、dry-run 执行器、动作队列
  cli.py           本地控制命令
  config.py        环境配置
  deepseek.py      唯一 AI provider 适配器
  feishu.py        双向命令/主动通知边界
  memory.py        Windows 只读内存采样与 profile 校验
  window.py        Steam 窗口查找、客户区和归一化坐标
  capture.py       Windows 客户区截图与标准 PNG 编码
  models.py        状态、目标、动作、事件模型
  perception.py    区域化视觉接口
  reporting.py     状态/日报
  storage.py       SQLite 状态与审计
  watchdog.py      暂停、恢复、心跳
tests/             安全关键路径测试
profiles/          用户维护的只读内存 profile 说明
```

## 只读内存诊断

```powershell
$env:PYTHONPATH = "src"
py -3 -m ai_governor.cli memory-processes
py -3 -m ai_governor.cli memory-read --profile profiles/songhua.memory.example.json
py -3 -m ai_governor.cli window-info
py -3 -m ai_governor.cli capture --out screenshots/current.png
```

示例 profile 只用于验证配置格式，不能读取真实游戏；`memory-read` 只在你提供了真实、经过校准的 profile 后才有意义。当前仓库不包含猜测性的游戏地址。

`window-info` 只检查窗口和客户区，不会激活、点击或输入游戏。

`capture` 读取窗口客户区并保存 PNG；窗口不存在、最小化或 GDI 捕获失败时会返回错误，不会伪造截图。实机视觉路径应将 `CapturedFrame.rgba` 传给 `PerceptionEngine.observe_rgba()`，由程序先裁剪 ROI，再调用 DeepSeek。
