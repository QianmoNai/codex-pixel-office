# Codex Pixel Office 版本声明

## 当前版本

| 项目 | 声明 |
|---|---|
| 产品版本 | `v1.2.2` |
| 发布阶段 | Release / 源码发布 |
| 声明日期 | 2026-09-26 |
| 默认分支 | `main` |
| 版本规范 | [Semantic Versioning 2.0.0](https://semver.org/lang/zh-CN/) |

`v1.2.2` 在既有 `v1.1.0` 标签基础上增加“叫人来加班”新会话启动、聊天中断控制，并优化会话轮询和聊天超时处理。此前版本已增加 Windows 原生 WebView2 桌面外壳、PowerShell/CMD 启动与开始菜单安装、`codex.exe` / `codex.cmd` 解析，以及 Windows 子进程树清理。Linux GTK 桌面端和零第三方依赖的浏览器模式继续保留；对外接口与 Codex 内部状态格式仍可能变化，升级 Codex 后请确认兼容性。

> [!NOTE]
> `server.py` 中 HTTP `Server` 响应头使用的产品标识，以及 Desktop Entry 中的 `Version=1.0` 字段，不代表应用的语义化版本；本文件中的 `v1.2.2` 才是当前产品版本声明。

## 本版本包含

- 自动读取最近活跃且未归档的 Codex 主会话和子代理。
- 将真实活动收敛为 `working`、`thinking`、`tool`、`waiting` 和 `idle` 五类状态。
- 状态驱动的像素员工动作、连续移动、自由活动和事件反馈。
- 主会话与子代理的差异化工位，以及父子关系展示。
- 常驻会议厅的老板 NPC、办公室缩放、平移、筛选和昼夜模式。
- 通过本机 `codex exec resume` 继续选中的原会话。
- 按会话选择 Codex 模型，并流式展示经过过滤的公开活动摘要。
- “叫人来加班”新会话启动与聊天中断控制。
- 会话轮询与聊天超时处理优化。
- Linux GTK4 / WebKitGTK 6 桌面窗口与 Windows pywebview / WebView2 桌面窗口。
- Linux XDG 与 Windows 开始菜单安装入口，以及两端的浏览器运行脚本。
- Windows `codex.exe` / `codex.cmd` 解析、隐藏控制台启动和超时后的进程树清理。
- 针对会话解析、HTTP 安全边界、聊天生命周期和 Linux/Windows 桌面启动协议的自动化测试。

## 支持范围

| 组件 | 当前支持范围 |
|---|---|
| Python | 3.11 或更高版本（使用标准库 `tomllib`） |
| Codex 数据 | 包含 `state_5.sqlite` 和 rollout JSONL 的本机 `CODEX_HOME` |
| Codex 聊天 | 支持 `codex exec resume --json` 的已安装、已登录 Codex CLI |
| Linux 桌面模式 | Linux 图形环境；PyGObject、GTK4、WebKitGTK 6 |
| Windows 桌面模式 | Windows 10/11；.NET Framework 4.6.2+、pywebview 6.2.1、Microsoft Edge WebView2 Runtime |
| 浏览器模式 | 现代浏览器；状态服务仅需 Python 标准库 |
| 默认网络边界 | `127.0.0.1` 回环地址 |

本项目没有声明对所有 Codex CLI 历史版本、所有 Linux 发行版、所有 Windows 版本或所有 Python / WebView2 组合提供兼容保证。

## 稳定性与已知限制

1. **Codex 状态格式并非稳定公共 API。** 项目读取 `state_5.sqlite` 和 rollout JSONL；上游结构变化可能需要更新解析层。
2. **内部接口可能调整。** 本地 HTTP 接口、JSON 字段和前端本地存储格式不是稳定的公共扩展接口。
3. **Windows 桌面依赖 WebView2。** 应用会校验 .NET、系统安装的 WebView2 最低版本和最终渲染器，并拒绝回退到已弃用、无法运行当前前端语法的 MSHTML；缺少 Runtime 时需要用户从 Microsoft 安装 Evergreen Runtime。Fixed Runtime 的版本由用户保证，目录必须位于本地磁盘，并可能需要额外的 AppContainer 文件权限。
4. **聊天能力依赖本机 Codex 环境。** 登录、模型目录、工具权限、审批策略和沙箱均由原 Codex CLI 配置决定。
5. **这不是多用户远程控制面板。** 即使状态页面被手动绑定到局域网地址，聊天和模型接口仍限制为本机回环客户端。
6. **当前没有公开许可证。** 仓库尚未包含 `LICENSE` 文件，对外分发前需要由维护者明确授权方式。
7. **当前未提供签名的 Windows 安装包。** Windows 入口直接从源码运行，开始菜单快捷方式会引用当前仓库的绝对路径。

## 版本编号规则

项目采用语义化版本 `MAJOR.MINOR.PATCH`：

- `PATCH`：向后兼容的问题修复、文档修订、安全加固和小型视觉调整。
- `MINOR`：向后兼容的新功能、新动作、新界面能力或新增运行方式。
- `MAJOR`：稳定版本阶段的破坏性配置、接口、数据格式或运行要求变化。

在 `0.x` 技术预览阶段，较大的兼容性变化可能发生在 `MINOR` 版本升级中；每次发布都应在发布说明中明确迁移影响。

## 发布约定

后续正式发布建议同时完成以下项目：

1. 更新本文件与 README 中的版本号和发布日期。
2. 在 Linux 与 Windows 分别运行完整测试并确认全部通过。
3. 检查 Linux GTK、Windows WebView2 和浏览器模式的最小启动流程。
4. 为发布提交创建 `vX.Y.Z` 格式的 Git 标签。
5. 在发布说明中记录新增功能、修复、兼容性变化和安全注意事项。

## 隐私与安全承诺

- 状态数据库以只读方式打开。
- 默认服务仅监听本机回环地址。
- 聊天和模型接口只接受本机客户端。
- UI 不展示隐藏推理、完整命令或工具参数。
- 项目不会主动绕过 Codex 的审批、沙箱或工具权限设置。

如安全边界发生变化，应至少提升 `MINOR` 版本，并在版本说明和 README 中显著标注。

## 品牌声明

Codex Pixel Office 是独立开发的第三方工具，不是 OpenAI 官方产品，也不代表 OpenAI 的认可或背书。Codex、OpenAI 及相关标识归其各自权利人所有。
