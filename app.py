from flask import Flask, request, redirect, url_for, session, render_template_string
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route("/")
def home():
    return "<h1>✅ SERVER ISHLADI!</h1><p>Maktab Portali muvaffaqiyatli ishga tushdi.</p><p><a href='/dashboard'>Dashboard ga o'tish</a></p>"

@app.route("/dashboard")
def dashboard():
    return "<h1>Bosh Sahifa</h1><p>Tizim barqaror ishlayapti.</p>"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session['user_role'] = 'admin'
        session['school_id'] = 1
        return redirect(url_for('dashboard'))
    return '''<form method="post">
        <input name="username" placeholder="Login"><br>
        <input name="password" type="password" placeholder="Parol"><br>
        <button type="submit">Kirish</button>
    </form>'''

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
