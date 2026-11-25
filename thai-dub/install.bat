@echo off
chcp 65001 >nul
echo === กำลังติดตั้งไลบรารีที่จำเป็น ===
python -m pip install --upgrade pip
python -m pip install -r "%~dp0requirements.txt"
echo.
echo === ติดตั้งเสร็จแล้ว ดับเบิลคลิก run.bat เพื่อเริ่มใช้งาน ===
pause
