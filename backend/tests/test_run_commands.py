from app.services.run_commands import parse_run_command


def test_direct_agent_commands_are_parsed():
    frontend = parse_run_command("/frontend 修复页面布局")
    backend = parse_run_command("/agent backend 检查接口")

    assert frontend.kind == "direct"
    assert frontend.agent == "frontend-agent"
    assert frontend.instruction == "修复页面布局"
    assert backend.agent == "backend-agent"
    assert backend.instruction == "检查接口"


def test_retry_command_keeps_task_id():
    command = parse_run_command("/retry parse-packet")

    assert command.kind == "retry"
    assert command.task_id == "parse-packet"
