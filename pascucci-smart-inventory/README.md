# Pascucci Smart Inventory — v4 (Piloto completo)

- 10 productos solicitados (Capuccino, Chocolate caliente, Croissant, Jugo de naranja, Cheesecake frutos del bosque (porción), Ensalada César Romana, Café, Copa de helado, Torta chocolate (porción), Rollos estilo New York).
- 6 meses de datos simulados (ventas, compras/lotes, mermas, promoción).
- CRUD completo con **auditoría** de cambios.
- **FEFO** al vender.
- Dashboard con KPIs, **Reposiciones (ROP)** y **Liquidaciones por vencimiento**, gráficos semanal/mensual.
- **Importar/Exportar CSV**.
- **Reportes PDF** (estándar + **Ejecutivo**) y **envío por correo** (SMTP configurables).
- **Programación automática** de correos (lunes 08:00 y día 1 08:00).
- **Respaldo diario** a las 02:00 + botón “Respaldar ahora”.
- Guardrails de **margen mínimo** en promociones (ajustable).

## Requisitos
- Python 3.11+
```
pip install -r requirements.txt
streamlit run app.py
```
Abrir `http://localhost:8501`.

## Correo y programaciones
- Configura en **Ajustes & Reportes** o editando `email_config.json`.
- Activa “**scheduler_enabled**” para correo programado.
- Backups diarios a `/backups/` y botón de respaldo manual.

## Ejecutable (.exe)
- Corre `build_exe_windows.bat`. El .exe quedará en `dist/`.

## Regenerar la base (si quieres empezar de cero)
```
sqlite3 pascucci.db < init_db.sql
python simulate.py
```
