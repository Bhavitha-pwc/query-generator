-- Synthetic retail/e-commerce schema. This is the full universe of data the
-- generator is allowed to reason about. See CLAUDE.md "Scope boundary".

CREATE TABLE customers (
    customer_id   INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL,
    city          TEXT NOT NULL,
    signup_date   TEXT NOT NULL  -- ISO date 'YYYY-MM-DD'
);

CREATE TABLE products (
    product_id    INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,
    unit_price    REAL NOT NULL
);

CREATE TABLE orders (
    order_id      INTEGER PRIMARY KEY,
    customer_id   INTEGER NOT NULL REFERENCES customers(customer_id),
    order_date    TEXT NOT NULL,  -- ISO date 'YYYY-MM-DD'
    status        TEXT NOT NULL  -- one of: pending, shipped, delivered, cancelled
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL
);
