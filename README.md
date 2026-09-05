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
.\.venv\Scripts\python.exe -m ai_governor.cli overlay
```

复制 `.env.example` 为 `.env` 后，需要由启动环境注入变量；程序不会自动读取 `.env` 文件，避免把秘密加载行为藏在代码里。

## Windows 浮动辅助窗口

运行 `overlay` 会打开一个始终置顶、跟随《满庭芳》客户区移动的辅助窗口。按 `Home` 可以全局显示或隐藏窗口，即使当前焦点在游戏内也有效。

点击“设置 DeepSeek”后可以填写并保存 API Base、API Key、视觉模型和推理模型。配置保存在当前 Windows 用户的 `%LOCALAPPDATA%\MantingfangAIGovernor\settings.json`，不会写入仓库或 Git；环境变量仍然可以覆盖保存值。

浮窗中的“启动 AI 托管”默认使用 `dry-run`，不会发送真实鼠标键盘输入。托管子进程日志保存在 `data\overlay.log`。

## 当前边界

- AI provider 只有 DeepSeek；没有 GPT、Claude、Qwen 或隐式备用模型。
- 视觉默认按 `resources`、`map`、`events`、`build_menu`、`dialog` 区域工作；复杂画面先定位再放大。
- 数字状态可以通过 `memory-read` 接入显式的 Windows 只读内存 profile；地址必须由用户针对具体游戏版本校准，程序不猜地址、不做大范围扫描、不写进程内存。
- 日报通过 `获取日报` 等命令按需生成；现在包含中国本地日界动作数、状态变化、动作摘要、瓶颈、下一目标和 DeepSeek Token 用量；重大事件通过 Feishu gateway 主动发送。
- 动作具有风险等级、幂等键、审计记录、暂停/恢复和恢复确认门槛。
- `GOVERNOR_EXECUTION_MODE=live` 仍需要 `GOVERNOR_ALLOW_LIVE_INPUT=true`、运行时 `live_armed=true` 和语义验证器三重条件；默认 dry-run，不会自动开启真实输入。

## 目录

```text
src/ai_governor/
  actions.py       风险门、dry-run 执行器、动作队列
  cli.py           本地控制命令
  config.py        环境配置
  deepseek.py      唯一 AI provider 适配器
  feishu.py        双向命令/主动通知边界
  feishu_http.py   飞书自建应用 token、消息和事件 payload Transport
  memory.py        Windows 只读内存采样与 profile 校验
  state.py         内存/视觉观测合并与字段来源追踪
  window.py        Steam 窗口查找、客户区和归一化坐标
  capture.py       Windows 客户区截图与标准 PNG 编码
  input.py         策略门控的 dry-run/SendInput 适配器
  skills.py        PlannedAction 到输入技能的受限转换器
  skills.py        PlannedAction 到输入技能的受限转换器
  verification.py  动作后的窗口/截图验证
  loop.py           变化检测、心跳和恢复态长运行循环
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
py -3 -m ai_governor.cli memory-modules --process-name Song.exe
py -3 -m ai_governor.cli memory-read --profile profiles/songhua.memory.example.json
py -3 -m ai_governor.cli window-info
py -3 -m ai_governor.cli capture --out screenshots/current.png
```

示例 profile 只用于验证配置格式，不能读取真实游戏；`memory-read` 只在你提供了真实、经过校准的 profile 后才有意义。当前仓库不包含猜测性的游戏地址。

`memory-modules` 只用于列出目标进程的已加载模块，帮助建立版本校准证据。Windows 可能因进程完整性级别或权限返回访问拒绝；此时工具会失败并报告错误，不会降级为任意内存扫描。

`StateAggregator` 将 `readonly-memory` 作为数字字段的高优先级来源，将 DeepSeek 区域视觉作为补充来源；同一字段不一致时保留内存优先结果，同时在 `conflicts` 中记录两份证据，供策略层决定是否暂停。

Governor 发给 DeepSeek Chat Completions 的用户上下文会序列化为 UTF-8 JSON 文本；这样既保留结构化状态，又符合 Chat API 对 `messages[].content` 的类型要求。视觉请求仍使用文本与 `image_url` content-parts。

`window-info` 只检查窗口和客户区，不会激活、点击或输入游戏。

`capture` 读取窗口客户区并保存 PNG；窗口不存在、最小化或 GDI 捕获失败时会返回错误，不会伪造截图。实机视觉路径应将 `CapturedFrame.rgba` 传给 `PerceptionEngine.observe_rgba()`，由程序先裁剪 ROI，再调用 DeepSeek。

Windows 客户区截图默认只使用 `SRCCOPY`，不会把 `CAPTUREBLT` 加入正常 Governor/E2E 路径。命令输出还包含 HWND、客户区尺寸、后端、光栅模式和近黑帧诊断；近黑帧会标记为 `CAPTURE_BLACK_FRAME`，不会自动退回到 `CAPTUREBLT`。

只读真实 Steam 预检可以等待用户自行把游戏置于前台；程序不抢焦点、不发送输入：

```powershell
py -3 -m ai_governor.cli e2e-preflight --wait-for-game-foreground
```

该命令最多等待 30 秒，并要求 `Song` 连续保持前台 3 秒，随后自动保存 `data/e2e/preflight.png` 和 `data/e2e/preflight_vision.json`，检查 `build_menu` 与 `dialog` 视觉结构。真实 Live E2E 仍需显式 `arm-live` 和 `--confirm-live-e2e`。

`WindowsSendInputAdapter` 默认关闭；Task 4 只提供能力和策略边界，未将 live click/keyboard 接入 Governor。校准阶段使用 `DryRunInputAdapter`，不会向系统发送输入。

动作引擎可以注入 `ScreenshotVerifier`。验证要求窗口仍存在、客户区未最小化且能够重新捕获 PNG；验证异常会把动作标记为 `uncertain` 并触发恢复态。需要人工决策的重大事件会先持久化并暂停 Watchdog，再发送飞书通知。

动作幂等默认按 `plan_id + action_type + payload` 作用域计算，因此周期性资源检查可以在新计划中再次执行；只有显式提供 `idempotency_key` 的不可重复动作才跨计划永久去重。

`GovernorLoop` 每轮读取观测，按稳定数据指纹跳过无变化画面，调用 Governor 处理变化，并在观测源连续失败达到阈值时暂停并进入恢复态。它是编排组件，不会自行启动游戏或启用 live 输入。

`CompositeObservationSource` 可以在同一轮合并内存和多区域视觉观测；`InputActionExecutor` 只接受白名单输入技能，并可在动作前后采集状态交给 `SemanticStateVerifier`。截图可用性验证不再被视为 live 动作成功的充分条件。

DeepSeek 客户端对网络超时、408、429 和 5xx 使用指数退避重试，并将返回的 prompt/completion/total tokens 记录到 SQLite；失败次数耗尽后仍会明确进入恢复路径。

运行入口为 `run`：它会连接配置的 Steam 窗口、采集多区域视觉并可选读取显式内存 profile。`run` 默认继承 `GOVERNOR_EXECUTION_MODE=dry-run`；live 模式还必须先执行 `arm-live`，且每个动作需要语义状态验证。使用 `disarm-live` 可立即撤销运行时 arm 状态。加 `--supervise` 后，只有未捕获异常才会按上限重启；安全暂停或 `recovery_required` 不会被自动清除。

`CompositeObservationSource` 可以在同一轮合并内存和多区域视觉观测；`InputActionExecutor` 只接受白名单输入技能，并可在动作前后采集状态交给 `SemanticStateVerifier`。截图可用性验证不再被视为 live 动作成功的充分条件。

飞书正式接入使用 `FeishuApiClient` + `FeishuHttpTransport`：凭据来自环境变量，token 只缓存在进程内，事件处理支持 URL challenge、文本命令、签名校验和 Encrypt Key 解密。`feishu-server` 提供本机常驻 Callback Server，默认监听 `127.0.0.1:8787`；需要公网回调时必须由用户自行配置安全的反向代理或隧道。加密回调需要安装可选依赖 `cryptography`。
