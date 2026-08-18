@echo off
REM ============================================
REM   停止医疗岗位雷达服务
REM ============================================
chcp 65001 >nul
set "PORT=5173"

REM 杀掉监听端口的进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
    echo 停止 PID=%%a
    taskkill /F /PID %%a >nul 2>&1
)
REM 杀掉所有 python 进程里跑 app.py 的
taskkill /F /IM python.exe /FI "WINDOWTITLE eq 医疗岗位雷达*" >nul 2>&1

echo 已停止。
timeout /t 2 >nul
