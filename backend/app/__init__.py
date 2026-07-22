"""Flask 应用工厂。"""

from flask import Flask
from flask_cors import CORS

from app.api.routes import api
from app.config import Settings
from app.services.container import ServiceContainer


def create_app(settings: Settings | None = None) -> Flask:
    """创建应用并组装依赖，测试时可传入独立配置。"""

    current_settings = settings or Settings.from_env()
    app = Flask(__name__, instance_path=str(current_settings.instance_dir))
    app.config["JSON_SORT_KEYS"] = False
    app.config["SETTINGS"] = current_settings

    # 前后端虽然分端口运行，但都只能从本机回环地址访问。
    allowed_origins = [
        f"http://127.0.0.1:{current_settings.frontend_port}",
        f"http://localhost:{current_settings.frontend_port}",
    ]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

    current_settings.instance_dir.mkdir(parents=True, exist_ok=True)
    container = ServiceContainer.build(current_settings)
    app.extensions["services"] = container
    app.register_blueprint(api, url_prefix="/api")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "access": "local-only"}

    return app

