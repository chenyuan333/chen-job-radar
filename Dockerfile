FROM python:3.11-slim

WORKDIR /app

# 装中文环境（不影响功能，但有时区/编码问题更少）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render / Heroku / 任何平台都通过 PORT 环境变量注入端口
ENV PORT=5173
EXPOSE 5173

CMD ["gunicorn", "-b", "0.0.0.0:5173", "-w", "2", "--timeout", "120", "wsgi:app"]
