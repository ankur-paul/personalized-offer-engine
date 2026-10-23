"""Catalog step: five categories with very different margins and ~40 products each, prices in ₹."""

from __future__ import annotations

from typing import TYPE_CHECKING

from offer_engine.domain import Catalog, Category, Product

if TYPE_CHECKING:
    from offer_engine.sim.generate import GenContext

# name: (margin %, average basket ₹, product ID prefix). Margins sit inside calibration target 7.
CATEGORIES = {
    "grocery": (15.0, 650.0, "GRO"),
    "electronics": (10.0, 7500.0, "ELE"),
    "fashion": (45.0, 1400.0, "FAS"),
    "beauty": (40.0, 850.0, "BEA"),
    "home": (30.0, 1800.0, "HOM"),
}

# Fictional brands × items (with a typical ₹ price) give 40 products per category.
BRANDS = {
    "grocery": ("Annapurna Fresh", "Desi Pantry", "Kisan Select", "Ghar Ka", "Daily Harvest"),
    "electronics": ("Voltix", "Nexa", "Sangam Tech", "Orbit", "Zentro"),
    "fashion": ("Rangrez", "Urban Kurta", "Chhavi", "Denim Lane", "Mitti"),
    "beauty": ("Kesari Glow", "Neem Tree", "Lavanya", "Aura Botanics", "Saffron & Co"),
    "home": ("Gharana", "Tulsi Living", "Chakra Home", "Nest & Nook", "Peetal"),
}
ITEMS = {
    "grocery": (
        ("Basmati Rice 5kg", 699),
        ("Toor Dal 1kg", 179),
        ("Mustard Oil 1L", 199),
        ("Chakki Atta 10kg", 449),
        ("Masala Chai 500g", 249),
        ("Desi Ghee 1L", 649),
        ("Poha 1kg", 89),
        ("Dry Fruit Mix 500g", 549),
    ),
    "electronics": (
        ("Wireless Earbuds", 1999),
        ("Smartwatch", 3499),
        ("Power Bank 20000mAh", 1299),
        ("Bluetooth Speaker", 2499),
        ("Smartphone 5G", 14999),
        ("LED Monitor 24in", 9999),
        ("Mixer Grinder", 3299),
        ("Air Fryer", 5499),
    ),
    "fashion": (
        ("Cotton Kurta", 899),
        ("Slim Jeans", 1299),
        ("Silk Saree", 2999),
        ("Running Shoes", 2199),
        ("Linen Shirt", 1099),
        ("Printed Dupatta", 499),
        ("Leather Sandals", 1199),
        ("Denim Jacket", 1899),
    ),
    "beauty": (
        ("Kumkumadi Face Oil", 799),
        ("Neem Face Wash", 249),
        ("Matte Lipstick", 449),
        ("Sunscreen SPF50", 399),
        ("Hair Oil 200ml", 299),
        ("Kajal", 199),
        ("Vitamin C Serum", 649),
        ("Ubtan Face Pack", 349),
    ),
    "home": (
        ("Cotton Bedsheet Set", 1299),
        ("Steel Dinner Set", 2499),
        ("Brass Diya Pair", 599),
        ("Floor Cushions", 999),
        ("Non-stick Kadai", 1199),
        ("Wall Clock", 899),
        ("Storage Jars Set", 749),
        ("Handloom Rug", 2299),
    ),
}


def ends_in_nine(price: float) -> float:
    """Shelf prices: ₹1,234 → ₹1,229, never below ₹49."""
    return float(max(49, round(price / 10) * 10 - 1))


def build(rng) -> Catalog:
    categories = {name: Category(name, margin, basket) for name, (margin, basket, _) in CATEGORIES.items()}
    products = {}
    for name, (_, _, prefix) in CATEGORIES.items():
        number = 0
        for brand in BRANDS[name]:
            for item, typical_price in ITEMS[name]:
                number += 1
                product_id = f"{prefix}{number:03d}"
                price = ends_in_nine(typical_price * rng.uniform(0.8, 1.3))
                products[product_id] = Product(product_id, f"{brand} {item}", name, price)
    return Catalog(categories, products)


def step(ctx: GenContext) -> None:
    ctx.catalog = build(ctx.rng("catalog"))
    ctx.conn.executemany(
        "INSERT INTO categories (name, margin_pct, avg_basket) VALUES (?, ?, ?)",
        [(c.name, c.margin_pct, c.avg_basket) for c in ctx.catalog.categories.values()],
    )
    ctx.conn.executemany(
        "INSERT INTO products (id, name, category, price) VALUES (?, ?, ?, ?)",
        [(p.id, p.name, p.category, p.price) for p in ctx.catalog.products.values()],
    )
