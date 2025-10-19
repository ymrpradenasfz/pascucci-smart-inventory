import sqlite3, os, json
import pandas as pd
import numpy as np
import streamlit as st
from datetime import datetime, timedelta, date
import matplotlib.pyplot as plt
from apscheduler.schedulers.background import BackgroundScheduler
from pathlib import Path

from report_pdf import build_weekly_monthly_pdf, build_executive_pdf
from emailer import send_email

DB = "pascucci.db"
APP_NAME = "Pascucci Smart Inventory"

PRIMARY = "#E21A22"; BLACK="#111111"; CARBON="#1F2937"; LIGHT="#E5E7EB"; WHITE="#FFFFFF"
SUCCESS="#2E7D32"; WARN="#F59E0B"; CRIT="#DC2626"

st.set_page_config(page_title=APP_NAME, layout="wide")

def conn():
    return sqlite3.connect(DB, check_same_thread=False)

@st.cache_data(ttl=300)
def load_df(query):
    with conn() as c:
        return pd.read_sql(query, c)

def run_sql(query, params=(), commit=False):
    with conn() as c:
        cur = c.cursor()
        cur.execute(query, params)
        if commit: c.commit()
        try:
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            return pd.DataFrame(rows, columns=cols)
        except:
            return pd.DataFrame()

def title_bar():
    st.markdown(f"<h2 style='color:{PRIMARY};margin-bottom:0'>{APP_NAME}</h2>", unsafe_allow_html=True)
    st.caption("PC & Tablet • CLP • FEFO • IA: ROP/Liquidaciones • Reportes y correo programado • Auditoría y Backups")

def log_audit(entity, entity_id, action, diff_json):
    try:
        run_sql("INSERT INTO audit(entity, entity_id, action, user, diff_json) VALUES(?,?,?,?,?)",
                (entity, int(entity_id) if entity_id else None, action, "local", json.dumps(diff_json, ensure_ascii=False)), commit=True)
    except Exception as e:
        print("Audit log error:", e)

# Scheduler (email weekly/monthly + daily backup)
_scheduler = None
def _job_send_report_email():
    cfg_path = Path("email_config.json")
    if not cfg_path.exists(): return
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if not cfg.get("scheduler_enabled", False): return
        pdf_path = build_weekly_monthly_pdf(load_df, out_path="resumen_pascucci.pdf")
        send_email(cfg["smtp_host"], int(cfg["smtp_port"]), cfg["username"], cfg["password"],
                   cfg.get("to_emails", []),
                   subject="[Pascucci Smart Inventory] Reporte programado",
                   body="Adjunto reporte programado.",
                   attachments=[pdf_path])
    except Exception as e:
        print("Scheduler email error:", e)

def _job_backup_daily():
    try:
        os.makedirs("backups", exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        import shutil
        shutil.copyfile(DB, f"backups/pascucci_{ts}.db")
    except Exception as e:
        print("Backup job error:", e)

def _ensure_scheduler():
    global _scheduler
    if _scheduler is not None: return _scheduler
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_job_send_report_email, "cron", day_of_week="mon", hour=8, minute=0)
    _scheduler.add_job(_job_send_report_email, "cron", day=1, hour=8, minute=0)
    _scheduler.add_job(_job_backup_daily, "cron", hour=2, minute=0)
    _scheduler.start()
    return _scheduler

title_bar()
section = st.sidebar.radio("Módulos", ["Dashboard","Productos","Compras/Lotes","Ventas","Mermas","Promociones","Proveedores","Importar/Exportar","Ajustes & Reportes","Auditoría"])

# Helpers
def get_products(): return load_df("SELECT * FROM products")
def get_sales(): return load_df("SELECT * FROM sales")
def get_sale_items(): return load_df("SELECT * FROM sale_items")
def get_waste(): return load_df("SELECT * FROM waste")

def kpi_cards():
    sales = get_sales(); si = get_sale_items(); prods = get_products()
    total_sales = sales['total'].sum() if not sales.empty else 0.0
    if not si.empty and not prods.empty:
        m = si.merge(prods[['id','unit_cost']], left_on='product_id', right_on='id', how='left')
        cogs = (m['qty']*m['unit_cost']).sum()
    else:
        cogs = 0.0
    margin = total_sales - cogs
    waste = get_waste(); wcost = (waste['qty']*waste['unit_cost_est']).sum() if not waste.empty else 0.0
    c1,c2,c3 = st.columns(3)
    c1.metric("Ventas (CLP)", f"{int(total_sales):,}".replace(",","."))
    c2.metric("Margen estimado (CLP)", f"{int(margin):,}".replace(",","."))
    c3.metric("Merma (CLP)", f"{int(wcost):,}".replace(",","."))

def _demand_stats_last_28d():
    sales = get_sales(); si = get_sale_items()
    if sales.empty or si.empty:
        return pd.DataFrame(columns=["product_id","mean_daily","std_daily"])
    sales['sold_at'] = pd.to_datetime(sales['sold_at'])
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=28)
    s28 = sales[sales['sold_at']>=cutoff]
    if s28.empty: return pd.DataFrame(columns=["product_id","mean_daily","std_daily"])
    m = si.merge(s28[['id','sold_at']], left_on='sale_id', right_on='id', how='inner')
    m['day'] = pd.to_datetime(m['sold_at']).dt.date
    g = m.groupby(['product_id','day'])['qty'].sum().reset_index()
    stats = g.groupby('product_id')['qty'].agg(['mean','std']).reset_index().rename(columns={'mean':'mean_daily','std':'std_daily'})
    stats['std_daily'] = stats['std_daily'].fillna(0.0)
    return stats

def _current_stock_by_product():
    lots = load_df("SELECT product_id, qty_current, status FROM lots")
    if lots.empty: return pd.DataFrame(columns=["product_id","stock"])
    lots = lots[lots['status']=='vigente']
    return lots.groupby('product_id')['qty_current'].sum().reset_index().rename(columns={'qty_current':'stock'})

def panel_repos_liq():
    st.markdown("### Reposiciones sugeridas (ROP) y productos a liquidar")
    prods = get_products(); stock = _current_stock_by_product(); stats = _demand_stats_last_28d()
    if prods.empty:
        st.info("No hay productos aún."); return
    df = prods.merge(stock, left_on='id', right_on='product_id', how='left').merge(stats, left_on='id', right_on='product_id', how='left')
    df['stock']=df['stock'].fillna(0); df['mean_daily']=df['mean_daily'].fillna(0.0); df['std_daily']=df['std_daily'].fillna(0.0)
    lead = st.number_input("Lead time (días)", 0, 30, 3); cover = st.number_input("Cobertura objetivo (días)", 1, 60, 7); z = st.number_input("Nivel servicio z", 0.0, 3.0, 1.28, 0.1)
    df['ROP'] = df['mean_daily']*lead + z*df['std_daily']
    df['sug_repo'] = (df['mean_daily']*cover + z*df['std_daily'] - df['stock']).clip(lower=0).round(0)
    df['necesita_repo'] = df['stock'] < df['ROP']
    cols = ["sku","name","category","stock","mean_daily","std_daily","ROP","sug_repo","necesita_repo"]
    repo_tbl = df[df['necesita_repo']].copy()
    if not repo_tbl.empty:
        st.write("**Reposiciones sugeridas** (últimas 4 semanas)")
        repo_view = repo_tbl[cols].sort_values("sug_repo", ascending=False)
        st.dataframe(repo_view); st.download_button("Exportar Reposiciones", repo_view.to_csv(index=False).encode("utf-8"), "reposiciones_sugeridas.csv")
    else:
        st.success("No hay reposiciones urgentes según ROP.")
    lots = load_df("SELECT product_id, lot_code, qty_current, expiration, status FROM lots WHERE status='vigente'")
    if not lots.empty:
        lots['expiration'] = pd.to_datetime(lots['expiration']); lots['days_left'] = (lots['expiration']-pd.Timestamp.now()).dt.days
        soon = lots[lots['days_left']<=7].copy()
        if not soon.empty:
            soon = soon.merge(prods[['id','sku','name']], left_on='product_id', right_on='id', how='left').merge(stats[['product_id','mean_daily']], left_on='product_id', right_on='product_id', how='left')
            soon['mean_daily']=soon['mean_daily'].fillna(0.0); soon['proj_demand_until_exp']=(soon['mean_daily']*soon['days_left'].clip(lower=0)).round(1)
            soon['exceso']=(soon['qty_current']-soon['proj_demand_until_exp']).round(0)
            liq = soon[soon['exceso']>0].copy()
            if not liq.empty:
                liq['sugerencia']="Aplicar promo/liquidación inmediata"
                st.write("**Productos a liquidar por vencimiento (≤7 días)**")
                liq_view = liq[["sku","name","lot_code","qty_current","days_left","proj_demand_until_exp","exceso","sugerencia"]].sort_values("exceso", ascending=False)
                st.dataframe(liq_view); st.download_button("Exportar Liquidaciones", liq_view.to_csv(index=False).encode("utf-8"), "liquidaciones_vencimiento.csv")
            else:
                st.success("No hay lotes con exceso previo al vencimiento.")
        else:
            st.success("No hay lotes con vencimiento en ≤7 días.")
    else:
        st.info("No hay lotes registrados.")


def panel_skus_bajo_margen():
    st.markdown("### SKUs bajo margen (precio vs costo y reglas)")
    prods = get_products()
    if prods.empty:
        st.info("No hay productos para evaluar.")
        return
    rows = []
    for _, r in prods.iterrows():
        req = _resolve_margin_for_product(r)
        if r['unit_cost'] is None or r['unit_cost'] <= 0:
            continue
        margen_real = (r['sale_price'] - r['unit_cost']) / r['unit_cost']
        if margen_real < req:
            precio_min = r['unit_cost'] * (1.0 + req)
            rows.append({
                "sku": r['sku'],
                "name": r['name'],
                "category": r['category'],
                "costo": int(r['unit_cost']),
                "precio_actual": int(r['sale_price']),
                "margen_actual_%": round(margen_real*100,1),
                "margen_requerido_%": int(req*100),
                "precio_sugerido_min": int(round(precio_min))
            })
    if rows:
        import pandas as pd
        df = pd.DataFrame(rows).sort_values("margen_actual_%")
        st.dataframe(df)
        st.download_button("Exportar SKUs bajo margen", data=df.to_csv(index=False).encode("utf-8"), file_name="skus_bajo_margen.csv")
        st.caption("Sugerencia: actualiza precio de venta desde **Productos** o diseña una promoción controlando margen.")
    else:
        st.success("Todos los SKUs cumplen el margen requerido.")


def weekly_monthly_reports():
    st.subheader("Análisis semanal y mensual")
    sales = get_sales()
    if sales.empty:
        st.info("No hay ventas para analizar."); return
    sales['sold_at'] = pd.to_datetime(sales['sold_at'])
    w = sales.groupby([sales['sold_at'].dt.to_period('W')])['total'].sum().reset_index()
    m = sales.groupby([sales['sold_at'].dt.to_period('M')])['total'].sum().reset_index()
    fig1 = plt.figure(); plt.plot(range(len(w)), w['total']); plt.title("Ventas semanales"); plt.xlabel("Semana"); plt.ylabel("CLP"); st.pyplot(fig1)
    fig2 = plt.figure(); plt.plot(range(len(m)), m['total']); plt.title("Ventas mensuales"); plt.xlabel("Mes"); plt.ylabel("CLP"); st.pyplot(fig2)

def expiry_alerts(days=7):
    df = load_df("SELECT l.id, p.name as producto, l.lot_code, l.qty_current, l.expiration FROM lots l JOIN products p ON l.product_id=p.id WHERE l.status='vigente'")
    if df.empty: return
    df['expiration'] = pd.to_datetime(df['expiration'])
    soon = df[(df['expiration'] - pd.Timestamp.now()) <= pd.Timedelta(days=days)]
    if not soon.empty:
        st.warning("Lotes por vencer (≤ {} días):".format(days)); st.dataframe(soon[['producto','lot_code','qty_current','expiration']])

def crud_productos():
    st.subheader("Productos")
    with st.form("add_prod"):
        c1,c2,c3 = st.columns(3)
        with c1:
            sku = st.text_input("SKU"); name = st.text_input("Nombre")
            category = st.selectbox("Categoría", ["Bebidas","Alimentos","Repostería","Materia Prima","Otros"])
        with c2:
            ptype = st.selectbox("Tipo", ["preparado","empacado","congelado","materia prima","otro"])
            shelf = st.number_input("Vida útil (días)", 0, 365, 3)
            unit_cost = st.number_input("Costo unitario (CLP)", 0, 10_000_000, 500)
        with c3:
            sale_price = st.number_input("Precio de venta (CLP)", 0, 10_000_000, 2500)
            min_stock = st.number_input("Stock mínimo (opcional)", 0, 100000, 0)
            unit_format = st.text_input("Formato (vaso, unidad, etc.)", "unidad")
        supplier_id = st.number_input("ID proveedor (opcional)", 0, 100000, 0)
        ok = st.form_submit_button("Agregar")
        if ok and sku and name:
            run_sql("""                INSERT OR IGNORE INTO products(sku,name,category,type,shelf_life_days,unit_cost,sale_price,min_stock,supplier_id,unit_format)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (sku,name,category,ptype,shelf,unit_cost,sale_price,(None if min_stock==0 else min_stock),(None if supplier_id==0 else supplier_id),unit_format), commit=True)
            st.success("Producto agregado."); log_audit('products', None, 'create', {'sku': sku, 'name': name})
    df = get_products(); st.dataframe(df)
    st.markdown('---'); st.write('**Editar producto**')
    edit_id = st.number_input('ID a editar', 0, 1_000_000, 0)
    if edit_id:
        row = run_sql('SELECT * FROM products WHERE id=?', (edit_id,))
        if not row.empty:
            e1,e2,e3 = st.columns(3)
            with e1:
                e_name = st.text_input('Nombre', row.loc[0,'name'])
                e_category = st.text_input('Categoría', row.loc[0,'category'])
                e_type = st.text_input('Tipo', row.loc[0,'type'])
            with e2:
                e_shelf = st.number_input('Vida útil (días)', 0, 365, int(row.loc[0,'shelf_life_days']))
                e_unit_cost = st.number_input('Costo unitario', 0, 10_000_000, int(row.loc[0,'unit_cost']))
                e_sale_price = st.number_input('Precio venta', 0, 10_000_000, int(row.loc[0,'sale_price']))
            with e3:
                e_min_stock = st.number_input('Stock mínimo', 0, 100000, int(row.loc[0,'min_stock']) if not pd.isna(row.loc[0,'min_stock']) else 0)
                e_supplier_id = st.number_input('Proveedor ID', 0, 100000, int(row.loc[0,'supplier_id']) if not pd.isna(row.loc[0,'supplier_id']) else 0)
                e_unit_format = st.text_input('Formato', row.loc[0,'unit_format'] or '')
            if st.button('Guardar cambios'):
                run_sql('UPDATE products SET name=?, category=?, type=?, shelf_life_days=?, unit_cost=?, sale_price=?, min_stock=?, supplier_id=?, unit_format=? WHERE id=?',
                        (e_name,e_category,e_type,int(e_shelf),float(e_unit_cost),float(e_sale_price),(None if e_min_stock==0 else e_min_stock),(None if e_supplier_id==0 else e_supplier_id),e_unit_format, int(edit_id)), commit=True)
                st.success('Producto actualizado.'); log_audit('products', edit_id, 'update', {'fields':'all'})
    del_id = st.text_input("ID a eliminar (producto)")
    if st.button("Eliminar producto") and del_id:
        run_sql("DELETE FROM products WHERE id=?", (del_id,), commit=True)
        st.success("Producto eliminado (si existía)."); log_audit('products', del_id, 'delete', {})

def compras_lotes():
    st.subheader("Compras y Lotes")
    prods = get_products()
    if prods.empty: st.info("Primero agrega productos."); return
    prod_map = dict(zip(prods['name'], prods['id']))
    with st.form("add_lot"):
        name = st.selectbox("Producto", list(prod_map.keys()))
        qty = st.number_input("Cantidad", 1, 1_000_000, 10)
        unit_cost = st.number_input("Costo unitario (CLP)", 0, 10_000_000, 500)
        received_at = st.date_input("Fecha de recepción", value=date.today())
        shelf = st.number_input("Vida útil (días)", 0, 365, 3)
        expiration = received_at + timedelta(days=int(shelf))
        supplier_id = st.number_input("ID proveedor", 0, 100000, 1)
        lot_code = st.text_input("Código lote", f"LOT-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        ok = st.form_submit_button("Registrar lote")
        if ok:
            run_sql("""                INSERT INTO lots(product_id, lot_code, received_at, expiration, qty_initial, qty_current, unit_cost, supplier_id, doc_ref, status)
                VALUES(?,?,?,?,?,?,?,?,?,?)
            """, (prod_map[name], lot_code, received_at.isoformat(), expiration.isoformat(), qty, qty, unit_cost, supplier_id, None, 'vigente'), commit=True)
            st.success("Lote ingresado."); log_audit('lots', None, 'create', {'lot_code': lot_code, 'product': name})
    lots = load_df("SELECT l.id, p.name as producto, l.lot_code, l.qty_initial, l.qty_current, l.unit_cost, l.received_at, l.expiration, l.status FROM lots l JOIN products p ON p.id=l.product_id ORDER BY datetime(l.received_at) DESC")
    st.dataframe(lots)
    st.markdown('---'); st.write('**Editar lote**')
    lot_id = st.number_input('ID lote a editar', 0, 1_000_000, 0)
    if lot_id:
        row = run_sql('SELECT * FROM lots WHERE id=?', (lot_id,))
        if not row.empty:
            c1,c2,c3 = st.columns(3)
            with c1:
                n_qty = st.number_input('Cantidad actual', 0, 1_000_000, int(row.loc[0,'qty_current']))
                n_status = st.selectbox('Estado', ['vigente','vendido','vencido','descartado'], index=['vigente','vendido','vencido','descartado'].index(row.loc[0,'status']))
            with c2:
                n_unit_cost = st.number_input('Costo unitario', 0, 10_000_000, int(row.loc[0,'unit_cost']))
            with c3:
                n_doc = st.text_input('Doc ref', row.loc[0,'doc_ref'] or '')
            if st.button('Guardar lote'):
                run_sql('UPDATE lots SET qty_current=?, status=?, unit_cost=?, doc_ref=? WHERE id=?', (int(n_qty), n_status, float(n_unit_cost), n_doc, int(lot_id)), commit=True)
                st.success('Lote actualizado.'); log_audit('lots', lot_id, 'update', {})
    del_lot = st.number_input('ID lote a eliminar', 0, 1_000_000, 0, key='del_lot')
    if st.button('Eliminar lote') and del_lot:
        run_sql('DELETE FROM lots WHERE id=?', (int(del_lot),), commit=True)
        st.success('Lote eliminado (si existía).'); log_audit('lots', del_lot, 'delete', {})

def ventas():
    st.subheader("Ventas")
    prods = get_products()
    if prods.empty: st.info("Primero agrega productos."); return
    prod_map = dict(zip(prods['name'], prods[['id','sale_price']].values))
    with st.form("venta_rapida"):
        name = st.selectbox("Producto", list(prod_map.keys()))
        qty = st.number_input("Cantidad", 1, 1_000_000, 1)
        sold_at = st.datetime_input("Fecha y hora", value=datetime.now())
        payment = st.selectbox("Medio de pago", ["efectivo","tarjeta","mixto"])
        ok = st.form_submit_button("Registrar venta")
        if ok:
            pid, price = prod_map[name]
            with conn() as c:
                cur = c.cursor()
                lots = cur.execute("""                    SELECT id, qty_current FROM lots WHERE product_id=? AND status='vigente' ORDER BY datetime(expiration) ASC
                """, (int(pid),)).fetchall()
                remain = qty
                for lot_id, qty_cur in lots:
                    if remain<=0: break
                    take = min(remain, qty_cur)
                    cur.execute("UPDATE lots SET qty_current=qty_current-? WHERE id=?", (take, lot_id))
                    remain -= take
                total = qty * price
                cur.execute("INSERT INTO sales(sold_at, channel, payment_method, receipt_no, total) VALUES(?,?,?,?,?)",
                            (sold_at.isoformat(),"local",payment,None,total))
                sale_id = cur.lastrowid
                cur.execute("INSERT INTO sale_items(sale_id, product_id, lot_id, qty, unit_price, promo_id) VALUES(?,?,?,?,?,NULL)",
                            (sale_id, int(pid), None, int(qty), float(price)))
                c.commit()
            st.success("Venta registrada."); log_audit('sales', None, 'create', {'product': name, 'qty': int(qty)})
    sales = load_df("SELECT * FROM sales ORDER BY datetime(sold_at) DESC LIMIT 200"); st.dataframe(sales)
    st.markdown('---'); st.write('**Editar venta**')
    sale_id = st.number_input('ID venta a editar', 0, 1_000_000, 0)
    if sale_id:
        row = run_sql('SELECT * FROM sales WHERE id=?', (sale_id,))
        if not row.empty:
            pm = st.selectbox('Medio de pago', ['efectivo','tarjeta','mixto'], index=['efectivo','tarjeta','mixto'].index(row.loc[0,'payment_method'] if row.loc[0,'payment_method'] in ['efectivo','tarjeta','mixto'] else 'mixto'))
            if st.button('Guardar venta'):
                run_sql('UPDATE sales SET payment_method=? WHERE id=?', (pm, int(sale_id)), commit=True)
                st.success('Venta actualizada.'); log_audit('sales', sale_id, 'update', {'payment_method': pm})
    del_sale = st.number_input('ID venta a eliminar', 0, 1_000_000, 0, key='del_sale')
    if st.button('Eliminar venta') and del_sale:
        run_sql('DELETE FROM sales WHERE id=?', (int(del_sale),), commit=True)
        st.success('Venta eliminada (si existía).'); log_audit('sales', del_sale, 'delete', {})

def mermas():
    st.subheader("Mermas")
    prods = get_products()
    if prods.empty: st.info("Primero agrega productos."); return
    prod_map = dict(zip(prods['name'], prods[['id','unit_cost']].values))
    with st.form("add_waste"):
        name = st.selectbox("Producto", list(prod_map.keys()))
        qty = st.number_input("Cantidad descartada", 1, 1_000_000, 1)
        ts = st.datetime_input("Fecha/hora", value=datetime.now())
        reason = st.selectbox("Motivo", ["caducidad","daño","preparación"])
        shift = st.selectbox("Turno", ["mañana","tarde","noche"])
        ok = st.form_submit_button("Registrar merma")
        if ok:
            pid, ucost = prod_map[name]
            run_sql("""                INSERT INTO waste(ts, product_id, lot_id, qty, unit_cost_est, reason, shift, evidence_path, approved_by)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (ts.isoformat(), int(pid), None, int(qty), float(ucost), reason, shift, None, "sistema"), commit=True)
            st.success("Merma registrado."); log_audit('waste', None, 'create', {'product': name, 'qty': int(qty), 'reason': reason})
    w = load_df("SELECT w.id, p.name as producto, w.qty, w.unit_cost_est, w.reason, w.ts FROM waste w JOIN products p ON p.id=w.product_id ORDER BY datetime(w.ts) DESC")
    st.dataframe(w)
    st.markdown('---'); st.write('**Editar merma**')
    wid = st.number_input('ID merma a editar', 0, 1_000_000, 0)
    if wid:
        row = run_sql('SELECT * FROM waste WHERE id=?', (wid,))
        if not row.empty:
            qty_n = st.number_input('Cantidad', 1, 1_000_000, int(row.loc[0,'qty']))
            reason_n = st.selectbox('Motivo', ['caducidad','daño','preparación'], index=['caducidad','daño','preparación'].index(row.loc[0,'reason'] if row.loc[0,'reason'] in ['caducidad','daño','preparación'] else 'caducidad'))
            if st.button('Guardar merma'):
                run_sql('UPDATE waste SET qty=?, reason=? WHERE id=?', (int(qty_n), reason_n, int(wid)), commit=True)
                st.success('Merma actualizada.'); log_audit('waste', wid, 'update', {})
    del_w = st.number_input('ID merma a eliminar', 0, 1_000_000, 0, key='del_w')
    if st.button('Eliminar merma') and del_w:
        run_sql('DELETE FROM waste WHERE id=?', (int(del_w),), commit=True)
        st.success('Merma eliminada (si existía).'); log_audit('waste', del_w, 'delete', {})

def _resolve_margin_for_product(prod_row):
    """Precedencia: producto > categoría > global (settings.margin_min_percent, default 0.22)"""
    settings = load_df("SELECT key, value FROM settings")
    m_global = 0.22
    if not settings.empty and 'margin_min_percent' in set(settings['key']):
        try:
            m_global = float(settings[settings['key']=='margin_min_percent']['value'].iloc[0])
        except:
            pass
    cat_margin = None
    try:
        mr = load_df("SELECT margin_min_percent FROM margin_rules WHERE scope='category' AND ref=?", (prod_row['category'],))
        if not mr.empty:
            cat_margin = float(mr['margin_min_percent'].iloc[0])
    except Exception:
        pass
    prod_margin = None
    try:
        mrp = load_df("SELECT margin_min_percent FROM margin_rules WHERE scope='product' AND ref=?", (str(prod_row['id']),))
        if not mrp.empty:
            prod_margin = float(mrp['margin_min_percent'].iloc[0])
    except Exception:
        pass
    return prod_margin if prod_margin is not None else (cat_margin if cat_margin is not None else m_global)

def promos():
    st.subheader("Promociones")
    with st.form("add_promo"):
        name = st.text_input("Nombre", "Happy Hour Bebidas")
        typ = st.selectbox("Tipo", ["%","combo","precio_fijo"])
        value = st.number_input("Valor", 0.0, 1000000.0, 20.0, 1.0)
        starts = st.datetime_input("Inicio", value=datetime.now())
        ends = st.datetime_input("Fin", value=datetime.now()+timedelta(days=7))
        ok = st.form_submit_button("Guardar promoción")
        if ok:
            settings = load_df("SELECT key, value FROM settings"); mmin=0.22
            if not settings.empty and 'margin_min_percent' in set(settings['key']):
                try: mmin=float(settings[settings['key']=='margin_min_percent']['value'].iloc[0])
                except: pass
            if typ == '%':
                prods = get_products(); low=[]
                for _,r in prods.iterrows():
                    pe = r['sale_price']*(1-value/100.0)
                    if r['unit_cost']<=0: continue
                    margen = (pe - r['unit_cost'])/r['unit_cost']
                    req = _resolve_margin_for_product(r)
                    if margen < req: low.append(f"{r['name']} (req {int(req*100)}%)")
                if low:
                    st.error(f"La promo podría violar margen mínimo ({int(mmin*100)}%) en: {', '.join(low[:5])}...")
                else:
                    run_sql("INSERT INTO promos(name,type,value,starts_at,ends_at,notes) VALUES(?,?,?,?,?,?)", (name, typ, value, starts.isoformat(), ends.isoformat(), None), commit=True)
                    st.success("Promoción creada."); log_audit('promos', None, 'create', {'name': name, 'type': typ, 'value': value})
            else:
                run_sql("INSERT INTO promos(name,type,value,starts_at,ends_at,notes) VALUES(?,?,?,?,?,?)", (name, typ, value, starts.isoformat(), ends.isoformat(), None), commit=True)
                st.success("Promoción creada."); log_audit('promos', None, 'create', {'name': name, 'type': typ, 'value': value})
    p = load_df("SELECT * FROM promos ORDER BY datetime(starts_at) DESC"); st.dataframe(p)
    st.markdown('---'); st.write('**Editar promoción**')
    pid = st.number_input('ID promo a editar', 0, 1_000_000, 0)
    if pid:
        row = run_sql('SELECT * FROM promos WHERE id=?', (pid,))
        if not row.empty:
            name_n = st.text_input('Nombre', row.loc[0,'name'])
            type_n = st.text_input('Tipo', row.loc[0,'type'])
            value_n = st.number_input('Valor', 0.0, 1000000.0, float(row.loc[0,'value']))
            notes_n = st.text_area('Notas', row.loc[0,'notes'] or '')
            if st.button('Guardar promo'):
                run_sql('UPDATE promos SET name=?, type=?, value=?, notes=? WHERE id=?', (name_n, type_n, float(value_n), notes_n, int(pid)), commit=True)
                st.success('Promoción actualizada.'); log_audit('promos', pid, 'update', {})
    del_p = st.number_input('ID promo a eliminar', 0, 1_000_000, 0, key='del_p')
    if st.button('Eliminar promoción') and del_p:
        run_sql('DELETE FROM promos WHERE id=?', (int(del_p),), commit=True)
        st.success('Promoción eliminada (si existía).'); log_audit('promos', del_p, 'delete', {})

def proveedores():
    st.subheader("Proveedores")
    with st.form("add_supplier"):
        name = st.text_input("Nombre proveedor"); contact = st.text_input("Contacto")
        freq = st.selectbox("Frecuencia", ["semanal","quincenal","mensual","bajo demanda"]); notes = st.text_area("Notas","")
        ok = st.form_submit_button("Agregar proveedor")
        if ok and name:
            run_sql("INSERT INTO suppliers(name, contact, frequency, notes) VALUES(?,?,?,?)", (name, contact, freq, notes), commit=True)
            st.success("Proveedor agregado."); log_audit('suppliers', None, 'create', {'name': name})
    sup = load_df("SELECT * FROM suppliers"); st.dataframe(sup)
    st.markdown('---'); st.write('**Editar proveedor**')
    sid = st.number_input('ID proveedor a editar', 0, 1_000_000, 0)
    if sid:
        row = run_sql('SELECT * FROM suppliers WHERE id=?', (sid,))
        if not row.empty:
            name_n = st.text_input('Nombre', row.loc[0,'name'])
            contact_n = st.text_input('Contacto', row.loc[0,'contact'])
            freq_n = st.text_input('Frecuencia', row.loc[0,'frequency'])
            notes_n = st.text_area('Notas', row.loc[0,'notes'] or '')
            if st.button('Guardar proveedor'):
                run_sql('UPDATE suppliers SET name=?, contact=?, frequency=?, notes=? WHERE id=?', (name_n, contact_n, freq_n, notes_n, int(sid)), commit=True)
                st.success('Proveedor actualizado.'); log_audit('suppliers', sid, 'update', {})
    del_s = st.number_input('ID proveedor a eliminar', 0, 1_000_000, 0, key='del_s')
    if st.button('Eliminar proveedor') and del_s:
        run_sql('DELETE FROM suppliers WHERE id=?', (int(del_s),), commit=True)
        st.success('Proveedor eliminado (si existía).'); log_audit('suppliers', del_s, 'delete', {})

def import_export():
    st.subheader("Importar / Exportar CSV")
    tab1, tab2 = st.tabs(["Importar", "Exportar"])
    with tab1:
        kind = st.selectbox("Tabla a importar", ["products","lots","sales","sale_items","waste","promos","suppliers"])
        file = st.file_uploader("CSV", type=["csv"])
        if file is not None:
            df = pd.read_csv(file)
            with conn() as c: df.to_sql(kind, c, if_exists="append", index=False)
            st.success(f"{len(df)} filas importadas a {kind}.")
    with tab2:
        kind = st.selectbox("Tabla a exportar", ["products","lots","sales","sale_items","waste","promos","suppliers","audit"])
        if st.button("Exportar CSV"):
            df = load_df(f"SELECT * FROM {kind}")
            st.download_button("Descargar CSV", df.to_csv(index=False).encode("utf-8"), file_name=f"{kind}.csv")

def ajustes_reportes():
    _ensure_scheduler()
    st.subheader("Ajustes & Reportes")
    st.caption("Configura correo, genera/envía reportes y gestiona respaldos.")
    cfg_path = Path("email_config.json")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {"smtp_host":"smtp.gmail.com","smtp_port":587,"username":"","password":"","to_emails":[],"scheduler_enabled":False}
    with st.form("email_cfg"):
        st.write("**Correo (SMTP)**")
        smtp_host = st.text_input("SMTP Host", cfg.get("smtp_host","smtp.gmail.com"))
        smtp_port = st.number_input("SMTP Port", 1, 65535, int(cfg.get("smtp_port",587)))
        username = st.text_input("Usuario (correo)", cfg.get("username",""))
        password = st.text_input("Contraseña de aplicación", value=cfg.get("password",""), type="password")
        to_emails = st.text_input("Destinatarios (separados por coma)", ", ".join(cfg.get("to_emails", [])))
        scheduler_enabled = st.checkbox("Activar envío programado (lun 08:00 y día 1 08:00)", value=bool(cfg.get("scheduler_enabled", False)))
        saved = st.form_submit_button("Guardar configuración")
        if saved:
            new_cfg = {"smtp_host": smtp_host, "smtp_port": int(smtp_port), "username": username, "password": password, "to_emails": [e.strip() for e in to_emails.split(",") if e.strip()], "scheduler_enabled": bool(scheduler_enabled)}
            cfg_path.write_text(json.dumps(new_cfg, indent=2), encoding="utf-8")
            st.success("Configuración guardada (puedes cambiarla cuando quieras).")
    st.divider(); st.write("**Reportes**")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Generar PDF semanal/mensual"):
            pdf_path = build_weekly_monthly_pdf(load_df, out_path="resumen_pascucci.pdf")
            st.success(f"PDF generado: {pdf_path}")
            with open(pdf_path, "rb") as f: st.download_button("Descargar PDF", data=f.read(), file_name="resumen_pascucci.pdf")
        if st.button("Generar PDF Ejecutivo (branding + acciones)"):
            pdf2 = build_executive_pdf(load_df, out_path="resumen_ejecutivo.pdf")
            st.success(f"PDF ejecutivo generado: {pdf2}")
            with open(pdf2, "rb") as f: st.download_button("Descargar PDF Ejecutivo", data=f.read(), file_name="resumen_ejecutivo.pdf")
    with col2:
        if st.button("Enviar PDF por correo (usar configuración guardada)"):
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                pdf_path = build_weekly_monthly_pdf(load_df, out_path="resumen_pascucci.pdf")
                try:
                    send_email(cfg["smtp_host"], int(cfg["smtp_port"]), cfg["username"], cfg["password"], cfg.get("to_emails", []),
                               subject="[Pascucci Smart Inventory] Resumen automático",
                               body="Se adjunta el resumen automático semanal/mensual.",
                               attachments=[pdf_path])
                    st.success("Correo enviado.")
                except Exception as e:
                    st.error(f"Error al enviar correo: {e}")
            else:
                st.error("Primero guarda la configuración de correo.")

    st.divider(); st.write("**Parámetros del sistema**")
    st.caption("Define margen mínimo permitido a nivel global, por categoría o por producto (precedencia: producto > categoría > global).")
    tabs = st.tabs(["Global","Por categoría","Por producto"])  # Tabs Márgenes
    # Lee el margen actual desde settings; por defecto 0.22 (22%)
    s = load_df("SELECT key, value FROM settings")
    cur_m = 0.22
    if not s.empty and 'margin_min_percent' in set(s['key']):
        try:
            cur_m = float(s[s['key']=='margin_min_percent']['value'].iloc[0])
        except:
            pass
    colm1, colm2 = st.columns([2,1])
    with colm1:
        m_input = st.number_input("Margen mínimo permitido (%)", min_value=0.0, max_value=95.0, value=float(int(cur_m*100))/1.0, step=1.0, help="Protege que las promociones no dejen el margen por debajo de este umbral.")
    with colm2:
        if st.button("Guardar margen"):
            new_val = float(m_input)/100.0
            run_sql("INSERT OR REPLACE INTO settings(key, value) VALUES(?,?)", ("margin_min_percent", str(new_val)), commit=True)
            st.success(f"Margen mínimo actualizado a {m_input:.0f}%")
    

    with tabs[1]:
        st.write("**Márgenes por categoría**")
        cats = load_df("SELECT DISTINCT category FROM products WHERE category IS NOT NULL AND category<>''")
        if cats.empty:
            st.info("No hay categorías definidas (agrega productos primero).")
        else:
            for cat in cats['category'].tolist():
                cur = load_df("SELECT margin_min_percent FROM margin_rules WHERE scope='category' AND ref=?", (cat,))
                curv = float(cur['margin_min_percent'].iloc[0]) if not cur.empty else cur_m
                c1,c2,c3 = st.columns([2,1,1])
                with c1:
                    st.write(f"Categoría: **{cat}**")
                with c2:
                    v = st.number_input(f"Margen (%) — {cat}", min_value=0.0, max_value=95.0, value=float(int(curv*100))/1.0, step=1.0, key=f"mcat_{cat}")
                with c3:
                    if st.button(f"Guardar {cat}", key=f"save_cat_{cat}"):
                        run_sql("INSERT OR REPLACE INTO margin_rules(scope, ref, margin_min_percent) VALUES('category', ?, ?)", (cat, float(v)/100.0), commit=True)
                        st.success(f"Guardado margen categoría {cat}: {v:.0f}%")

    with tabs[2]:
        st.write("**Márgenes por producto (override)**")
        prods = load_df("SELECT id, sku, name FROM products ORDER BY name ASC")
        if prods.empty:
            st.info("No hay productos aún.")
        else:
            names = prods['name'].tolist()
            sel = st.selectbox("Producto", names)
            row = prods[prods['name']==sel].iloc[0]
            curp = load_df("SELECT margin_min_percent FROM margin_rules WHERE scope='product' AND ref=?", (str(row['id']),))
            curv = float(curp['margin_min_percent'].iloc[0]) if not curp.empty else cur_m
            c1,c2,c3 = st.columns([2,1,1])
            with c1:
                st.write(f"Producto: **{row['name']}** (SKU {row['sku']})")
            with c2:
                vp = st.number_input("Margen (%) — producto", min_value=0.0, max_value=95.0, value=float(int(curv*100))/1.0, step=1.0)
            with c3:
                if st.button("Guardar margen producto"):
                    run_sql("INSERT OR REPLACE INTO margin_rules(scope, ref, margin_min_percent) VALUES('product', ?, ?)", (str(row['id']), float(vp)/100.0), commit=True)
                    st.success(f"Guardado margen producto: {vp:.0f}%")
            if st.button("Eliminar override del producto"):
                run_sql("DELETE FROM margin_rules WHERE scope='product' AND ref=?", (str(row['id']),), commit=True)
                st.success("Override eliminado (aplicará categoría o global).")
    st.divider(); st.write("**Respaldos**")
    if st.button("Respaldar ahora (.db)"):
        import shutil
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        os.makedirs("backups", exist_ok=True)
        dst = f"backups/pascucci_{ts}.db"
        shutil.copyfile(DB, dst)
        st.success(f"Respaldo creado: {dst}")
        with open(dst, "rb") as f: st.download_button("Descargar respaldo", data=f.read(), file_name=f"pascucci_{ts}.db")

def audit_view():
    st.subheader("Auditoría")
    df = load_df("SELECT id, ts, user, entity, entity_id, action, diff_json FROM audit ORDER BY datetime(ts) DESC LIMIT 1000")
    if df.empty: st.info("Sin registros de auditoría."); return
    st.dataframe(df); st.download_button("Exportar auditoría CSV", df.to_csv(index=False).encode("utf-8"), "auditoria.csv")

# Render
if section == "Dashboard":
    kpi_cards(); panel_skus_bajo_margen(); expiry_alerts(7); panel_repos_liq(); weekly_monthly_reports()
elif section == "Productos":
    crud_productos()
elif section == "Compras/Lotes":
    compras_lotes()
elif section == "Ventas":
    ventas()
elif section == "Mermas":
    mermas()
elif section == "Promociones":
    promos()
elif section == "Proveedores":
    proveedores()
elif section == "Importar/Exportar":
    import_export()
elif section == "Ajustes & Reportes":
    ajustes_reportes()
elif section == "Auditoría":
    audit_view()
