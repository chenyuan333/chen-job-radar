"""
Gunicorn 入口 - 用于云端部署
本地调试仍用 python app.py
"""
import os
from app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5173)))
