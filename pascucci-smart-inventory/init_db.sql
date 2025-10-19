PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sku TEXT UNIQUE,
  name TEXT,
  category TEXT,
  type TEXT,
  shelf_life_days INTEGER,
  unit_cost REAL,
  sale_price REAL,
  min_stock INTEGER,
  supplier_id INTEGER,
  unit_format TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS suppliers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  contact TEXT,
  frequency TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS lots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id INTEGER,
  lot_code TEXT,
  received_at DATETIME,
  expiration DATETIME,
  qty_initial INTEGER,
  qty_current INTEGER,
  unit_cost REAL,
  supplier_id INTEGER,
  doc_ref TEXT,
  status TEXT CHECK(status IN ('vigente','vendido','vencido','descartado')) DEFAULT 'vigente',
  FOREIGN KEY(product_id) REFERENCES products(id),
  FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
);

CREATE TABLE IF NOT EXISTS purchases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at DATETIME,
  supplier_id INTEGER,
  total_cost REAL,
  FOREIGN KEY(supplier_id) REFERENCES suppliers(id)
);

CREATE TABLE IF NOT EXISTS purchase_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  purchase_id INTEGER,
  product_id INTEGER,
  lot_id INTEGER,
  qty INTEGER,
  unit_cost REAL,
  FOREIGN KEY(purchase_id) REFERENCES purchases(id),
  FOREIGN KEY(product_id) REFERENCES products(id),
  FOREIGN KEY(lot_id) REFERENCES lots(id)
);

CREATE TABLE IF NOT EXISTS sales (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sold_at DATETIME,
  channel TEXT,
  payment_method TEXT,
  receipt_no TEXT,
  total REAL
);

CREATE TABLE IF NOT EXISTS sale_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sale_id INTEGER,
  product_id INTEGER,
  lot_id INTEGER,
  qty INTEGER,
  unit_price REAL,
  promo_id INTEGER,
  FOREIGN KEY(sale_id) REFERENCES sales(id),
  FOREIGN KEY(product_id) REFERENCES products(id)
);

CREATE TABLE IF NOT EXISTS waste (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts DATETIME,
  product_id INTEGER,
  lot_id INTEGER,
  qty INTEGER,
  unit_cost_est REAL,
  reason TEXT,
  shift TEXT,
  evidence_path TEXT,
  approved_by TEXT,
  FOREIGN KEY(product_id) REFERENCES products(id),
  FOREIGN KEY(lot_id) REFERENCES lots(id)
);

CREATE TABLE IF NOT EXISTS promos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  type TEXT,
  value REAL,
  starts_at DATETIME,
  ends_at DATETIME,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
);

CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts DATETIME DEFAULT CURRENT_TIMESTAMP,
  user TEXT,
  entity TEXT,
  entity_id INTEGER,
  action TEXT,
  diff_json TEXT
);


CREATE TABLE IF NOT EXISTS margin_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT CHECK(scope IN ('category','product')) NOT NULL,
  ref TEXT NOT NULL,
  margin_min_percent REAL NOT NULL
);
