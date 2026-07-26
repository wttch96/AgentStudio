"""统一、可读且不泄露请求正文的后端日志配置。"""

from __future__ import annotations

import logging
import os
import sys


LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)s "
    "[%(threadName)s] %(name)s: %(message)s"
)


def configure_logging() -> None:
    """配置根 Logger；重复创建 Flask app 时不会重复添加 Handler。"""

    level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    if not any(getattr(handler, "_agent_studio_handler", False) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        handler._agent_studio_handler = True  # type: ignore[attr-defined]
        root.addHandler(handler)

    logging.getLogger("werkzeug").setLevel(level)
