-- GC-CART: multi-SKU order lines on shop_orders (one PayPal payment, one promo).
-- Legacy rows keep empty/[] items_json → fulfill falls back to single sku.

ALTER TABLE shop_orders ADD COLUMN items_json TEXT NOT NULL DEFAULT '[]';
