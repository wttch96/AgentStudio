"""Flask 应用工厂。"""

import logging
import time
import traceback
import uuid

from flask import Flask, g, request
from flask_cors import CORS
from werkzeug.exceptions import HTTPException

from app.api.routes import api
from app.config import Settings
from app.logging_config import configure_logging
from app.services.container import ServiceContainer

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> Flask:
    """创建应用并组装依赖，测试时可传入独立配置。"""

    configure_logging()
    current_settings = settings or Settings.from_env()
    logger.info(
        "app.starting host=%s port=%s workspace=%s data_dir=%s demo_mode=%s",
        current_settings.backend_host,
        current_settings.backend_port,
        current_settings.workspace_root,
        current_settings.data_dir,
        current_settings.demo_mode,
    )
    app = Flask(__name__, instance_path=str(current_settings.data_dir))
    app.config["JSON_SORT_KEYS"] = False
    app.config["SETTINGS"] = current_settings

    # 前后端虽然分端口运行，但都只能从本机回环地址访问。
    allowed_origins = [
        f"http://127.0.0.1:{current_settings.frontend_port}",
        f"http://localhost:{current_settings.frontend_port}",
    ]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

    current_settings.data_dir.mkdir(parents=True, exist_ok=True)
    container = ServiceContainer.build(current_settings)
    app.extensions["services"] = container
    app.register_blueprint(api, url_prefix="/api")

    @app.before_request
    def log_request_started() -> None:
        g.request_started_at = time.perf_counter()
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        if request.path != "/health":
            logger.info(
                "http.started request_id=%s method=%s path=%s endpoint=%s "
                "project_id=%s content_length=%s",
                g.request_id,
                request.method,
                request.path,
                request.endpoint or "-",
                (request.view_args or {}).get("project_id")
                or request.args.get("project_id")
                or "-",
                request.content_length or 0,
            )

    @app.after_request
    def log_request_completed(response):
        request_id = getattr(g, "request_id", "-")
        started_at = getattr(g, "request_started_at", time.perf_counter())
        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers["X-Request-ID"] = request_id
        log = logger.debug if request.path == "/health" else logger.info
        log(
            "http.completed request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
            request_id,
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "access": "local-only"}

    @app.errorhandler(500)
    def handle_500(e):
        logger.error(
            "http.internal_error request_id=%s error=%s\n%s",
            getattr(g, "request_id", "-"),
            e,
            traceback.format_exc(),
        )
        return {"error": "Internal Server Error", "detail": str(e)}, 500

    @app.errorhandler(Exception)
    def handle_exception(e):
        if isinstance(e, HTTPException):
            return {"error": e.name, "detail": e.description}, e.code
        logger.error(
            "http.unhandled_exception request_id=%s error_type=%s error=%s\n%s",
            getattr(g, "request_id", "-"),
            type(e).__name__,
            e,
            traceback.format_exc(),
        )
        return {"error": "Internal Server Error", "detail": str(e)}, 500

    logger.info("app.ready routes=%s", len(app.url_map._rules))
    return app
