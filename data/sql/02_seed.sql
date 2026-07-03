-- Sample data for shop demo (MySQL 8.0+)
USE ai_sql_dev;

SET NAMES utf8mb4;

INSERT INTO categories (name, description) VALUES
  ('Electronics', 'Phones, laptops, accessories'),
  ('Books', 'Physical and technical books'),
  ('Home', 'Kitchen and decor');

INSERT INTO products (category_id, sku, name, description, price, stock_qty, is_active) VALUES
  (1, 'PHONE-X1', 'Phone X1', '6.1" OLED smartphone', 699.99, 40, 1),
  (1, 'BUDS-AIR', 'Buds Air', 'Wireless earbuds', 89.50, 120, 1),
  (1, 'LAPTOP-14', 'Laptop 14"', 'Lightweight laptop', 999.00, 15, 1),
  (2, 'BOOK-SQL', 'SQL for Developers', 'Intro to relational databases', 39.90, 200, 1),
  (2, 'BOOK-PY', 'Python Cookbook', 'Recipes and patterns', 49.00, 80, 1),
  (3, 'MUG-CER', 'Ceramic Mug', '350ml mug', 12.00, 300, 1),
  (3, 'LAMP-DESK', 'Desk Lamp', 'LED desk lamp', 45.00, 60, 1);

INSERT INTO customers (email, full_name, country) VALUES
  ('ana.popescu@example.com', 'Ana Popescu', 'RO'),
  ('mihai.ionescu@example.com', 'Mihai Ionescu', 'RO'),
  ('sara.dinu@example.com', 'Sara Dinu', 'RO'),
  ('guest@example.com', 'Guest User', NULL);

-- Orders span different dates for "last month", "top products", etc.
INSERT INTO orders (customer_id, order_date, status, notes) VALUES
  (1, '2026-01-10 10:00:00', 'paid', NULL),
  (2, '2026-02-05 14:30:00', 'shipped', NULL),
  (1, '2026-02-20 09:15:00', 'paid', 'Gift wrap'),
  (3, '2026-03-01 11:00:00', 'paid', NULL),
  (2, '2026-03-15 16:45:00', 'pending', NULL),
  (4, '2026-03-28 08:00:00', 'cancelled', 'Customer changed mind');

INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES
  (1, 1, 1, 699.99),
  (1, 2, 1, 89.50),
  (2, 4, 2, 39.90),
  (2, 5, 1, 49.00),
  (3, 2, 2, 89.50),
  (3, 7, 1, 45.00),
  (4, 3, 1, 999.00),
  (5, 6, 4, 12.00),
  (5, 2, 1, 89.50);
