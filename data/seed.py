"""Builds data/synthetic.db from schema.sql with deterministic synthetic rows.

Re-run any time to reset the dataset: python3 data/seed.py
"""
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent
DB_PATH = DATA_DIR / "synthetic.db"
SCHEMA_PATH = DATA_DIR / "schema.sql"

random.seed(42)

CITIES = ["Austin", "Seattle", "Denver", "Chicago", "Boston", "Miami", "Portland"]
CATEGORIES = {
    "Electronics": ["Wireless Mouse", "USB-C Hub", "Mechanical Keyboard", "Webcam", "Monitor Stand"],
    "Home": ["Ceramic Mug", "Throw Blanket", "Desk Lamp", "Candle Set", "Storage Bin"],
    "Books": ["Mystery Novel", "Cookbook", "Sci-Fi Anthology", "Biography", "Poetry Collection"],
    "Sports": ["Yoga Mat", "Water Bottle", "Resistance Bands", "Running Socks", "Foam Roller"],
}
STATUSES = ["pending", "shipped", "delivered", "cancelled"]
FIRST_NAMES = ["Alex", "Jordan", "Sam", "Taylor", "Morgan", "Casey", "Riley", "Jamie",
               "Drew", "Avery", "Quinn", "Reese", "Skyler", "Dana", "Elliot", "Harper"]
LAST_NAMES = ["Nguyen", "Smith", "Garcia", "Patel", "Kim", "Johnson", "Lopez", "Chen",
              "Brown", "Davis", "Martinez", "Wilson", "Clark", "Lewis", "Walker", "Young"]


def random_date(start: date, end: date) -> str:
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()


def build():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_PATH.read_text())

    # customers
    customers = []
    for i in range(1, 41):
        first, last = random.choice(FIRST_NAMES), random.choice(LAST_NAMES)
        name = f"{first} {last}"
        email = f"{first.lower()}.{last.lower()}{i}@example.com"
        city = random.choice(CITIES)
        signup = random_date(date(2023, 1, 1), date(2024, 6, 30))
        customers.append((i, name, email, city, signup))
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?, ?)", customers
    )

    # products
    products = []
    pid = 1
    for category, names in CATEGORIES.items():
        for name in names:
            price = round(random.uniform(5, 150), 2)
            products.append((pid, name, category, price))
            pid += 1
    conn.executemany(
        "INSERT INTO products VALUES (?, ?, ?, ?)", products
    )

    # orders + order_items
    orders = []
    order_items = []
    order_id = 1
    item_id = 1
    for customer in customers:
        num_orders = random.randint(0, 5)
        for _ in range(num_orders):
            order_date = random_date(date(2023, 1, 1), date(2024, 12, 31))
            status = random.choice(STATUSES)
            orders.append((order_id, customer[0], order_date, status))

            num_items = random.randint(1, 4)
            chosen = random.sample(products, num_items)
            for product in chosen:
                qty = random.randint(1, 5)
                order_items.append((item_id, order_id, product[0], qty))
                item_id += 1

            order_id += 1

    conn.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?)", orders
    )
    conn.executemany(
        "INSERT INTO order_items VALUES (?, ?, ?, ?)", order_items
    )

    conn.commit()
    conn.close()
    print(f"Seeded {len(customers)} customers, {len(products)} products, "
          f"{len(orders)} orders, {len(order_items)} order_items into {DB_PATH}")


if __name__ == "__main__":
    build()
