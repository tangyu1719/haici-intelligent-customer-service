USE ecommerce;

INSERT INTO products (product_id, name, category, brand, price, original_price, description, image_url, sales, rating, created_at) VALUES
('P001', 'Apple iPhone 15 Pro 256GB', '手机', 'Apple', 8999.00, 9999.00, '6.1英寸超视网膜XDR显示屏,A17 Pro芯片', '', 15000, 4.9, NOW()),
('P002', 'Apple iPhone 15 128GB', '手机', 'Apple', 5999.00, 6499.00, '6.1英寸超视网膜XDR显示屏,A16芯片', '', 25000, 4.8, NOW()),
('P003', 'Xiaomi 14 Pro 512GB', '手机', '小米', 4999.00, 5299.00, '6.73英寸2K屏幕,骁龙8Gen3', '', 12000, 4.7, NOW()),
('P004', 'HUAWEI Mate 60 Pro', '手机', '华为', 6999.00, 7299.00, '6.82英寸OLED曲面屏,麒麟9000S', '', 20000, 4.9, NOW()),
('P005', 'MacBook Pro 14 M3 Pro', '电脑', 'Apple', 16999.00, 17999.00, '14.2英寸Liquid视网膜XDR屏,M3 Pro芯片', '', 5000, 4.9, NOW());

INSERT INTO product_skus (sku_id, product_id, spec_info, price, stock) VALUES
('SKU001', 'P001', '原色钛金属 256GB', 8999.00, 500),
('SKU002', 'P001', '蓝色钛金属 256GB', 8999.00, 300),
('SKU003', 'P002', '黑色 128GB', 5999.00, 800),
('SKU004', 'P003', '黑色 512GB', 4999.00, 400),
('SKU005', 'P005', '深空黑 512GB', 16999.00, 150);

INSERT INTO product_specs (product_id, spec_name, spec_value) VALUES
('P001', '屏幕尺寸', '6.1英寸'),
('P001', '处理器', 'A17 Pro'),
('P001', '存储容量', '256GB'),
('P003', '屏幕尺寸', '6.73英寸'),
('P003', '处理器', '骁龙8 Gen3');

INSERT INTO users (user_id, username, phone, email, level, created_at) VALUES
('U001', '张三', '13800138001', 'zhangsan@example.com', 3, NOW()),
('U002', '李四', '13800138002', 'lisi@example.com', 2, NOW());

INSERT INTO orders (order_id, user_id, status, total_amount, pay_amount, freight, address, remark, created_at, updated_at) VALUES
('OD20240115001', 'U001', 'shipped', 8999.00, 8999.00, 0, '北京市朝阳区xxx街道', NULL, '2024-01-15 10:30:00', NOW()),
('OD20240116002', 'U001', 'pending', 5999.00, 5999.00, 0, '北京市朝阳区xxx街道', NULL, '2024-01-16 14:20:00', NOW()),
('OD20240117003', 'U002', 'delivered', 4999.00, 4999.00, 0, '上海市浦东新区yyy路', NULL, '2024-01-10 09:00:00', NOW());

INSERT INTO order_items (order_id, product_id, sku_id, quantity, price) VALUES
('OD20240115001', 'P001', 'SKU001', 1, 8999.00),
('OD20240116002', 'P002', 'SKU003', 1, 5999.00),
('OD20240117003', 'P003', 'SKU004', 1, 4999.00);

INSERT INTO logistics (order_id, carrier, tracking_no, status, updated_at) VALUES
('OD20240115001', '顺丰速运', 'SF1234567890', 'in_transit', NOW()),
('OD20240117003', '京东物流', 'JD9876543210', 'delivered', NOW());

INSERT INTO logistics_trace (order_id, tracking_no, trace_time, content) VALUES
('OD20240115001', 'SF1234567890', '2024-01-15 12:00:00', '包裹已揽收'),
('OD20240115001', 'SF1234567890', '2024-01-15 18:00:00', '包裹已到达北京分拨中心'),
('OD20240115001', 'SF1234567890', '2024-01-16 08:00:00', '包裹正在派送中'),
('OD20240117003', 'JD9876543210', '2024-01-11 09:00:00', '包裹已送达,签收人:本人');
