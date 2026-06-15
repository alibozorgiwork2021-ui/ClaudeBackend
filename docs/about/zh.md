# ClaudeBackend —— 它是什么，以及你为什么会用它

[English](en.md) · [فارسی](fa.md) · [日本語](ja.md) · **中文** · [Русский](ru.md) · [Français](fr.md) · [Deutsch](de.md)

> 一个通用的、多智能体的**后端开发系统**：给它一个代码仓库和一个用自然语言写下的
> 目标，它就会在一个可供审查的 git 分支上把这个改动实现出来——具备依赖感知、经过
> 验证，而且从不触碰你的工作区。

## ClaudeBackend 是什么？

ClaudeBackend 是一个命令行智能体，它接受一个代码仓库，外加一个用自然语言写下的
任意目标——比如“添加 JWT 认证”“重构 SQLAlchemy 模型”“添加一个 `/health`
端点”，甚至“把这个从 Python 2 迁移到 3”——然后把它实现出来。它由一个大语言模型
驱动（默认使用 Claude Opus 4.8，拥有 1M token 的上下文窗口），并封装在一条
**确定性的、相互隔离的三智能体流水线**中：一个 **Planner** 决定要创建、修改或
删除哪些文件；一个 **Coder** 实现每个步骤；一个 **Verifier** 作为安全网，运行语法
检查、`ruff` 以及项目自带的 `pytest` 测试套件（最多重试 3 次）。模型负责实际的
编码；外围程序则决定*改什么*、*以什么顺序*改，并*检查结果*。产出会写入一个
**全新的 git 分支**——你的工作区和当前分支始终不会被改动。

## 它解决的问题

真实的后端工作很少能装进一个文件里。添加一个端点、替换一套认证方案、重塑一个数据
模型，或是现代化一个遗留代码库，都会波及多个模块、ORM 模型、配置和测试。手工去做
既慢又容易出错；交给一个朴素的代码助手又有风险，因为助手一次只编辑一个文件，看不
出某处的改动会如何在另一处造成破坏。

真正危险的 bug，恰恰是那些跨越文件边界的：

> 某个辅助函数返回 `d.keys()`。在 Python 2 中它是一个 `list`，所以另一个模块
> 可以安全地写 `keys()[0]`。而在 Python 3 中，`keys()` 是一个*视图*——`keys()[0]`
> 会抛出 `TypeError`。一个纯局部的工具会“修复”这两个文件，却让代码库处于损坏状态，
> 因为这个 bug 只有当你把这两个文件*放在一起*看时才会暴露出来。同样的陷阱潜藏在
> 数不清的后端改动里——改一个模型字段名，每一处用到它的查询和序列化器都可能悄无
> 声息地崩掉。

## ClaudeBackend 的不同之处

| | 朴素的代码助手 | 静态检查工具（如 SonarQube） | ClaudeBackend |
|---|---|---|---|
| 实现一个改动（不只是编辑/报告） | 一次一个文件 | 只读 | 端到端、贯穿整个仓库 |
| 跨文件 / 依赖感知的修复 | 否 | 否 | 是——映射 import、ORM、配置 |
| 标记有歧义 / 有风险的选择 | 否 | 否 | 是（`CLAUDEBACKEND-REVIEW`） |
| 输出 | 原地修改 | 一份报告 | 一个可审查的 git 分支 + 摘要 |

核心思路是：ClaudeBackend 会为你的代码构建一张**依赖图**——它不仅映射 Python 的
import，*还*映射 ORM 模型（Django / SQLAlchemy）、Dockerfile 和配置文件——并把这份
真实的上下文交给 Planner。在一个超大的上下文窗口中，每个文件*连同它的依赖*一起被
展示给模型。这正是它能够实现跨文件波及的改动、而不是像纯局部工具那样产出逐文件的
破损编辑的原因。

## 谁需要它

- **要交付后端功能的团队**——他们想要一个可审查的分支，而不是一次黑盒式的批量编辑。
- 正在现代化服务、重塑数据模型，或在众多文件间偿还技术债的**维护者**。
- 承接大规模重构或迁移工作的**顾问与外包人员**——他们想要一份可审查的 diff，而不是
  一个黑盒。
- **任何人**，只要手头有一个遗留代码库——包括一个“仍能用”、却在现代机器上再也装不上
  的 Python 2 工具——需要一次谨慎的、具备依赖感知的更新。

## 核心特性

- **依赖感知的跨文件开发**——招牌能力：它映射 import、ORM 模型、Dockerfile 和配置，
  让 Planner 看到真实的上下文。
- **三智能体流水线**——Planner、Coder 和 Verifier 作为相互隔离的确定性阶段运行，
  使每一个目标都遵循同一条有纪律的路径。
- **诚实、分层的验证**——先是逐文件的语法关卡，然后是项目级的整体检查（编译 +
  `ruff` + 你自己的 `pytest` 测试套件，前提是它能被收集到），并以最多 3 次重试作为
  安全网。
- **设计上即安全**——它会拒绝在脏工作区上运行，只写入一个新分支
  （`claudebackend/feature-<timestamp>`），并提供 `--dry-run` 模式（智能体的默认
  模式），该模式什么也不写。
- **标记它不确定的地方**——有歧义或涉及安全的改动会被实现，*同时*用
  `CLAUDEBACKEND-REVIEW` 注释标记出来，供人工确认。
- **使用你自己的 LLM**——默认使用 Claude；也支持其他兼容 OpenAI 的提供商
  （OpenRouter、OpenAI、NVIDIA、DeepSeek 和 Gemini）。
- **从你的工具里调用它**——它以 MCP server、Agent Skill 以及 Claude Code plugin 的
  形式发布，因此 Cursor、Codex、Google Antigravity 以及 Claude Code/Desktop 都能
  调用它。

## 它是如何工作的（概览）

1. **建图（Graph）**——映射仓库的依赖关系：Python 的 import（借助标准库 `tokenize`，
   因此连 `ast` 拒绝的 Python 2 源码也能解析）、ORM 模型（Django / SQLAlchemy）、
   Dockerfile 和配置文件。import 循环会被折叠成单个单元。
2. **规划（Plan）**——Planner 把你的目标落实为一份要创建、修改或删除的文件的具体
   清单，并标注每个文件的风险和注记。
3. **开发（Develop）**——对每个步骤，Coder 构建上下文（该文件加上它的依赖，并启用
   prompt 缓存），流式生成改动，做语法检查，并在失败时重试。
4. **验证（Verify）**——一次项目级的编译 + lint + 测试检查：真正的跨文件关卡
   （最多重试 3 次）。
5. **提交（Commit）**——创建分支，按模块提交，并写出一份 `DEV_SUMMARY.md` 以及一份
   交互式的拓扑图 `DEV_GRAPH.md`。

## 对自身局限的坦诚

这些静态检查是一张**安全网，而非正确性证明**。语法检查和 `ruff` 能捕捉一类错误——
但那些保持行为不变却又有歧义的选择，是由模型决定并*标记*给你的，而不是被证明为
正确。最可靠的保证，是改动之后你**自己的测试套件能够通过**。ClaudeBackend 的目标
是让这一审查过程快速而诚实，而不是假装后端工作可以被完全自动化。

## 快速上手

```bash
# 1. 安装（按操作系统提供的引导脚本——参见安装指南）：
#    Windows: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#    macOS:   ./scripts/setup-macos.sh
#    Linux:   ./scripts/setup-linux.sh

# 2. 进行认证（例如使用 Anthropic API key），并先预览这次工作：
export ANTHROPIC_API_KEY=...
claudebackend develop path/to/repo "Add a /health endpoint" --dry-run  # 什么也不写
```

**了解更多：** [项目 README](../../README.md) ·
[LLM 后端](../providers.md) · [IDE / 智能体集成](../integrations.md)
· 安装指南：[Windows](../install/windows.md)、
[macOS](../install/macos.md) 和 [Linux](../install/linux.md)。
