\
@echo off
REM Construye un .exe de Pascucci Smart Inventory (Windows)
pip install pyinstaller
set ADD_DATA=init_db.sql;init_db.sql ^
;app.py;app.py ^
;emailer.py;emailer.py ^
;report_pdf.py;report_pdf.py ^
;email_config.json;email_config.json ^
;pascucci.db;pascucci.db

pyinstaller --noconfirm --clean --onefile run_app.py --name PascucciSmartInventory ^
 --add-data %ADD_DATA%

echo.
echo Listo. Busca el ejecutable en .\dist\PascucciSmartInventory.exe
pause
