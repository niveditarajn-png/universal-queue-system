-- SQLite Database Schema for Universal Queue Management System

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'customer'))
);

CREATE TABLE IF NOT EXISTS queues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    prefix TEXT NOT NULL,
    current_token_index INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    token_number TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('waiting', 'serving', 'completed', 'cancelled')),
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    served_at TIMESTAMP,
    FOREIGN KEY(queue_id) REFERENCES queues(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS queue_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    queue_id INTEGER NOT NULL,
    served_by_admin_id INTEGER,
    joined_at TIMESTAMP NOT NULL,
    served_at TIMESTAMP,
    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL CHECK(status IN ('completed', 'cancelled')),
    waiting_duration_seconds INTEGER,
    service_duration_seconds INTEGER,
    FOREIGN KEY(token_id) REFERENCES tokens(id) ON DELETE SET NULL,
    FOREIGN KEY(queue_id) REFERENCES queues(id) ON DELETE CASCADE,
    FOREIGN KEY(served_by_admin_id) REFERENCES users(id) ON DELETE SET NULL
);

