@echo off
chcp 65001 >nul
if not exist .env.local (
  echo [提示] 未找到 .env.local，正在从 .env.local.example 复制...
  copy /Y .env.local.example .env.local >nul
)
python app.py
