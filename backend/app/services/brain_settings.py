"""持久化 DeepSeek 主脑提示词。

页面只编辑主脑的任务理解、项目选择、契约设计和验收偏好。Agent 白名单、
JSON Schema 等运行安全约束仍由 planner 在请求时追加，避免误配置破坏控制协议。
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from app.domain.configuration import BrainConfiguration


DEFAULT_ORCHESTRATION_PROMPT = """
你是 Agent Studio 的主脑编排器。你的首要原则是**少即是多**——不要为简单问题创建复杂的任务规划。

## 任务分级（必须严格遵守）

### 第一级：直接回答（不创建任何任务）
以下情况你直接给出回复，**绝不创建 DAG，绝不调用任何 Agent**：
- 闲聊对话（"你好"、"你是谁"、"今天天气怎么样"）
- 概念性问题（"什么是 xxx"、"解释一下 xxx"）
- 你能直接从训练数据中回答的知识性问题
- 对已有执行结果的追问、澄清、分析或总结
- 用户让你分析/建议但不涉及读写文件的需求

**第一级输出格式：直接输出纯文本回复，不要输出 JSON**

### 第二级：单一 Agent 任务（只创建一个任务）
以下情况只创建一个 Agent 任务，**不要拉上其他 Agent**：
- 需要检索知识库 → 只创建 RAG Agent 任务
- 需要录入知识 → 只创建一个 RAG Agent 任务
- 需要读/写/搜索代码文件 → 只创建一个 Claude/DeepSeek/文件操作 Agent 任务
- 需要文件管理（复制/移动/删除/列出）→ 只创建一个文件操作 Agent 任务
- 用户明确指定了 Agent 名（如 "/agent xxx 做 yyy"）→ 只创建该 Agent 的任务

### 第三级：多 Agent DAG（创建多个有依赖的任务）
**仅当**以下条件全部满足时才创建多个任务：
1. 工作明显无法由单个 Agent 完成
2. 存在真实的跨 Agent 依赖或并行机会
3. 你已排除了第一级和第二级的可能性

## 你的 Agent 团队
- Claude Agent：读写代码、运行命令、文件操作
- DeepSeek Agent：通用推理和代码生成
- 文件操作 Agent：文件复制、移动、删除、列表、搜索 (FileManagementToolkit)
- RAG Agent：知识库检索和录入（search/get/add/list_knowledge）

## 决策流程（每次收到用户输入都按此顺序判断）
1. 这个请求我能直接回答吗？→ 能，直接输出纯文本（第一级）
2. 这个请求只需要一个 Agent 就能完成吗？→ 是，输出只有一个 task 的 JSON（第二级）
3. 确实需要多个 Agent 协作？→ 输出完整 DAG JSON（第三级），但只包含必要的 Agent

## 关键约束
- **绝对不要**为简单对话创建任务
- **绝对不要**把不需要的 Agent 拉进来
- RAG 优先：需要查资料时先用 RAG Agent，不要直接让编码 Agent 扫盘
- 知识库中 [manual] 和 [import] 来源的信息可信度高于 [auto]
""".strip()


class BrainSettings:
    def __init__(self, store=None, defaults_path: Path | None = None,
                 config_path: Path | None = None) -> None:
        self.store = store
        self.config_path = config_path
        self.defaults_path = defaults_path
        self.defaults = self._load_defaults()
        self._lock = RLock()

    def _load_defaults(self) -> BrainConfiguration:
        """优先加载版本库模板；模板缺失或损坏时使用代码内置的安全兜底。"""

        if self.defaults_path and self.defaults_path.is_file():
            try:
                return BrainConfiguration.model_validate_json(
                    self.defaults_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        return BrainConfiguration(
            orchestration_prompt=DEFAULT_ORCHESTRATION_PROMPT,
        )

    def current(self) -> BrainConfiguration:
        with self._lock:
            # 自动迁移：首次调用时从旧 JSON 文件迁移到 SQLite
            if self.store and self.config_path and self.config_path.exists():
                self.store.migrate_config_from_file("brain", str(self.config_path))
            if self.store:
                data = self.store.get_config("brain")
                if data:
                    return BrainConfiguration.model_validate(data)
            if self.config_path and self.config_path.exists():
                try:
                    payload = json.loads(self.config_path.read_text(encoding="utf-8"))
                    return BrainConfiguration.model_validate(payload)
                except (OSError, ValueError, json.JSONDecodeError):
                    pass
            return self.defaults.model_copy()

    def default(self) -> BrainConfiguration:
        """返回版本库模板的副本，供配置页面显式恢复默认值。"""

        return self.defaults.model_copy()

    def update(self, configuration: BrainConfiguration) -> BrainConfiguration:
        with self._lock:
            if self.store:
                self.store.set_config("brain", configuration.model_dump())
            elif self.config_path:
                self.config_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.config_path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(configuration.model_dump(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(self.config_path)
        return configuration.model_copy()
