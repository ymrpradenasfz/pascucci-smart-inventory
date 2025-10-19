import sqlite3, random, math
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

DB = "pascucci.db"
random.seed(7)
np.random.seed(7)

def connect():
    return sqlite3.connect(DB)

def seed_settings(conn):
    cur = conn.cursor()
    settings = [
        ("currency", "CLP"),
        ("iva_percent", "0"),
        ("alert_days_expiry", "7"),
        ("report_weekly_day_hour", "1|08:00"),
        ("report_monthly_day_hour", "1|08:00"),
        ("email_to", "dueno@pascucci.cl;finanzas@pascucci.cl"),
        ("margin_min_percent", "0.22")
    ]
    for k,v in settings:
        cur.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k,v))
    conn.commit()

def seed_suppliers(conn):
    suppliers = [
        ("Café y Tostadores Ltda.", "ventas@tostadores.cl / +56 9 5555 1111", "semanal", ""),
        ("Panadería Central", "contacto@panacentral.cl / +56 2 2222 3333", "semanal", ""),
        ("Lácteos del Sur", "ventas@lacteossur.cl / +56 9 4444 2222", "quincenal", ""),
        ("Frescos del Valle", "frutas@fvalle.cl / +56 9 7777 2222", "semanal", "")
    ]
    cur = conn.cursor()
    for s in suppliers:
        cur.execute("INSERT INTO suppliers(name, contact, frequency, notes) VALUES(?,?,?,?)", s)
    conn.commit()

def seed_products(conn):
    products = [
        ("PSI-101", "Capuccino", "Bebidas", "preparado", 3, 600, 2900, 18, 1, "vaso"),
        ("PSI-102", "Chocolate Caliente", "Bebidas", "preparado", 3, 700, 3000, 16, 1, "vaso"),
        ("PSI-103", "Croissant", "Repostería", "empacado", 3, 750, 2300, 12, 2, "unidad"),
        ("PSI-104", "Jugo de Naranja", "Bebidas", "preparado", 2, 550, 2700, 10, 4, "vaso"),
        ("PSI-105", "Cheesecake Frutos del Bosque (porción)", "Repostería", "empacado", 4, 1600, 4200, 6, 2, "porción"),
        ("PSI-106", "Ensalada César Romana", "Alimentos", "empacado", 2, 1900, 5200, 6, 2, "unidad"),
        ("PSI-107", "Café", "Bebidas", "preparado", 3, 350, 1800, 18, 1, "vaso"),
        ("PSI-108", "Copa de Helado", "Alimentos", "empacado", 4, 1200, 3800, 8, 2, "unidad"),
        ("PSI-109", "Torta Chocolate (porción)", "Repostería", "empacado", 4, 1400, 3900, 6, 2, "porción"),
        ("PSI-110", "Rollos estilo New York", "Repostería", "empacado", 3, 900, 3200, 8, 2, "unidad")
    ]
    cur = conn.cursor()
    for p in products:
        cur.execute("""            INSERT INTO products(sku,name,category,type,shelf_life_days,unit_cost,sale_price,min_stock,supplier_id,unit_format)
            VALUES(?,?,?,?,?,?,?,?,?,?)
        """, p)
    conn.commit()

def create_purchase_with_lots(conn, received_at, supplier_id, items):
    cur = conn.cursor()
    cur.execute("INSERT INTO purchases(received_at, supplier_id, total_cost) VALUES(?,?,?)",
                (received_at, supplier_id, 0.0))
    purchase_id = cur.lastrowid
    total_cost = 0.0
    for it in items:
        pid = cur.execute("SELECT id, shelf_life_days FROM products WHERE sku=?", (it['sku'],)).fetchone()
        if not pid: continue
        product_id, sld = pid
        expiration = (datetime.fromisoformat(received_at) + timedelta(days=sld or 3)).isoformat()
        lot_code = f"LOT-{it['sku']}-{received_at[:10]}-{int(np.random.randint(1000,9999))}"
        cur.execute("""            INSERT INTO lots(product_id, lot_code, received_at, expiration, qty_initial, qty_current, unit_cost, supplier_id, doc_ref, status)
            VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (product_id, lot_code, received_at, expiration, it['qty'], it['qty'], it['unit_cost'], supplier_id, None, 'vigente'))
        lot_id = cur.lastrowid
        cur.execute("""            INSERT INTO purchase_items(purchase_id, product_id, lot_id, qty, unit_cost)
            VALUES(?,?,?,?,?)
        """, (purchase_id, product_id, lot_id, it['qty'], it['unit_cost']))
        total_cost += it['qty'] * it['unit_cost']
    cur.execute("UPDATE purchases SET total_cost=? WHERE id=?", (total_cost, purchase_id))
    conn.commit()

def fefo_consume(conn, product_id, qty_needed):
    cur = conn.cursor()
    lots = cur.execute("""        SELECT id, qty_current FROM lots
        WHERE product_id=? AND status='vigente' AND (expiration IS NULL OR expiration >= ?)
        ORDER BY datetime(expiration) ASC
    """, (product_id, datetime.now().isoformat())).fetchall()
    remain = qty_needed
    used_lots = []
    for lot_id, qty_cur in lots:
        if remain<=0: break
        take = min(remain, qty_cur)
        cur.execute("UPDATE lots SET qty_current=qty_current-? WHERE id=?", (take, lot_id))
        used_lots.append((lot_id, take))
        remain -= take
    if remain>0:
        # fallback
        lots2 = cur.execute("""            SELECT id, qty_current FROM lots
            WHERE product_id=? AND status='vigente'
            ORDER BY datetime(received_at) ASC
        """, (product_id,)).fetchall()
        for lot_id, qty_cur in lots2:
            if remain<=0: break
            if qty_cur<=0: continue
            take = min(remain, qty_cur)
            cur.execute("UPDATE lots SET qty_current=qty_current-? WHERE id=?", (take, lot_id))
            used_lots.append((lot_id, take))
            remain -= take
    conn.commit()
    return used_lots, remain<=0

def seed_sales_mermas_promos(conn, start_date, weeks=26):
    cur = conn.cursor()
    # purchases every 2 weeks
    for w in range(0, weeks, 2):
        recv = (start_date + timedelta(days=w*7)).isoformat()
        cost_map = dict(cur.execute("SELECT sku, unit_cost FROM products").fetchall())
        qtys = {"PSI-101":120,"PSI-102":80,"PSI-103":80,"PSI-104":70,"PSI-105":30,"PSI-106":40,"PSI-107":130,"PSI-108":50,"PSI-109":30,"PSI-110":90}
        items = [{"sku":sku,"qty":qtys.get(sku,40),"unit_cost":float(cost_map[sku])} for sku in cost_map.keys()]
        create_purchase_with_lots(conn, recv+"T09:00:00", 1, items)

    cur.execute("""        INSERT INTO promos(name,type,value,starts_at,ends_at,notes)
        VALUES(?,?,?,?,?,?)
    """, ("Happy Hour Bebidas", "%", 15, (start_date+timedelta(weeks=8)).isoformat()+"T16:00:00",
           (start_date+timedelta(weeks=9)).isoformat()+"T18:00:00", "16:00-18:00 en bebidas"))
    conn.commit()

    means = {"PSI-101":12,"PSI-107":14,"PSI-110":8,"PSI-102":7,"PSI-103":7,"PSI-104":6,"PSI-106":5,"PSI-108":5,"PSI-105":2,"PSI-109":2}

    for d in range(weeks*7):
        day = start_date + timedelta(days=d)
        weekend = 1.2 if day.weekday()>=5 else 1.0
        trend = 1.0 + 0.08*np.sin(2*np.pi*d/30.0)
        for hour in range(8,20,2):
            sale_total = 0.0; has_items=False
            for sku, mu in means.items():
                mu_b = mu*weekend*trend/6.0
                qty = int(np.random.poisson(mu_b))
                if qty<=0: continue
                pid, price = cur.execute("SELECT id, sale_price FROM products WHERE sku=?", (sku,)).fetchone()
                fefo_consume(conn, pid, qty)
                sale_total += qty*float(price)
                has_items = True
            if has_items:
                ts = datetime(day.year, day.month, day.day, hour, 0, 0).isoformat()
                cur.execute("INSERT INTO sales(sold_at, channel, payment_method, receipt_no, total) VALUES(?,?,?,?,?)",
                            (ts,"local","mixto",None,sale_total))
                sale_id = cur.lastrowid
                # distribute items again for sale_items (approximate)
                for sku, mu in means.items():
                    mu_b = mu*weekend*trend/6.0
                    qty = int(np.random.poisson(mu_b))
                    if qty<=0: continue
                    pid, price = cur.execute("SELECT id, sale_price FROM products WHERE sku=?", (sku,)).fetchone()
                    cur.execute("INSERT INTO sale_items(sale_id, product_id, lot_id, qty, unit_price, promo_id) VALUES(?,?,?,?,?,NULL)",
                                (sale_id, pid, None, qty, float(price)))
        # waste for low-demand items
        for sku, p in [("PSI-105",0.30),("PSI-109",0.28),("PSI-103",0.12),("PSI-108",0.12)]:
            if random.random() < p*0.15:
                pid, ucost = cur.execute("SELECT id, unit_cost FROM products WHERE sku=?", (sku,)).fetchone()
                qty = max(1, int(np.random.poisson(2)))
                cur.execute("""                    INSERT INTO waste(ts, product_id, lot_id, qty, unit_cost_est, reason, shift, evidence_path, approved_by)
                    VALUES(?,?,?,?,?,?,?,?,?)
                """, (datetime(day.year, day.month, day.day, 20, 0, 0).isoformat(), pid, None, qty, float(ucost), "caducidad", "tarde", None, "sistema"))
    conn.commit()

def main():
    conn = connect()
    conn.executescript(open("init_db.sql","r",encoding="utf-8").read())
    seed_settings(conn); seed_suppliers(conn); seed_products(conn)
    start_date = (datetime.now() - timedelta(weeks=26)).date()
    seed_sales_mermas_promos(conn, start_date, weeks=26)
    print("Seeded 6 months for specified products.")

if __name__ == "__main__":
    main()
