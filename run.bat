@echo off
cd /d C:\railmind

start "RailMind Backend" cmd /k "call .venv\Scripts\activate.bat && uvicorn src.api.main:app --reload"
start "RailMind Frontend" cmd /k "cd dashboard && npm run dev"