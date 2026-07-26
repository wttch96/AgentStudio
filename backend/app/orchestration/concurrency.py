"""并发与文件冲突控制。

在任务调度阶段检测同一波次中多个任务之间的文件写入冲突，
通过添加顺序依赖来防止多个 Agent 同时修改相同文件。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FileConflict:
    """文件写入冲突描述。"""

    task_a: str  # 任务 A 的 ID
    task_b: str  # 任务 B 的 ID
    conflicting_path: str  # 冲突路径
    resolution: str = "sequentialize"  # 解决策略


class ConflictDetector:
    """检测并解决任务之间的文件写入冲突。

    规则:
        1. write_scope 重叠 → 冲突，需要顺序化
        2. 空 write_scope（只读任务）→ 永不冲突
        3. 冲突解决: 给 task_b 添加对 task_a 的顺序依赖
    """

    def detect(self, tasks: list) -> list[FileConflict]:
        """检测一批任务中的文件写入冲突。

        Args:
            tasks: DagTask 或 AgentTask 列表（有 write_scope 属性的对象）

        Returns:
            检测到的冲突列表
        """
        conflicts: list[FileConflict] = []
        n = len(tasks)

        for i in range(n):
            for j in range(i + 1, n):
                t1, t2 = tasks[i], tasks[j]
                ws1 = self._normalize_scope(getattr(t1, "write_scope", []))
                ws2 = self._normalize_scope(getattr(t2, "write_scope", []))

                # 空 write_scope = 只读，不冲突
                if not ws1 or not ws2:
                    continue

                # 检测重叠
                overlap = self._find_overlap(ws1, ws2)
                for path in overlap:
                    conflicts.append(
                        FileConflict(
                            task_a=getattr(t1, "id", str(i)),
                            task_b=getattr(t2, "id", str(j)),
                            conflicting_path=path,
                            resolution="sequentialize",
                        )
                    )

        return conflicts

    def resolve(
        self,
        conflicts: list[FileConflict],
        tasks: list,
    ) -> list:
        """通过添加顺序依赖来解决冲突。

        对每个冲突，给 task_b 添加对 task_a 的顺序依赖，
        确保 task_a 先执行完成后 task_b 才开始。

        Args:
            conflicts: 检测到的冲突列表
            tasks: 原始任务列表（会通过 depends_on 修改）

        Returns:
            修改后的任务列表
        """
        # 用 depends_on 属性构建任务引用
        task_map: dict[str, object] = {}
        for t in tasks:
            tid = getattr(t, "id", "")
            if tid:
                task_map[tid] = t

        for conflict in conflicts:
            tb = task_map.get(conflict.task_b)
            if tb is None:
                continue

            existing_deps = list(getattr(tb, "depends_on", []))
            if conflict.task_a not in existing_deps:
                # 修改 depends_on
                if hasattr(tb, "depends_on"):
                    if hasattr(tb, "model_copy"):
                        # Pydantic 模型 — 通过 model_copy 不可变修改
                        # 在 resolve() 中修改原列表的元素
                        new_deps = list(tb.depends_on) + [conflict.task_a]
                        object.__setattr__(tb, "depends_on", new_deps)
                    elif isinstance(tb.depends_on, list):
                        tb.depends_on.append(conflict.task_a)

        return tasks

    def get_resource_locks(
        self, tasks: list,
    ) -> dict[str, dict[str, str]]:
        """生成任务所需的资源锁信息。

        Returns:
            {file_path: {agent: str, task_id: str}}
            可用于在黑板中记录锁状态。
        """
        locks: dict[str, dict[str, str]] = {}
        for task in tasks:
            ws = self._normalize_scope(getattr(task, "write_scope", []))
            tid = getattr(task, "id", "")
            agent = getattr(task, "agent", "")
            for path in ws:
                if path:
                    locks[f"locks:{path}"] = {
                        "agent": agent,
                        "task_id": tid,
                        "status": "pending",
                    }
        return locks

    # ── 内部工具 ──────────────────────────────────────────────────

    @staticmethod
    def _normalize_scope(scope: list[str]) -> set[str]:
        """标准化 write_scope 为路径集合。"""
        result: set[str] = set()
        for s in scope:
            s = s.strip().rstrip("/\\")
            if s and s != ".":
                result.add(s)
        return result

    @staticmethod
    def _find_overlap(
        scope1: set[str], scope2: set[str],
    ) -> set[str]:
        """查找两个 write_scope 的重叠路径。"""
        overlap: set[str] = set()
        for p1 in scope1:
            for p2 in scope2:
                # 完全相同 或 一个包含另一个
                if p1 == p2 or p1.startswith(p2 + "/") or p2.startswith(p1 + "/"):
                    overlap.add(p1 if len(p1) <= len(p2) else p2)
        return overlap


class NoOpConflictDetector(ConflictDetector):
    """不做冲突检测的探测器 — 所有任务都可在同一波次并行。

    用于向后兼容: 当未配置冲突检测时，系统行为不变。
    """

    def detect(self, tasks: list) -> list[FileConflict]:
        return []
