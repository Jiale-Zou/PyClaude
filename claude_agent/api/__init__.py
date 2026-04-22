__all__ = ["create_app"]


def create_app() -> object:
    from claude_agent.api.server import create_app as _create_app

    return _create_app()
