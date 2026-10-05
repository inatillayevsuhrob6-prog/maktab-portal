from flask import Flask, request, redirect, url_for, session, render_template_string, flash
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route("/")
def home():
    if 'user_role' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route("/dashboard")
def dashboard():
    if 'user_role' not in session:
        return redirect(url_for('login'))
    
    html = """<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <title>Bosh Sahifa - Maktab Portali</title>
    <style>
        body { font-family: sans-serif; background: #f0f2f5; margin: 0; display: flex; }
        .sidebar { width: 260px; background: #1e293b; color: white; height: 100vh; padding: 20px 0; position: fixed; }
        .brand { padding: 0 25px 30px; font-size: 1.4rem; font-weight: bold; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 20px; }
        .menu a { display: block; padding: 14px 25px; color: #94a3b8; text-decoration: none; transition: 0.3s; border-left: 3px solid transparent; }
        .menu a:hover, .menu a.active { background: rgba(255,255,255,0.05); color: white; border-left-color: #3b82f6; }
        .main { flex: 1; margin-left: 260px; padding: 40px; }
        .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 20px; }
        .card { background: white; padding: 25px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); }
        .card h3 { margin: 0 0 10px; color: #64748b; font-size: 0.9rem; text-transform: uppercase; }
        .card .num { font-size: 2.5rem; font-weight: bold; color: #1e293b; margin: 0 0 15px; }
        .btn { display: inline-block; padding: 10px 20px; background: #3b82f6; color: white; text-decoration: none; border-radius: 8px; font-weight: 600; }
        .logout { color: #ef4444; text-decoration: none; font-weight: 600; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="brand">Maktab Portali</div>
        <div class="menu">
            <a href="/dashboard" class="active">🏠 Bosh sahifa</a>
            <a href="/tests">📝 Testlar</a>
            <a href="/students">🎓 O'quvchilar</a>
            <a href="/teachers">👩‍🏫 O'qituvchilar</a>
            <a href="/classes">🏫 Sinflar</a>
            <a href="/library">📚 Kutubxona</a>
            <a href="/chat">💬 Chat</a>
        </div>
    </div>
    <div class="main">
        <div class="header">
            <h1>Xush kelibsiz, {{ name }}!</h1>
            <a href="/logout" class="logout">Chiqish</a>
        </div>
        <div class="grid">
            <div class="card"><h3>Testlar</h3><p class="num">5</p><a href="/tests" class="btn">Boshqarish</a></div>
            <div class="card"><h3>O'quvchilar</h3><p class="num">120</p><a href="/students" class="btn">Ro'yxat</a></div>
            <div class="card"><h3>O'qituvchilar</h3><p class="num">8</p><a href="/teachers" class="btn">Jamoa</a></div>
            <div class="card"><h3>Sinflar</h3><p class="num">6</p><a href="/classes" class="btn">Jadval</a></div>
        </div>
    </div>
</body>
</html>"""
    return render_template_string(html, name=session.get('user_name', 'Admin'))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get('username')
        password = request.form.get('password')
        if username and password:
            session['user_role'] = 'admin'
            session['school_id'] = 1
            session['user_name'] = username.title()
            return redirect(url_for('dashboard'))
        flash("Login yoki parol noto'g'ri!", "danger")
            
    html = """<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <title>Kirish</title>
    <style>
        body { font-family: sans-serif; background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .box { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); width: 100%; max-width: 400px; }
        input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #e2e8f0; border-radius: 8px; box-sizing: border-box; }
        button { width: 100%; padding: 12px; background: #3b82f6; color: white; border: none; border-radius: 8px; font-weight: bold; cursor: pointer; margin-top: 10px; }
        .error { color: #ef4444; background: #fef2f2; padding: 10px; border-radius: 8px; margin-bottom: 15px; text-align: center; }
    </style>
</head>
<body>
    <div class="box">
        <h2 style="text-align:center; color:#1e293b;">Tizimga Kirish</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="post">
            <input type="text" name="username" placeholder="Login" required>
            <input type="password" name="password" placeholder="Parol" required>
            <button type="submit">Kirish</button>
        </form>
    </div>
</body>
</html>"""
    return render_template_string(html)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route("/tests")
@app.route("/students")
@app.route("/teachers")
@app.route("/classes")
@app.route("/library")
@app.route("/chat")
def placeholder():
    if 'user_role' not in session: return redirect(url_for('login'))
    page = request.path[1:].title()
    return f"""<!DOCTYPE html>
<html><head><title>{page}</title><style>body{{font-family:sans-serif;padding:40px;background:#f0f2f5}}.back{{color:#3b82f6;text-decoration:none}}</style></head>
<body><h1>{page} Sahifasi</h1><p>Tez orada bu yerda to'liq funksional bo'ladi.</p><a href='/dashboard' class='back'>← Ortga</a></body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
