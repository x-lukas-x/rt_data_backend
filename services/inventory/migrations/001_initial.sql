CREATE TABLE IF NOT EXISTS products (
    product_id TEXT PRIMARY KEY,
    product_name TEXT NOT NULL,
    stock_quantity INTEGER NOT NULL CHECK (stock_quantity >= 0),
    unit_price NUMERIC(12, 2) NOT NULL CHECK (unit_price >= 0),
    csv_row INTEGER UNIQUE
);

CREATE TABLE IF NOT EXISTS import_runs (
    import_name TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    product_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'accepted', 'rejected')),
    product_id TEXT NOT NULL,
    message TEXT,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sales (
    event_id TEXT PRIMARY KEY REFERENCES processed_events(event_id),
    shop_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES products(product_id),
    amount NUMERIC(12, 2) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS restocks (
    event_id TEXT PRIMARY KEY REFERENCES processed_events(event_id),
    shop_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES products(product_id),
    quantity INTEGER NOT NULL CHECK (quantity = 100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS market_revenue (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0
);
INSERT INTO market_revenue(singleton, amount) VALUES (TRUE, 0) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS shop_revenue (
    shop_id TEXT PRIMARY KEY,
    amount NUMERIC(14, 2) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS warning_outbox (
    warning_id TEXT PRIMARY KEY,
    source_event_id TEXT NOT NULL UNIQUE REFERENCES sales(event_id),
    shop_id TEXT NOT NULL,
    product_id TEXT NOT NULL REFERENCES products(product_id),
    stock_quantity INTEGER NOT NULL,
    published_at TIMESTAMPTZ
);