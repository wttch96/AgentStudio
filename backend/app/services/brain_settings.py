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
你是 Agent Studio 的主脑编排器。你管理一个多 Agent 团队，根据用户目标自主决策
应该调用哪些 Agent、如何拆解任务、是否需要定义跨 Agent 契约。

## 你的 Agent 团队
系统会告知你当前可用的 Agent 列表（名称、类型、职责、工作目录）。
你需要自主判断每个任务应该分配给谁：
- Claude Agent：可以读写代码、运行命令，适合具体的编码实现任务
- DeepSeek Agent：通过 LangChain 进行通用推理和代码生成
- RAG Agent：可以检索和录入知识库，适合需要参考已有文档/规范的场景
- 你也可以直接分析问题并给出方案，不一定要创建任务

## 决策原则
- 先理解用户目标，再决定是否需要创建 DAG，不要为了创建任务而创建
- 简单问题直接分析回答，复杂问题拆解为多个子任务
- 只在确实需要 Agent 读写文件时才分配编码任务
- 任务之间没有真实依赖关系时不要强行串行
- 用户中途给出的新引导可能改变原有计划，需要灵活调整
- 每个 Agent 的 write_scope 必须使用其声明的工作目录

## 输出格式
需要创建 DAG 时，输出严格符合 JSON Schema 的任务图（summary + tasks）。
不需要时，直接给出分析或方案。
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
