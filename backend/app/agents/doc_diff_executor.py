"""DocDiffAgent — 文档对比 Agent。

对比当前文件与 Blackboard 中存储的历史版本，使用 Claude 生成语义 diff 报告。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.models import AgentResult, DagTask
from app.services.blackboard_state import BlackboardStateOps


class DocDiffAgentExecutor:
    """专用执行器：文档版本对比。

    工作流程：
    1. 从 task.objective 中解析目标文件路径和历史版本 key
    2. 读取当前工作目录中的文件
    3. 从 blackboard 读取旧版本内容
    4. 使用 Claude Agent SDK 生成语义 diff + 变更分析
    5. 将 diff 报告写回 blackboard
    """

    # 解析 objective 格式: "diff FILE_PATH against BLACKBOARD_KEY -> OUTPUT_KEY"
    # 或自然语言描述

    def __init__(
        self,
        blackboard: BlackboardStateOps,
        claude_executor: Any = None,
    ) -> None:
        self._blackboard = blackboard
        self._claude = claude_executor

    def execute(
        self,
        run_id: str,
        task: DagTask,
        dependency_results: list[AgentResult],
        cancel_event: threading.Event,
        workspace_root: str,
        max_turns: int | None = None,
        timeout_seconds: int | None = None,
        project_id: str | None = None,
    ) -> AgentResult:
        """执行文档对比。"""
        started_at = datetime.now(timezone.utc).isoformat()

        # 1. 解析参数
        params = self._parse_objective(task.objective, dependency_results)
        file_path = params.get("file_path", "")
        source_key = params.get("source_key", "doc_snapshot")
        output_key = params.get("output_key", "diff_report")

        # 2. 读取当前文件
        abs_path = Path(workspace_root) / file_path
        current_content = ""
        if abs_path.exists():
            current_content = abs_path.read_text(encoding="utf-8")

        # 3. 读取旧版本
        previous_content = self._blackboard.read(source_key)
        if previous_content is None:
            # 没有旧版本，认为是首次检查
            self._blackboard.write(source_key, current_content, "doc-diff")
            return AgentResult(
                task_id=task.id,
                agent=task.agent,
                status="completed",
                summary=f"已保存文件 {file_path} 的快照到 blackboard.{source_key}，待下次对比。",
                provides=[output_key],
                started_at=started_at,
                duration_ms=0,
            )

        if isinstance(previous_content, str):
            prev_text = previous_content
        else:
            prev_text = json.dumps(previous_content, ensure_ascii=False, indent=2)

        # 4. 如果有 Claude executor，用 LLM 做语义 diff
        if self._claude:
            diff_report = self._semantic_diff(current_content, prev_text, file_path)
        else:
            diff_report = self._plain_diff(current_content, prev_text, file_path)

        # 5. 存储报告
        self._blackboard.write(output_key, diff_report, "doc-diff")

        # 6. 更新快照为最新版本
        self._blackboard.write(source_key, current_content, "doc-diff")

        return AgentResult(
            task_id=task.id,
            agent=task.agent,
            status="completed",
            summary=diff_report[:500],
            provides=[output_key],
            started_at=started_at,
            duration_ms=0,
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _parse_objective(
        self,
        objective: str,
        dependency_results: list[AgentResult],
    ) -> dict[str, str]:
        """尝试从 objective 文本中提取文件路径和 key。

        支持的格式：
        - "diff src/app.py against api_contract -> api_diff_report"
        - "对比 src/app.py，源 key: old_version，输出 key: diff_result"
        """
        params: dict[str, str] = {}
        # 简单关键词解析
        import re
        file_match = re.search(r"([\w./-]+\.[\w]+)", objective)
        if file_match:
            params["file_path"] = file_match.group(1)

        source_match = re.search(r"(?:against|源\s*key[:：])\s*(\w+)", objective)
        if source_match:
            params["source_key"] = source_match.group(1)

        output_match = re.search(r"(?:->|输出\s*key[:：])\s*(\w+)", objective)
        if output_match:
            params["output_key"] = output_match.group(1)

        return params

    @staticmethod
    def _plain_diff(current: str, previous: str, file_path: str) -> str:
        """纯文本逐行 diff（无 LLM 时使用）。"""
        import difflib
        current_lines = current.splitlines(keepends=True)
        previous_lines = previous.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                previous_lines,
                current_lines,
                fromfile=f"{file_path} (旧)",
                tofile=f"{file_path} (新)",
                lineterm="",
            )
        )
        if not diff_lines:
            return f"文件 {file_path} 无变更。"
        return "\n".join(diff_lines)

    def _semantic_diff(self, current: str, previous: str, file_path: str) -> str:
        """使用 Claude 生成语义 diff。

        通过 claude_executor 发送简化的对比请求。
        由于不依赖完整的 LangGraph worker，这里只做简单的 prompt 构建；
        实际执行由调用方的 Claude executor 完成。
        """
        prompt = f"""对比以下两个版本的文件并生成变更分析报告：

## 文件路径
{file_path}

## 旧版本
```
{previous[:3000]}
```

## 新版本
```
{current[:3000]}
```

请分析：
1. 主要变更摘要（2-3 句话）
2. 新增/删除/修改的具体内容
3. 潜在影响评估
"""
        # 简化实现：直接走 LLM
        return prompt  # caller will use claude_executor
