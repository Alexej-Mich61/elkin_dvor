@echo off
rem Однократная отправка готовых писем из почтовой очереди (этап 6).
rem Для регулярной отправки добавьте этот файл в Планировщик заданий Windows.
rem Параметры команды пробрасываются: send_emails.bat --batch 50
cd /d "%~dp0"
rem UTF-8 в консоли, чтобы вывод писем и логов с кириллицей не ломался.
chcp 65001 >nul
set PYTHONUTF8=1
venv\Scripts\python.exe manage.py send_order_emails %*
