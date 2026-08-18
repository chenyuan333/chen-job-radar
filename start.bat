@echo off
REM ============================================
REM   🍊 医疗岗位雷达 - 一键启动脚本
REM ============================================
REM   双击本文件即可启动服务，浏览器会自动打开
REM   如需停止：双击 stop.bat
REM ============================================

chcp 65001 >nul
title 医疗岗位雷达 - 启动中

set "APP_DIR=D:\workbuddy\2026-08-03-10-33-38\岗位雷达小程序"
set "PORT=5173"

cd /d "%APP_DIR%"

REM 检查 python 是否可用
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9+
    echo        下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查 flask 是否安装
python -c "import flask" 2>nul
if errorlevel 1 (
    echo [提示] 首次启动，正在安装依赖...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络
        pause
        exit /b 1
    )
)

REM 杀掉可能残留的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

REM 启动服务（端口 5173，监听所有网卡方便手机访问同 wifi 时打开）
echo 正在启动服务...
set "HOST=0.0.0.0"
start "医疗岗位雷达" /min python app.py

REM 等待服务起来
:wait_loop
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul
if errorlevel 1 goto wait_loop

REM 拿到本机 IP，方便手机访问
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    set "LAN_IP=%%a"
    goto :got_ip
)
:got_ip

echo.
echo  ╔════════════════════════════════════════════════╗
echo  ║   🍊 医疗岗位雷达 - 已启动                    ║
echo  ╠════════════════════════════════════════════════╣
echo  ║   本机：http://127.0.0.1:%PORT%                  ║
echo  ║   同wifi手机：http://%LAN_IP%:%PORT%  ║
echo  ╚════════════════════════════════════════════════╝
echo.
echo  关闭本窗口或双击 stop.bat 停止服务

REM 自动打开浏览器
start "" http://127.0.0.1:%PORT%

pause >nul
