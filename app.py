from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import sqlite3
import os
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.urandom(24)

DATABASE = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'database.db')

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Helper to verify database setup
def check_db_initialized():
    if not os.path.exists(DATABASE):
        from init_db import init_db
        init_db()

@app.route('/')
def index():
    check_db_initialized()
    return render_template('index.html')

# User Registration
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json() or request.form
    username = data.get('username')
    password = data.get('password')
    role = data.get('role', 'customer') # default role is customer

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400

    hashed_pw = generate_password_hash(password)

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                     (username, hashed_pw, role))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Username already exists'}), 400
    finally:
        conn.close()

    return jsonify({'success': 'User registered successfully'})

# User Login
@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json() or request.form
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'error': 'Username and password are required'}), 400

    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()

    if user and check_password_hash(user['password'], password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        return jsonify({
            'success': 'Logged in successfully',
            'user': {
                'id': user['id'],
                'username': user['username'],
                'role': user['role']
            }
        })
    
    return jsonify({'error': 'Invalid username or password'}), 401

# User Logout
@app.route('/api/logout', methods=['POST', 'GET'])
def logout():
    session.clear()
    return jsonify({'success': 'Logged out successfully'})

# Join Queue / Token Generation
@app.route('/api/join_queue', methods=['POST'])
def join_queue():
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required. Please sign in.'}), 401

    data = request.get_json() or request.form
    queue_id = data.get('queue_id')

    if not queue_id:
        return jsonify({'error': 'Queue ID is required'}), 400

    conn = get_db_connection()
    queue = conn.execute('SELECT * FROM queues WHERE id = ?', (queue_id,)).fetchone()
    if not queue:
        conn.close()
        return jsonify({'error': 'Queue not found'}), 404

    # Calculate token number prefix + next auto increment count
    # Let's count tokens existing in this queue to generate ticket numbers
    token_count = conn.execute('SELECT COUNT(*) FROM tokens WHERE queue_id = ?', (queue_id,)).fetchone()[0]
    next_num = token_count + 1
    token_number = f"{queue['prefix']}-{next_num}"

    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO tokens (queue_id, user_id, token_number, status) VALUES (?, ?, ?, ?)',
        (queue_id, session['user_id'], token_number, 'waiting')
    )
    token_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return jsonify({
        'success': 'Successfully joined queue',
        'token': {
            'id': token_id,
            'token_number': token_number,
            'status': 'waiting'
        }
    })

# Current Serving Token & Queue Info
@app.route('/api/queue_status', methods=['GET'])
def queue_status():
    conn = get_db_connection()
    queues = conn.execute('SELECT * FROM queues').fetchall()
    
    status_list = []
    for q in queues:
        # Fetch current serving token (if any)
        serving = conn.execute(
            "SELECT token_number FROM tokens WHERE queue_id = ? AND status = 'serving' ORDER BY joined_at DESC LIMIT 1",
            (q['id'],)
        ).fetchone()
        
        # Fetch count of waiting people
        waiting_count = conn.execute(
            "SELECT COUNT(*) FROM tokens WHERE queue_id = ? AND status = 'waiting'",
            (q['id'],)
        ).fetchone()[0]

        status_list.append({
            'queue_id': q['id'],
            'queue_name': q['name'],
            'prefix': q['prefix'],
            'serving_now': serving['token_number'] if serving else 'None',
            'waiting_count': waiting_count
        })
    conn.close()
    return jsonify({'queues': status_list})

# Admin: Serve Next Ticket
@app.route('/api/admin/serve_next', methods=['POST'])
def serve_next():
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Admin permissions required'}), 403

    data = request.get_json() or request.form
    queue_id = data.get('queue_id')

    if not queue_id:
        return jsonify({'error': 'Queue ID is required'}), 400

    conn = get_db_connection()
    
    # Complete currently serving tokens and log them to queue_history
    current_serving = conn.execute(
        "SELECT * FROM tokens WHERE queue_id = ? AND status = 'serving'",
        (queue_id,)
    ).fetchall()

    for token in current_serving:
        conn.execute("UPDATE tokens SET status = 'completed' WHERE id = ?", (token['id'],))
        conn.execute('''
            INSERT INTO queue_history (
                token_id, queue_id, served_by_admin_id, joined_at, served_at, completed_at, status, 
                waiting_duration_seconds, service_duration_seconds
            ) VALUES (
                ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 'completed',
                (strftime('%s', ?) - strftime('%s', ?)),
                (strftime('%s', 'now') - strftime('%s', ?))
            )
        ''', (
            token['id'], queue_id, session.get('user_id'), token['joined_at'], 
            token['served_at'] if token['served_at'] else token['joined_at'],
            token['served_at'] if token['served_at'] else token['joined_at'],
            token['joined_at'],
            token['served_at'] if token['served_at'] else token['joined_at']
        ))

    # Fetch next waiting token
    next_token = conn.execute(
        "SELECT * FROM tokens WHERE queue_id = ? AND status = 'waiting' ORDER BY joined_at ASC LIMIT 1",
        (queue_id,)
    ).fetchone()

    if not next_token:
        conn.commit()
        conn.close()
        return jsonify({'message': 'No clients waiting in this queue', 'serving_now': 'None'})

    # Set state of next token to serving and record served_at
    conn.execute(
        "UPDATE tokens SET status = 'serving', served_at = CURRENT_TIMESTAMP WHERE id = ?",
        (next_token['id'],)
    )

    conn.commit()
    conn.close()

    return jsonify({
        'success': f'Now serving token {next_token["token_number"]}',
        'serving_now': next_token['token_number']
    })

# Admin: Create Queue
@app.route('/api/admin/create_queue', methods=['POST'])
def create_queue():
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Admin permissions required'}), 403

    data = request.get_json() or request.form
    name = data.get('name')
    prefix = data.get('prefix')

    if not name or not prefix:
        return jsonify({'error': 'Queue name and prefix are required'}), 400

    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO queues (name, prefix) VALUES (?, ?)', (name, prefix.upper()))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error': 'Queue name already exists'}), 400
    finally:
        conn.close()

    return jsonify({'success': f'Queue "{name}" created successfully'})

# Admin: Delete Queue
@app.route('/api/admin/delete_queue', methods=['POST'])
def delete_queue():
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Admin permissions required'}), 403

    data = request.get_json() or request.form
    queue_id = data.get('queue_id')

    if not queue_id:
        return jsonify({'error': 'Queue ID is required'}), 400

    conn = get_db_connection()
    conn.execute('DELETE FROM queues WHERE id = ?', (queue_id,))
    conn.commit()
    conn.close()

    return jsonify({'success': 'Queue deleted successfully'})

# Admin: View Waiting Customers
@app.route('/api/admin/waiting_customers', methods=['GET'])
def waiting_customers():
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Admin permissions required'}), 403

    conn = get_db_connection()
    waiting = conn.execute('''
        SELECT t.id, t.token_number, t.joined_at, u.username, q.name as queue_name
        FROM tokens t
        JOIN users u ON t.user_id = u.id
        JOIN queues q ON t.queue_id = q.id
        WHERE t.status = 'waiting'
        ORDER BY t.joined_at ASC
    ''').fetchall()
    conn.close()

    return jsonify({
        'customers': [dict(row) for row in waiting]
    })

# Admin: Search Customer
@app.route('/api/admin/search_customer', methods=['GET'])
def search_customer():
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Admin permissions required'}), 403

    query = request.args.get('q', '')
    conn = get_db_connection()
    results = conn.execute('''
        SELECT t.token_number, t.status, t.joined_at, u.username, q.name as queue_name
        FROM tokens t
        JOIN users u ON t.user_id = u.id
        JOIN queues q ON t.queue_id = q.id
        WHERE u.username LIKE ? OR t.token_number LIKE ?
        ORDER BY t.joined_at DESC
    ''', (f'%{query}%', f'%{query}%')).fetchall()
    conn.close()

    return jsonify({
        'results': [dict(row) for row in results]
    })

# Admin: Queue Analytics
@app.route('/api/admin/analytics', methods=['GET'])
def analytics():
    if 'role' not in session or session['role'] != 'admin':
        return jsonify({'error': 'Admin permissions required'}), 403

    conn = get_db_connection()
    
    # General counters
    total_served = conn.execute("SELECT COUNT(*) FROM queue_history WHERE status = 'completed'").fetchone()[0]
    total_cancelled = conn.execute("SELECT COUNT(*) FROM queue_history WHERE status = 'cancelled'").fetchone()[0]
    
    # Department breakdown
    breakdown = conn.execute('''
        SELECT q.name, COUNT(h.id) as count
        FROM queues q
        LEFT JOIN queue_history h ON q.id = h.queue_id
        GROUP BY q.id
    ''').fetchall()

    conn.close()

    return jsonify({
        'total_served': total_served,
        'total_cancelled': total_cancelled,
        'breakdown': [dict(row) for row in breakdown]
    })

# Customer: Get Active Token details (Position, Wait Time)
@app.route('/api/customer/active_token', methods=['GET'])
def active_token():
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401

    conn = get_db_connection()
    
    # Fetch user's active token
    token = conn.execute('''
        SELECT t.id, t.token_number, t.status, t.joined_at, q.id as queue_id, q.name as queue_name
        FROM tokens t
        JOIN queues q ON t.queue_id = q.id
        WHERE t.user_id = ? AND t.status IN ('waiting', 'serving')
        ORDER BY t.joined_at DESC LIMIT 1
    ''', (session['user_id'],)).fetchone()

    if not token:
        conn.close()
        return jsonify({'token': None})

    # Calculate position
    position = 0
    if token['status'] == 'waiting':
        position = conn.execute('''
            SELECT COUNT(*) FROM tokens 
            WHERE queue_id = ? AND status = 'waiting' AND joined_at <= ?
        ''', (token['queue_id'], token['joined_at'])).fetchone()[0]
    
    # Simple dynamic weight: 5 minutes per person
    estimated_wait = position * 5

    conn.close()

    return jsonify({
        'token': {
            'id': token['id'],
            'token_number': token['token_number'],
            'status': token['status'],
            'queue_name': token['queue_name'],
            'position': f"{position} in line" if position > 0 else "Serving Now",
            'estimated_wait_minutes': estimated_wait
        }
    })

# Customer: View Token History
@app.route('/api/customer/history', methods=['GET'])
def customer_history():
    if 'user_id' not in session:
        return jsonify({'error': 'Authentication required'}), 401

    conn = get_db_connection()
    history = conn.execute('''
        SELECT t.token_number, t.status, t.joined_at, q.name as queue_name
        FROM tokens t
        JOIN queues q ON t.queue_id = q.id
        WHERE t.user_id = ? AND t.status IN ('completed', 'cancelled')
        ORDER BY t.joined_at DESC
    ''', (session['user_id'],)).fetchall()
    conn.close()

    return jsonify({
        'history': [dict(row) for row in history]
    })

if __name__ == '__main__':

    check_db_initialized()
    app.run(debug=True)

