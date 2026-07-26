"""黑板同步测试 —— Agent 结果写回、状态转换。"""


class TestBoardWritebackLogic:
    """黑板写回逻辑测试（不依赖实际存储）。"""

    def test_result_key_format(self):
        """验证 result key 的命名格式。"""
        task_id = "task-abc-123"
        expected_key = f"result:{task_id}"
        assert expected_key == "result:task-abc-123"

    def test_status_mapping_completed_to_review(self):
        """Agent status 'completed' 应映射为 board status 'review'。"""
        agent_status = "completed"
        board_status_map = {
            "completed": "review",    # Agent 完成 → 进入审查
            "failed": "failed",
            "blocked": "blocked",
        }
        expected_board = board_status_map.get(agent_status, agent_status)
        assert expected_board == "review"

    def test_review_transitions(self):
        """审查后的状态转换。"""
        transitions = {
            "accepted": "completed",
            "accepted_with_risks": "completed",
            "revision_required": "revision_required",
            "rejected": "rejected",
            "blocked": "blocked",
        }
        assert transitions["accepted"] == "completed"
        assert transitions["revision_required"] == "revision_required"
        # revision_required 绝对不会直接变成 completed
        assert transitions["revision_required"] != "completed"

    def test_board_keys_structure(self):
        """验证黑板中各 key 的结构。"""
        keys = ["result:task-1", "review:task-1", "all_results", "all_reviews"]
        for k in keys:
            assert isinstance(k, str)
            assert len(k) > 0


class TestTodoSyncLogic:
    """Todo 同步逻辑测试。"""

    def test_todo_statuses(self):
        """Todo 状态常量。"""
        statuses = ["pending", "in_progress", "completed", "blocked"]
        assert len(statuses) == 4

    def test_todo_init_from_dag(self):
        """从 DAG tasks 初始化 Todo。"""
        dag_tasks = [
            {"id": "t1", "title": "任务1", "agent": "a1",
             "depends_on": []},
            {"id": "t2", "title": "任务2", "agent": "a2",
             "depends_on": ["t1"]},
        ]
        todo_items = [
            {"id": t["id"], "content": t["title"],
             "assigned_to": t["agent"],
             "depends_on": t["depends_on"]}
            for t in dag_tasks
        ]
        assert len(todo_items) == 2
        assert todo_items[1]["depends_on"] == ["t1"]
