from app.services.run_commands import parse_run_command


def test_direct_agent_commands_are_parsed():
    frontend = parse_run_command("/vue-frontend 修复页面布局")
    backend = parse_run_command("/flask-backend 检查接口")

    assert frontend.kind == "direct"
    assert frontend.agent == "vue-frontend"
    assert frontend.instruction == "修复页面布局"
    assert backend.agent == "flask-backend"
    assert backend.instruction == "检查接口"


def test_brain_command_routes_to_planner():
    command = parse_run_command("/brain 重新评估接口契约")

    assert command.kind == "normal"
    assert command.instruction == "重新评估接口契约"
