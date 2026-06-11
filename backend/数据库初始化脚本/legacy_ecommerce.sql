CREATE DATABASE IF NOT EXISTS ecommerce DEFAULT CHARACTER SET utf8mb4;
USE ecommerce;

CREATE TABLE IF NOT EXISTS products (
    product_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(50),
    brand VARCHAR(50),
    price DECIMAL(10,2),
    original_price DECIMAL(10,2),
    description TEXT,
    image_url VARCHAR(500),
    sales INT DEFAULT 0,
    rating DECIMAL(2,1) DEFAULT 5.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS product_skus (
    sku_id VARCHAR(32) PRIMARY KEY,
    product_id VARCHAR(32),
    spec_info VARCHAR(200),
    price DECIMAL(10,2),
    stock INT DEFAULT 0,
    INDEX idx_product (product_id)
);

CREATE TABLE IF NOT EXISTS product_specs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    product_id VARCHAR(32),
    spec_name VARCHAR(50),
    spec_value VARCHAR(200),
    INDEX idx_product (product_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id VARCHAR(32) PRIMARY KEY,
    username VARCHAR(50),
    phone VARCHAR(20),
    email VARCHAR(100),
    level INT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(32) PRIMARY KEY,
    user_id VARCHAR(32),
    status VARCHAR(20) DEFAULT 'pending',
    total_amount DECIMAL(10,2),
    pay_amount DECIMAL(10,2),
    freight DECIMAL(10,2) DEFAULT 0,
    address TEXT,
    remark TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user (user_id),
    INDEX idx_status (status)
);

CREATE TABLE IF NOT EXISTS order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(32),
    product_id VARCHAR(32),
    sku_id VARCHAR(32),
    quantity INT,
    price DECIMAL(10,2),
    INDEX idx_order (order_id)
);

CREATE TABLE IF NOT EXISTS logistics (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(32),
    carrier VARCHAR(50),
    tracking_no VARCHAR(50),
    status VARCHAR(20),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_order (order_id)
);

CREATE TABLE IF NOT EXISTS logistics_trace (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(32),
    tracking_no VARCHAR(50),
    trace_time DATETIME,
    content VARCHAR(500),
    INDEX idx_order (order_id)
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id VARCHAR(32) PRIMARY KEY,
    order_id VARCHAR(32),
    user_id VARCHAR(32),
    amount DECIMAL(10,2),
    reason TEXT,
    refund_type VARCHAR(20),
    status VARCHAR(20) DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_order (order_id)
);
