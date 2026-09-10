from flask import Flask

from servio.config import BASE_DIR, Config


def create_app(config_object: type = Config) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config.from_object(config_object)

    from servio.routes import register_routes

    register_routes(app)

    return app
