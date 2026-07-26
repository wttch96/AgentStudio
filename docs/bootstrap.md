# 自举与本地启动

Agent Studio 提供两种启动方式：

- `./start.sh`：直接在当前工作区安装依赖并启动前后端。
- `./bootstrap.sh`：从已提交的 `main` 创建稳定沙箱，同时把本地工作区切换到 `dev`。

## 环境要求

- Git
- tar
- Python 3.11 或更高版本
- Node.js `^20.19.0` 或 `>=22.12.0`
- npm
- curl

启动脚本会在执行任何安装前检查这些依赖和版本。Web 服务只接受
`127.0.0.1`、`localhost` 或 `::1`。

## 稳定沙箱与开发分支

执行：

```bash
./bootstrap.sh
```

自举顺序固定为：

1. 从本地已提交的 `main` 分支读取 commit，不读取当前工作区文件。
2. 使用 `git archive main` 创建 `.sandbox/` 稳定快照。
3. 将项目根目录的 `.env` 复制到 `.sandbox/.env`，权限收紧为仅当前用户可读写。
4. 如果本地没有 `.env`，从 `.env.example` 创建沙箱配置并进入演示模式。
5. 本地存在 `dev` 时切换到 `dev`；不存在时从 `main` 创建 `dev`。
6. 在沙箱内安装依赖、启动服务并等待前后端健康检查通过。

因此，沙箱始终运行已提交的 `main`，本地未提交修改留在 `dev`，不会进入稳定沙箱。
要更新沙箱版本，应先把已验收的 `dev` 变更合并到 `main`，再重新执行自举。

可单独执行：

```bash
./bootstrap.sh setup
./bootstrap.sh start
./bootstrap.sh stop
./bootstrap.sh restart
./bootstrap.sh status
./bootstrap.sh destroy
```

`status` 会显示沙箱来源分支、commit、服务 PID、命令和监听端口。

## 直接启动

```bash
cp .env.example .env
./start.sh
```

直接启动会：

1. 创建 `backend/.venv`；
2. 根据 `pyproject.toml` 和 Python 版本签名安装后端依赖；
3. 根据 `package.json`、`package-lock.json` 和 Node 版本签名执行 `npm ci`；
4. 直接启动 Flask 和 Vite 子进程；
5. 最多等待 30 秒，只有 `/health` 和前端首页都可访问才报告成功；
6. 任一子进程退出时停止另一个进程并返回真实退出码。

调用方传入的地址和端口优先于 `.env`，可用于并行实例：

```bash
BACKEND_PORT=5011 FRONTEND_PORT=5184 ./start.sh
```

Vite 的 `/api` 和 `/health` 代理会自动跟随实际 `BACKEND_HOST` 和
`BACKEND_PORT`。

## 安全停止

```bash
./stop.sh
```

停止脚本只处理 `.run/backend.pid` 和 `.run/frontend.pid`，并在发送信号前检查：

- PID 属于当前用户；
- 后端命令使用当前项目的 venv 并运行 `run.py`；
- 前端命令使用当前项目的 Vite 入口。

归属不匹配时脚本拒绝停止进程并保留 PID 文件，避免陈旧 PID 误伤其他程序。正常
`SIGTERM` 在 5 秒内无效时，才会对仍匹配当前服务的进程发送 `SIGKILL`。

## 运行数据

依赖、日志和运行数据不会写入 Git：

```text
backend/.venv/
frontend/node_modules/
.run/
.sandbox/
.workspace/
```

沙箱中的 `.bootstrap-meta` 保存 `main` 来源 commit，`.env` 始终保持未跟踪状态。
