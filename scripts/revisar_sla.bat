@echo off
REM Ejecuta "python manage.py revisar_sla" con el Python del entorno virtual del proyecto.
REM Registrado en el Programador de tareas de Windows para correr cada 15 minutos.
REM Log en scripts\revisar_sla.log (se sobrescribe cada corrida).
cd /d "%~dp0.."
"C:\Users\Lenovo\Desktop\SCS\venv\Scripts\python.exe" manage.py revisar_sla > "%~dp0revisar_sla.log" 2>&1