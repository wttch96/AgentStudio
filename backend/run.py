"""本地 Flask 开发服务入口。

监听地址由配置强制校验为回环地址，避免误把带有代码执行能力的服务暴露到局域网。
"""

from app import create_app
from app.config import Settings


settings = Settings.from_env()
app = create_app(settings)


if __name__ == "__main__":
    app.run(host=settings.backend_host, port=settings.backend_port, threaded=True, debug=False)

