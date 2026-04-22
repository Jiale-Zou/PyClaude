from __future__ import annotations

def main() -> None:
    from claude_agent.api.server import create_app

    try:
        import uvicorn
    except Exception as e:
        raise RuntimeError("uvicorn is required to run the FastAPI server.") from e

    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
