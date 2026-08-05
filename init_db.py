import sqlite3
import os

DATABASE = 'database.db'
SCHEMA_FILE = 'schema.sql'

def init_db():
    # Make sure we run in the directory of this file
    dir_path = os.path.dirname(os.path.realpath(__file__))
    db_path = os.path.join(dir_path, DATABASE)
    schema_path = os.path.join(dir_path, SCHEMA_FILE)

    print(f"Initializing database at: {db_path}")
    conn = sqlite3.connect(db_path)
    with open(schema_path, 'r') as f:
        conn.executescript(f.read())
    
    # Insert default queues if they don't exist
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO queues (name, prefix) VALUES ('General Queries', 'A')")
    cursor.execute("INSERT OR IGNORE INTO queues (name, prefix) VALUES ('Billing & Support', 'B')")
    cursor.execute("INSERT OR IGNORE INTO queues (name, prefix) VALUES ('VIP Services', 'VIP')")
    
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

if __name__ == '__main__':
    init_db()
