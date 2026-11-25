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
    host = os.getenv("HOST", "127.0.0.1")  # a host like Render sets HOST=0.0.0.0
    url = f"http://127.0.0.1:{port}"
    print(f"Halcyon Guard on {host}:{port}  (AI provider: {settings.llm_provider})", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    uvicorn.run(create_app(settings), host=host, port=port, log_level="info" if host != "127.0.0.1" else "warning",
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
