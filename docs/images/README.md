# README 截图准备说明

建议使用相同浏览器窗口尺寸截取 PNG，推荐 `1600 × 1000` 或其他 16:10 比例。深色界面无需额外加边框。

README 当前使用以下图片：

| 文件名 | 建议画面 |
| --- | --- |
| `workspace-overview.png` | 左右栏均打开；中间显示包含两个以上并行 Agent 的时间线；右侧至少一个 Agent 正在工作 |
| `configuration-center.png` | 配置中心的 Agent 或调度配置页面，能够看到 Agent、Skill、工作目录或最大轮次等配置能力 |
| `slash-commands.png` | 聊天框输入 `/` 后展开 Agent 命令菜单 |
| `task-continuation.png` | 一个第二轮或更后续的任务，显示“正在延续第 N 轮”和“查看上游”入口 |

截图前请注意：

- 不要打开或展示 `.env`、API Key、Token 等敏感内容。
- 如余额不希望公开，请对具体数字打码，保留“账户余额”和“本地统计”结构即可。
- 工作目录可能包含用户名或私人项目名，可在配置中心截图前切换到示例目录或打码。
- 建议使用真实但不敏感的任务标题，避免全部使用“测试任务”。

根目录 `README.md` 的“界面截图”部分按下面方式引用：

```markdown
![Agent Studio 工作台总览](docs/images/workspace-overview.png)
![页面配置中心](docs/images/configuration-center.png)
![斜杠命令菜单](docs/images/slash-commands.png)
![连续任务上下文](docs/images/task-continuation.png)
```
