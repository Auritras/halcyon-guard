"""Start Halcyon Guard: python run.py  (then open http://127.0.0.1:8000)"""
import os
import sys
import threading
import webbrowser

import uvicorn

from halcyon.app import create_app
from halcyon.config import get_settings


def main():
    settings = get_settings()
    port = int(os.getenv("PORT", "8000"))
    url = f"http://127.0.0.1:{port}"
    print(f"Halcyon Guard: {url}  (AI provider: {settings.llm_provider})")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
