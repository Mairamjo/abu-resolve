from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ai_service import classify_complaint

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, 'abu_resolve.db')
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-development-secret')

CATEGORIES = ['Water', 'Electricity', 'Accommodation', 'Academic', 'Infrastructure', 'Sanitation', 'Security', 'ICT', 'Fees / Finance', 'Other']
STATUSES = ['Submitted', 'Under Review', 'In Progress', 'Resolved', 'Rejected']
PRIORITIES = ['Low', 'Normal', 'High', 'Urgent']

# Columns added for the AI triage stage (also applied to existing databases).
AI_COLUMNS = {
    'ai_category': 'TEXT',
    'ai_summary': 'TEXT',
    'ai_reason': 'TEXT',
    'ai_confidence': 'REAL',
    'ai_source': 'TEXT',
    'needs_review': 'INTEGER DEFAULT 0',
}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')

def init_db():
    with db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            location TEXT,
            description TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'Normal',
            status TEXT NOT NULL DEFAULT 'Submitted',
            assigned_office TEXT,
            admin_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        ''')
        # Migration: add AI columns to databases created before this version.
        existing = {row['name'] for row in conn.execute('PRAGMA table_info(complaints)')}
        for col, col_type in AI_COLUMNS.items():
            if col not in existing:
                conn.execute(f'ALTER TABLE complaints ADD COLUMN {col} {col_type}')
        admin = conn.execute('SELECT id FROM users WHERE email = ?', ('admin@aburesolve.local',)).fetchone()
        if not admin:
            conn.execute('INSERT INTO users(full_name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                         ('ABU Resolve Admin', 'admin@aburesolve.local', generate_password_hash('Admin123!'), 'admin', now()))

def current_user():
    if 'user_id' not in session:
        return None
    with db() as conn:
        return conn.execute('SELECT id, full_name, email, role FROM users WHERE id=?', (session['user_id'],)).fetchone()

def login_required(admin=False):
    user = current_user()
    if not user:
        flash('Please sign in to continue.', 'info')
        return redirect(url_for('login'))
    if admin and user['role'] != 'admin':
        abort(403)
    return None

def make_reference():
    with db() as conn:
        last = conn.execute('SELECT MAX(id) AS m FROM complaints').fetchone()['m'] or 0
    return f'ABUR-{datetime.now():%y%m}-{last + 1:04d}'

@app.context_processor
def inject_globals():
    return {'current_user': current_user(), 'categories': CATEGORIES, 'statuses': STATUSES, 'priorities': PRIORITIES}

@app.route('/')
def index():
    user = current_user()
    if user:
        return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'dashboard'))
    return render_template('welcome.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not name or not email or len(password) < 8:
            flash('Enter your name and email, and use a password with at least 8 characters.', 'error')
        else:
            try:
                with db() as conn:
                    conn.execute('INSERT INTO users(full_name,email,password_hash,role,created_at) VALUES(?,?,?,?,?)',
                                 (name, email, generate_password_hash(password), 'student', now()))
                flash('Account created. You can now sign in.', 'success')
                return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                flash('An account with that email already exists.', 'error')
    return render_template('auth.html', mode='register')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        with db() as conn:
            user = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['id']
            flash(f'Welcome back, {user["full_name"].split()[0]}!', 'success')
            return redirect(url_for('admin_dashboard' if user['role'] == 'admin' else 'dashboard'))
        flash('Email or password is incorrect.', 'error')
    return render_template('auth.html', mode='login')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been signed out.', 'info')
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    gate = login_required()
    if gate: return gate
    user = current_user()
    with db() as conn:
        complaints = conn.execute('SELECT * FROM complaints WHERE user_id=? ORDER BY id DESC LIMIT 5', (user['id'],)).fetchall()
        stats = {s: conn.execute('SELECT COUNT(*) n FROM complaints WHERE user_id=? AND status=?', (user['id'], s)).fetchone()['n'] for s in STATUSES}
        total = conn.execute('SELECT COUNT(*) n FROM complaints WHERE user_id=?', (user['id'],)).fetchone()['n']
    return render_template('dashboard.html', complaints=complaints, stats=stats, total=total)

@app.route('/complaints/new', methods=['GET', 'POST'])
def new_complaint():
    gate = login_required()
    if gate: return gate
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        category = request.form.get('category', '')
        location = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()
        if not title or category not in CATEGORIES or len(description) < 15:
            flash('Add a title, choose a category, and describe the issue in at least 15 characters.', 'error')
        else:
            stamp = now(); ref = make_reference()
            # AI triage: priority, routing and a one-line summary for admins.
            triage = classify_complaint(title, category, location, description)
            with db() as conn:
                conn.execute(
                    '''INSERT INTO complaints(reference,user_id,title,category,location,description,priority,status,
                       assigned_office,created_at,updated_at,ai_category,ai_summary,ai_reason,ai_confidence,ai_source,needs_review)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (ref, session['user_id'], title, category, location, description,
                     triage['priority'], 'Submitted', triage['assigned_office'], stamp, stamp,
                     triage['category'], triage['summary'], triage['reason'], triage['confidence'],
                     triage['source'], 1 if triage['needs_human_review'] else 0))
            flash(f'Complaint submitted successfully. Your reference number is {ref}.', 'success')
            if triage['priority'] == 'Urgent':
                flash('This looks urgent. If anyone is in immediate danger, please also contact campus security directly.', 'info')
            return redirect(url_for('complaint_detail', complaint_id=ref))
    return render_template('new_complaint.html')

@app.route('/complaints')
def my_complaints():
    gate = login_required()
    if gate: return gate
    user = current_user()
    status = request.args.get('status', '')
    with db() as conn:
        if status in STATUSES:
            rows = conn.execute('SELECT * FROM complaints WHERE user_id=? AND status=? ORDER BY id DESC', (user['id'], status)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM complaints WHERE user_id=? ORDER BY id DESC', (user['id'],)).fetchall()
    return render_template('complaints.html', complaints=rows, selected_status=status)

@app.route('/complaints/<complaint_id>')
def complaint_detail(complaint_id):
    gate = login_required()
    if gate: return gate
    user = current_user()
    with db() as conn:
        item = conn.execute('SELECT c.*, u.full_name FROM complaints c JOIN users u ON u.id=c.user_id WHERE c.reference=?', (complaint_id,)).fetchone()
    if not item: abort(404)
    if user['role'] != 'admin' and item['user_id'] != user['id']: abort(403)
    return render_template('complaint_detail.html', item=item)

@app.route('/admin')
def admin_dashboard():
    gate = login_required(admin=True)
    if gate: return gate
    with db() as conn:
        total = conn.execute('SELECT COUNT(*) n FROM complaints').fetchone()['n']
        stats = {s: conn.execute('SELECT COUNT(*) n FROM complaints WHERE status=?', (s,)).fetchone()['n'] for s in STATUSES}
        complaints = conn.execute('SELECT c.*, u.full_name FROM complaints c JOIN users u ON u.id=c.user_id ORDER BY c.id DESC LIMIT 8').fetchall()
    return render_template('admin_dashboard.html', total=total, stats=stats, complaints=complaints)

@app.route('/admin/complaints', methods=['GET', 'POST'])
def admin_complaints():
    gate = login_required(admin=True)
    if gate: return gate
    if request.method == 'POST':
        ref = request.form.get('reference', '')
        status = request.form.get('status', '')
        priority = request.form.get('priority', '')
        office = request.form.get('assigned_office', '').strip()
        note = request.form.get('admin_note', '').strip()
        if status not in STATUSES or priority not in PRIORITIES:
            flash('Choose a valid status and priority.', 'error')
        else:
            with db() as conn:
                cur = conn.execute('UPDATE complaints SET status=?, priority=?, assigned_office=?, admin_note=?, needs_review=0, updated_at=? WHERE reference=?',
                                   (status, priority, office, note, now(), ref))
            if cur.rowcount:
                flash(f'Complaint {ref} updated.', 'success')
            else:
                flash('That complaint could not be found.', 'error')
        return redirect(url_for('admin_complaints'))
    status = request.args.get('status', '')
    with db() as conn:
        if status in STATUSES:
            complaints = conn.execute('SELECT c.*, u.full_name FROM complaints c JOIN users u ON u.id=c.user_id WHERE c.status=? ORDER BY c.id DESC', (status,)).fetchall()
        else:
            complaints = conn.execute('SELECT c.*, u.full_name FROM complaints c JOIN users u ON u.id=c.user_id ORDER BY c.id DESC').fetchall()
    return render_template('admin_complaints.html', complaints=complaints, selected_status=status)

# ---------- JSON API ----------

@app.route('/api/classify', methods=['POST'])
def api_classify():
    """Preview AI triage without saving. Body: {title, category, location, description}."""
    user = current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    data = request.get_json(silent=True) or {}
    title = str(data.get('title', '')).strip()
    description = str(data.get('description', '')).strip()
    if not title or len(description) < 15:
        return jsonify({'error': 'title and a description of at least 15 characters are required'}), 400
    result = classify_complaint(title, str(data.get('category', '')), str(data.get('location', '')).strip(), description)
    return jsonify(result)

@app.route('/api/complaints')
def api_complaints():
    """Complaints as JSON: students see their own, admins see all."""
    user = current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    with db() as conn:
        if user['role'] == 'admin':
            rows = conn.execute('SELECT * FROM complaints ORDER BY id DESC').fetchall()
        else:
            rows = conn.execute('SELECT * FROM complaints WHERE user_id=? ORDER BY id DESC', (user['id'],)).fetchall()
    return jsonify([dict(r) for r in rows])

@app.errorhandler(403)
def forbidden(_):
    return render_template('message.html', heading='Access restricted', message='You do not have permission to view this page.'), 403

@app.errorhandler(404)
def not_found(_):
    return render_template('message.html', heading='Page not found', message='We could not find the page or complaint you requested.'), 404

init_db()
if __name__ == '__main__':
    app.run(debug=True)
