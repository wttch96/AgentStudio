"""Spring Boot 风格日志配置 — 统一、可读、不泄露请求正文。"""

from __future__ import annotations

import logging
import os
import sys


# ── ANSI 颜色 (终端输出) ──────────────────────────────────────────
RESET = "\033[0m"
COLORS = {
    logging.DEBUG: "\033[36m",     # CYAN
    logging.INFO: "\033[32m",      # GREEN
    logging.WARNING: "\033[33m",   # YELLOW
    logging.ERROR: "\033[31m",     # RED
    logging.CRITICAL: "\033[1;31m",  # BOLD RED
}
LEVEL_PAD = {"DEBUG": "DEBUG", "INFO": " INFO", "WARNING": " WARN",
             "ERROR": "ERROR", "CRITICAL": "FATAL"}

# Spring Boot 风格格式 (无色版本，用于文件/管道)
PLAIN_FMT = (
    "%(asctime)s.%(msecs)03d  "
    "%(levelname)-5s  "
    "%(pid)s --- "
    "[%(threadName)-15s] "
    "%(name)-40s : "
    "%(message)s"
)


class SpringBootFormatter(logging.Formatter):
    """Spring Boot 风格格式化器，支持 ANSI 彩色输出。

    格式::

        2026-07-27 10:30:45.123  INFO  12345 --- [Thread-1       ] app.services.run_manager          : run.started ...
    """

    _use_color: bool

    def __init__(self, use_color: bool = True):
        super().__init__(fmt=PLAIN_FMT, datefmt="%Y-%m-%d %H:%M:%S")
        self._use_color = use_color
        self._pid = str(os.getpid())

    def format(self, record: logging.LogRecord) -> str:
        # 注入 PID
        record.pid = self._pid  # type: ignore[attr-defined]

        # 缩短 logger 名 (仿 Spring Boot 的缩写风格)
        name = record.name
        if len(name) > 40:
            parts = name.split(".")
            if len(parts) > 2:
                # 保留首段 + 末段全名, 中间取首字母
                name = ".".join(
                    [parts[0]]
                    + [p[0] for p in parts[1:-1]]
                    + [parts[-1]]
                )
            record.name = name[:40]

        # 缩短线程名
        thread_name = record.threadName
        if thread_name and len(thread_name) > 15:
            # run-abc12345 → run-ab…
            record.threadName = thread_name[:12] + "…"

        # 对齐 level
        level_name = record.levelname
        record.levelname = LEVEL_PAD.get(level_name, level_name)

        msg = super().format(record)

        # 恢复原始值 (避免影响其他 handler)
        record.name = record.name  # no-op, keep shortened version

        if self._use_color:
            color = COLORS.get(record.levelno, "")
            if color:
                msg = color + msg + RESET

        return msg


def configure_logging() -> None:
    """配置根 Logger, 重复创建 Flask app 时不会重复添加 Handler。

    环境变量:
        LOG_LEVEL     — 日志级别, 默认 INFO
        LOG_COLOR     — 是否使用 ANSI 颜色, 默认 true (管道/重定向时自动关闭)
        LOG_FORMAT    — ``spring`` (默认) 或 ``plain``
    """

    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    if not any(getattr(h, "_agent_studio_handler", False) for h in root.handlers):
        use_color = os.getenv("LOG_COLOR", "").strip().lower() != "false"
        # 管道/重定向时自动关闭颜色
        if use_color and not sys.stdout.isatty():
            use_color = False

        fmt_choice = os.getenv("LOG_FORMAT", "spring").strip().lower()
        if fmt_choice == "plain":
            # 简单格式: 时间 级别 [线程] 名称: 消息
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)-5s [%(threadName)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))
        else:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(SpringBootFormatter(use_color=use_color))

        handler._agent_studio_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    # 抑制 werkzeug 访问日志 (由 Flask 的 before/after_request 替代)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
