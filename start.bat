@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo =========================================
echo    ⚔️  兵器破阵 · 易经起卦 v2.0
echo =========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

REM 安装依赖
echo [1/2] 检查依赖...
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

REM 启动服务
echo [2/2] 启动后端服务 (端口 8000)...
echo.
echo   前端页面: http://localhost:8000/static/index.html
echo   API 文档: http://localhost:8000/docs
echo.
echo   按 Ctrl+C 停止服务
echo =========================================

start "" http://localhost:8000/static/index.html
python server.py

pause