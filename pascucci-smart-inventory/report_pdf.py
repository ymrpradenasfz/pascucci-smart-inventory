from datetime import datetime, timedelta
import pandas as pd
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from pathlib import Path

def build_weekly_monthly_pdf(db_loader, out_path='resumen_pascucci.pdf', weeks=4):
    sales = db_loader('SELECT * FROM sales')
    if sales.empty:
        c = canvas.Canvas(out_path, pagesize=A4)
        c.drawString(3*cm, 27*cm, 'No hay ventas para generar reporte.')
        c.save()
        return out_path

    sales['sold_at'] = pd.to_datetime(sales['sold_at'])
    weekly = sales.groupby(sales['sold_at'].dt.to_period('W'))['total'].sum().reset_index()
    monthly = sales.groupby(sales['sold_at'].dt.to_period('M'))['total'].sum().reset_index()

    charts = Path('charts'); charts.mkdir(exist_ok=True)
    w_png = charts / 'ventas_semanales.png'
    m_png = charts / 'ventas_mensuales.png'

    fig1 = plt.figure()
    plt.plot(range(len(weekly)), weekly['total'])
    plt.title('Ventas semanales'); plt.xlabel('Semana'); plt.ylabel('CLP')
    fig1.savefig(w_png, bbox_inches='tight'); plt.close(fig1)

    fig2 = plt.figure()
    plt.plot(range(len(monthly)), monthly['total'])
    plt.title('Ventas mensuales'); plt.xlabel('Mes'); plt.ylabel('CLP')
    fig2.savefig(m_png, bbox_inches='tight'); plt.close(fig2)

    total = int(sales['total'].sum())
    last_week = int(sales[sales['sold_at']>(sales['sold_at'].max()-pd.Timedelta(days=7))]['total'].sum())

    c = canvas.Canvas(out_path, pagesize=A4)
    c.setFont('Helvetica-Bold', 14)
    c.drawString(2*cm, 28*cm, 'Pascucci Smart Inventory — Resumen')
    c.setFont('Helvetica', 11)
    c.drawString(2*cm, 27*cm, f'Generado: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    c.drawString(2*cm, 26.2*cm, f'Ventas Totales (CLP): {total:,}'.replace(',', '.'))
    c.drawString(2*cm, 25.6*cm, f'Ventas Últimos 7 días (CLP): {last_week:,}'.replace(',', '.'))
    try:
        c.drawImage(ImageReader(str(w_png)), 2*cm, 14*cm, width=16*cm, preserveAspectRatio=True, mask='auto')
        c.drawImage(ImageReader(str(m_png)), 2*cm, 6*cm, width=16*cm, preserveAspectRatio=True, mask='auto')
    except Exception:
        pass
    c.showPage(); c.save()
    return out_path

def build_executive_pdf(db_loader, out_path='resumen_ejecutivo.pdf'):
    import pandas as pd
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from datetime import datetime as _dt

    sales = db_loader('SELECT * FROM sales')
    if sales.empty:
        c = canvas.Canvas(out_path, pagesize=A4)
        c.drawString(3*cm, 27*cm, 'Sin datos para reporte.')
        c.save()
        return out_path

    sales['sold_at'] = pd.to_datetime(sales['sold_at'])
    total = int(sales['total'].sum())

    c = canvas.Canvas(out_path, pagesize=A4)
    c.setFillColorRGB(0.886, 0.102, 0.133)  # Rojo Pascucci
    c.rect(0, 780, 595, 60, fill=1, stroke=0)
    c.setFillColorRGB(1,1,1)
    c.setFont('Helvetica-Bold', 18)
    c.drawString(2*cm, 27.5*cm, 'Pascucci Smart Inventory — Resumen Ejecutivo')
    c.setFont('Helvetica', 11)
    c.drawString(2*cm, 26.8*cm, f'Generado: {_dt.now().strftime("%Y-%m-%d %H:%M")}')
    c.setFillColorRGB(0,0,0)

    c.setFont('Helvetica-Bold', 12)
    c.drawString(2*cm, 25.6*cm, f'Ventas totales (CLP): {total:,}'.replace(',', '.'))

    actions = [
        'Reponer SKUs con ROP excedido y cobertura < 7 días.',
        'Liquidar lotes que vencen en ≤7 días con exceso sobre demanda.',
        'Revisar margen en bebidas con mayor variabilidad.',
        'Ajustar min_stock en SKUs de alta rotación (Capuccino, Café, Rollos NY).',
        'Programar compra de insumos críticos antes del fin de semana.'
    ]
    y = 24.6*cm
    c.setFont('Helvetica-Bold', 12); c.drawString(2*cm, y, 'Acciones recomendadas:'); y -= 0.5*cm
    c.setFont('Helvetica', 11)
    for a in actions:
        c.drawString(2.5*cm, y, f'• {a}'); y -= 0.5*cm

    c.showPage(); c.save()
    return out_path
