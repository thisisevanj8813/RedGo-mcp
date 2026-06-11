<div align="center">

# 🛩️ RedGo

**为 AI agent 而生的小红书数据采集 MCP server**

[![PyPI](https://img.shields.io/pypi/v/redgo-mcp)](https://pypi.org/project/redgo-mcp/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![MCP](https://img.shields.io/badge/protocol-MCP-8A2BE2)](https://modelcontextprotocol.io/)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)](#)

vibe coder 友好 ·  即插即用 ·  无需懂代码

</div>

---

**RedGo 专为 Claude Code、Codex、Cursor 这类 AI 工具设计。** 一条 config 贴进去，然后你就用大白话指挥你的 AI——「帮我搜小红书上关于露营的笔记」「看看这篇的评论都在说什么」——数据就回来了。**全程不用碰一行代码。**

如果你是那种"会用 AI 干活、但不想自己写代码"的人，RedGo 就是为你做的。市面上能查小红书的工具，要么你的 AI 根本调不动，要么返回一坨乱码还得有人写程序去解析。RedGo 把这些都处理好了：你的 AI 拿到的是干净、即用的数据，账号保护也默认开着。只读，四个工具，装好就能用。

```
┌──────────────┐  MCP    ┌────────┐         ┌────────┐
│ Claude Code  │ ──────▶ │        │ ──────▶ │        │
│ Codex        │  stdio  │ RedGo  │  真实    │ 小红书 │
│ Cursor       │ ──────▶ │        │  浏览器  │        │
└──────────────┘         └────────┘         └────────┘
        一条 config 接入             结构化 JSON · 抗封内建
```

## 能拿它来干嘛

RedGo 适合**个人、低频、给自己的 AI 喂料**的场景。下面几个例子帮你对号入座（每个都附一句可以直接照抄给 AI 说的话）：

**🛒 买东西前先做功课** —— 想买某样东西，让 AI 替你去小红书扒真实测评和避雷帖，帮你总结到底值不值得入。
> 帮我搜小红书上关于「某款扫地机器人」的笔记，正面和踩雷的各挑几条，帮我总结该不该买

**👀 快速摸一下某个品牌的风评** —— 想知道某品牌最近在小红书口碑如何，官方在发什么、用户在夸什么，随手扒一圈。
> 帮我看看小红书上大家最近怎么评价「某品牌」，正面负面各挑几条

**✨ 找对标博主** —— 想做某个垂类，让 AI 把这个领域做得好的博主和他们的内容扒出来给你参考。
> 帮我在小红书找几个做「家庭收纳」做得不错的博主，看看他们都发什么内容

**📝 写笔记前调研选题** —— 要发某个主题的笔记，先让 AI 看看这话题热不热、大家都从什么角度切入。
> 搜一下小红书上「city walk」相关的热门笔记，看看大家一般怎么写、什么角度容易火

**💼 营销/品牌人的随手调研助手** —— 如果你做数字营销或品牌，RedGo 可以当一个随手查的小口子：让 AI 帮你快速摸一下自己负责的品牌、或某个竞品最近在小红书的风评，省得自己一篇篇手动翻。
> 帮我快速看一下小红书上大家最近怎么聊「某竞品」，挑几条有代表性的评价

**🤖 给你的 AI 当数据源** —— 你在用 Claude / Cursor 捣鼓需要小红书数据的小工具或分析，RedGo 就是那个即插即用的数据接口——最贴它"为 agent 而生"的本意。
> （在你自己的项目里）让 agent 调 RedGo 拉一批笔记数据，喂给你的分析流程

## 为什么是 RedGo

### ① 一条 config，即插即用

```json
{
  "mcpServers": {
    "redgo": {
      "command": "uvx",
      "args": ["redgo-mcp"]
    }
  }
}
```

贴进 Claude Code 的 `.mcp.json`（Codex / Cursor 同理），agent 立刻多出 4 个小红书工具——`uvx` 会自动拉取，无需 clone、无需填路径。

### ② 数据干净，你的 AI 一看就懂

很多工具吐回来的是一坨原始乱码，你的 AI 还得费劲去猜「`1.2万` 到底是多少」。RedGo 把数据都整理好了：点赞数是干净的数字（`12000` 而不是 `"1.2万"`）、时间是标准格式、每条笔记都附好了后续查看详情/评论所需的信息。你的 AI 拿到就能直接用，回答又快又准。

<details>
<summary>给好奇的技术读者：返回结构长这样</summary>

```json
{
  "keyword": "咖啡",
  "has_more": true,
  "notes": [{
    "note_id": "65a1...",
    "xsec_token": "AB...",
    "title": "深圳喜欢的两家咖啡店☕️",
    "liked_count": 12000,
    "url": "https://www.xiaohongshu.com/explore/65a1...?xsec_token=..."
  }]
}
```

走 MCP `structuredContent` + output schema，数字归一化、时间 ISO 8601、错误也是结构化的，agent 零二次解析。
</details>

### ③ 账号保护，默认开着

你不用懂任何原理——RedGo 内建了一套账号保护机制，装好就在替你看着，把使用强度控制在安全范围、避开明显危险的用法。你只管正常用，它在后台帮你守着账号。

## 关于封号风险，说实话

在一堆宣称"永不封号"的工具里，RedGo 选择说实话：

- **这是"低量安全"，不是"高量隐身"。** 合规低量使用能把封号概率从"几乎必然"压到长期低风险；但量一上来，任何工具都救不了——量本身就是证据。
- **不保证不封号。** 平台策略动态调整，没人能打包票。遇到风控时 RedGo 会返回明确错误并建议冷却，而不是硬爬下去把账号跑挂。
- **建议用非主力账号**，并保持低频、合规使用。

## 上手：把安装交给你的 AI

你不用自己敲命令、不用读懂配置。**最简单的方式——把这个页面的链接发给你的 AI 工具（Claude Code / Cursor / Codex），对它说：**

> 帮我装上这个 MCP 工具：https://github.com/thisisevanj8813/RedGo-mcp

它会自己读下面的安装说明，把下载、配置全搞定。

**你本人只需要做一件事 👇**

### 🔑 扫码登录小红书（只有这步必须你亲自来）

AI 装好后会让你运行一下登录命令，然后弹出一个浏览器窗口——**像平时一样扫码登录你的小红书**（建议用非主力小号）。这是 AI 替不了你的唯一一步，因为只有你能登录自己的账号。

登录一次就长期记住。**登录后那个浏览器窗口别关，最小化就行。**

搞定后，在新对话里直接对 AI 说人话就能用了：

> 帮我在小红书搜「露营装备」，把最火的 5 篇标题和点赞数列给我

---

<details>
<summary>📋 给 AI 看的安装说明（你自己不用敲，AI 会照着做）</summary>

> 以下步骤供 AI 助手执行。普通用户无需手动操作——把本页链接交给 AI 即可。
> 已发布到 PyPI，用 [uv](https://docs.astral.sh/uv/) 的 `uvx` 免安装运行，无需 clone、无需填路径。

**1. 启动浏览器供用户登录**

```bash
uvx --from redgo-mcp redgo launch-chrome
```

运行后会打开一个浏览器窗口（若已有登录好的实例则直接复用、不重复弹窗，属正常）。**提示用户在此窗口扫码登录小红书**，登录态长期保存，窗口保持开启（最小化即可）。

**2. 写入 MCP 配置**：把下面这段加进用户 AI 工具的配置文件（如 Claude Code 的 `.mcp.json`）。Cursor、Codex 同理。

```json
{
  "mcpServers": {
    "redgo": {
      "command": "uvx",
      "args": ["redgo-mcp"]
    }
  }
}
```

**3. 提醒用户**：配置写入后需**新开一个对话**（MCP 工具在会话启动时加载），RedGo 的四个工具才会生效。

> 排查：运行 `uvx --from redgo-mcp redgo status` 可检查浏览器连接与登录状态。

</details>

<details>
<summary>🔧 想自己手动装？</summary>

**最简方式（推荐，需 [uv](https://docs.astral.sh/uv/)）**——不用 clone：

1. **登录**：`uvx --from redgo-mcp redgo launch-chrome`，在弹出的窗口里扫码登录小红书（非主力小号），窗口别关
2. **接入**：把上面那段 `uvx` 版 `.mcp.json` 配置贴进你的 AI 工具，然后**新开一个对话**
3. 随时 `uvx --from redgo-mcp redgo status` 看连接和登录状态

<br>

**从源码装（想改代码 / 本地开发时）**：

```bash
git clone https://github.com/thisisevanj8813/RedGo-mcp && cd RedGo-mcp
uv sync
uv run redgo launch-chrome   # 扫码登录
```

config 用本地路径版：`"command": "uv", "args": ["run", "--directory", "/path/to/RedGo-mcp", "redgo-mcp"]`

</details>

## 四个工具（你的 AI 会自动选用，了解即可）

你不用记这些——你说人话，AI 自己挑工具。这张表只是让你知道 RedGo 能干什么：

| 工具 | 作用 |
|---|---|
| `search_notes` | 按关键词搜笔记，拿到一批结果 |
| `get_note` | 看某一篇笔记的完整内容（正文、图片/视频、点赞收藏评论数、发布时间） |
| `get_comments` | 看某一篇笔记的评论 |
| `get_creator_notes` | 看某个博主发过的笔记 |

查看详情和评论需要先从搜索结果里拿到对应笔记——你的 AI 会自动串好这个顺序，你只管提需求。

**当前版本范围**：搜索、评论、博主笔记都返回第一页/首屏内容，够日常使用；更深的翻页留待后续版本。

## 配置（可选）

绝大多数人不用配任何东西，装好直接用。少数情况可以通过环境变量微调，例如换 Chrome 的连接地址、指定 Chrome 路径，或在你清楚风险时放宽账号保护的默认强度。完整可调项见仓库内代码注释——日常使用完全用不到。

## 常见问题

- **我不会写代码，能用吗？** 能。装好之后你只跟你的 AI 工具（Claude Code / Codex / Cursor）用大白话对话就行，不用碰任何代码。见上方「5 分钟上手」。
- **登录会过期吗？** 偶尔会。过期时工具会明确提示你去 RedGo 的 Chrome 窗口重新登录一下，绝不会偷偷返回空数据骗你。
- **Chrome 窗口能关吗？** 别关（它是数据通道），最小化没问题。万一手滑关了也不要紧，RedGo 会自动帮你开回来。
- **可以部署到服务器上跑吗？** 不可以。RedGo 设计为在你自己的电脑上运行，请勿部署到服务器或云主机。

## License

MIT © 2026 EJ

## 免责声明

仅供学习与个人合规使用。请遵守小红书用户协议与 robots 政策，尊重内容创作者权益，不要用于大规模采集或商业爬取。使用产生的一切后果由使用者自行承担。
