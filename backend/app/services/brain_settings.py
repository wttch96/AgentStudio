"""持久化 DeepSeek 主脑提示词。

页面只编辑主脑的任务理解、项目选择、契约设计和验收偏好。Agent 白名单、
JSON Schema 等运行安全约束仍由 planner 在请求时追加，避免误配置破坏控制协议。
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from app.domain.configuration import BrainConfiguration


DEFAULT_PLANNING_PROMPT = """
你是多项目软件工程工作空间的主脑，负责基于专业 Agent 的项目发现结果做架构判断、
项目选择、跨项目契约设计、任务拆解和依赖决策。

工作原则：
1. 用户选择的是待改造代码工作空间，不是 Agent Studio 本身。除非工作空间确实指向
   Agent Studio，否则不要把 frontend/、backend/、netty/ 当作固定目录。
2. 先阅读各专业 Agent 返回的候选项目、技术栈证据、相关入口和推荐修改范围，再选择
   与目标最匹配的真实项目根目录；不要仅凭目录名称猜测。
3. 新功能跨越前端、业务后端或 Netty 服务时，先定义共享契约。HTTP API 至少写明
   method、path、认证、请求字段、响应字段、错误码和兼容策略；二进制协议需写明帧结构、
   字段、字节序、消息类型和异常行为。后端或协议实施任务还应在被选项目已有的 OpenAPI、
   接口文档或等效位置落地这份契约；没有文档入口时创建与项目惯例一致的契约文档。
4. 将同一份契约提供给所有相关实现节点。接口契约已经明确时，前后端应并行编码，
   前端可以先基于契约实现类型和请求层，不要无意义地等待后端代码完成。
5. 每个任务必须写明实际项目相对路径、修改目标、不可越界的范围和验证要求。
6. 只调用与目标有关的专业 Agent；不要为了展示并行而创建无关节点。
7. 每个专业 Agent 自己完成本项目的测试和自检，不创建独立测试 Agent。
""".strip()


DEFAULT_SUMMARY_PROMPT = """
你是多项目软件工程任务的最终验收者。根据用户目标、项目发现结果、共享契约、实施 DAG
和 Agent 执行结果进行汇总。明确说明实际选择了哪些项目、接口或协议契约、各项目完成
内容、验证结果、失败或跳过项和遗留风险。不要编造未执行的修改或测试。
使用简洁的中文 Markdown。
""".strip()


class BrainSettings:
    def __init__(self, config_path: Path, defaults_path: Path | None = None) -> None:
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
            planning_prompt=DEFAULT_PLANNING_PROMPT,
            summary_prompt=DEFAULT_SUMMARY_PROMPT,
        )

    def current(self) -> BrainConfiguration:
        with self._lock:
            if not self.config_path.exists():
                return self.defaults.model_copy()
            try:
                payload = json.loads(self.config_path.read_text(encoding="utf-8"))
                return BrainConfiguration.model_validate(payload)
            except (OSError, ValueError, json.JSONDecodeError):
                return self.defaults.model_copy()

    def default(self) -> BrainConfiguration:
        """返回版本库模板的副本，供配置页面显式恢复默认值。"""

        return self.defaults.model_copy()

    def update(self, configuration: BrainConfiguration) -> BrainConfiguration:
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.config_path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(configuration.model_dump(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.config_path)
        return configuration.model_copy()
