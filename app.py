from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from config import Config
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from backend.models import School, Class, Student, Teacher, TeacherClassAssignment, Subject, Test, TestQuestion, TestResult, Achievement, StudentAchievement, Schedule, Book, News, Club, StudentClub, ChatMessage, Presentation
from sqlalchemy.orm import joinedload
from sqlalchemy import text, func, and_, or_
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import bleach
import os
from openai import OpenAI
from datetime import datetime, timedelta, timezone

import traceback
import sys

# Global exception handler
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    with open('error.log', 'a') as f:
        f.write("".join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
        f.write("
" + "="*50 + "
")

sys.excepthook = handle_exception


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    os.makedirs(app.instance_path, exist_ok=True)
    
    csrf = CSRFProtect(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        flash("Sahifa eskirgan. Jadval yangilandi, amalni qayta bajaring.", "danger")
        return redirect(url_for('manage_schedule'))
    
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["200 per day", "50 per hour"]
    )
    
    db.init_app(app)
    
    with app.app_context():
        from sqlalchemy import text

        # 1. Bazani yaratish (agar yo'q bo'lsa)
        db.create_all()

        # 2. NEWS jadvalidagi image_url ustunini tekshirish va qo'shish
        try:
            result = db.session.execute(text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='news' AND column_name='image_url'"
            )).fetchone()
            
            if not result:
                print("⚠️ 'image_url' ustuni topilmadi. Qo'shilmoqda...")
                db.session.execute(text("ALTER TABLE news ADD COLUMN image_url TEXT;"))
                db.session.commit()
                print("✅ 'image_url' ustuni muvaffaqiyatli qo'shildi!")
        except Exception as e:
            print(f"❌ Bazani yangilashda xatolik: {e}")
            db.session.rollback()

        try:
            if db.engine.dialect.name == 'sqlite':
                columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(tests)"))]
                if 'created_by_teacher_id' not in columns:
                    db.session.execute(text("ALTER TABLE tests ADD COLUMN created_by_teacher_id INTEGER"))
                    db.session.commit()
            else:
                result = db.session.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='tests' AND column_name='created_by_teacher_id'")).fetchone()
                if not result:
                    db.session.execute(text("ALTER TABLE tests ADD COLUMN created_by_teacher_id INTEGER REFERENCES teachers(id)"))
                    db.session.commit()
        except Exception as e:
            print(f"Test ustunini yangilashda xatolik: {e}")
            db.session.rollback()
            
        # 3. CLUB jadvalini yaratish
        try:
            db.session.execute(text("CREATE TABLE IF NOT EXISTS club (id SERIAL PRIMARY KEY, name VARCHAR(200) NOT NULL, description TEXT, teacher_id INTEGER REFERENCES teachers(id), max_students INTEGER DEFAULT 20, schedule VARCHAR(100), school_id INTEGER NOT NULL REFERENCES schools(id));"))
            db.session.execute(text("CREATE TABLE IF NOT EXISTS student_club (id SERIAL PRIMARY KEY, student_id INTEGER REFERENCES students(id), club_id INTEGER REFERENCES club(id), joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);"))
            db.session.commit()
            print("✅ 'club' va 'student_club' jadvallari yaratildi!")
        except Exception as e:
            print(f"❌ Club jadvalini yaratishda xatolik: {e}")
            db.session.rollback()
            
        # Achievement qo'shish (agar bo'lmasa)
        if not Achievement.query.first():
            achievements = [
                Achievement(name="Birinchi Qadam", description="Birinchi testni topshirdingiz", xp_reward=50, condition_type="first_test"),
                Achievement(name="Matematika Ustasi", description="10 ta test topshirdingiz", icon="", xp_reward=200, condition_type="test_count", condition_value=10),
                Achievement(name="Mukammallik", description="100% natija oldingiz", icon="", xp_reward=100, condition_type="perfect_score")
            ]
            db.session.add_all(achievements)
            db.session.commit()

    def sanitize_input(text):
        if text: return bleach.clean(text, tags=[], attributes={}, strip=True)
        return text

    @app.context_processor
    def header_notifications():
        unread_count = 0
        notification_items = []
        try:
            role = session.get('user_role')
            school_id = session.get('school_id')
            if school_id and role in {'admin', 'student', 'teacher'}:
                if role == 'admin':
                    messages = ChatMessage.query.filter_by(school_id=school_id).order_by(ChatMessage.created_at.desc()).limit(8).all()
                    unread_count = ChatMessage.query.filter_by(school_id=school_id).count()
                else:
                    user_id = session.get('student_id') if role == 'student' else session.get('teacher_id')
                    messages = ChatMessage.query.filter(
                        ChatMessage.school_id == school_id,
                        ChatMessage.recipient_type == role,
                        ChatMessage.recipient_id == user_id
                    ).order_by(ChatMessage.created_at.desc()).limit(8).all()
                    unread_count = ChatMessage.query.filter(
                        ChatMessage.school_id == school_id,
                        ChatMessage.recipient_type == role,
                        ChatMessage.recipient_id == user_id
                    ).count()

                teacher_ids = {item.sender_id for item in messages if item.sender_type == 'teacher'}
                student_ids = {item.sender_id for item in messages if item.sender_type == 'student'}
                teachers = {item.id: f"{item.first_name} {item.last_name}" for item in Teacher.query.filter(Teacher.id.in_(teacher_ids)).all()} if teacher_ids else {}
                students = {item.id: f"{item.first_name} {item.last_name}" for item in Student.query.filter(Student.id.in_(student_ids)).all()} if student_ids else {}
                for item in messages:
                    if item.sender_type == 'admin':
                        sender_name = 'Admin'
                    elif item.sender_type == 'teacher':
                        sender_name = teachers.get(item.sender_id, 'O‘qituvchi')
                    else:
                        sender_name = students.get(item.sender_id, 'O‘quvchi')
                    notification_items.append({'sender': sender_name, 'body': item.body, 'time': item.created_at.strftime('%d.%m.%Y %H:%M')})
        except Exception as error:
            app.logger.warning("Bildirishnomalarni yuklashda xatolik: %s", error)
            db.session.rollback()
        return {'header_notification_count': unread_count, 'header_notifications': notification_items}

    def remove_student_records(student_id):
        StudentClub.query.filter_by(student_id=student_id).delete(synchronize_session=False)
        StudentAchievement.query.filter_by(student_id=student_id).delete(synchronize_session=False)
        TestResult.query.filter_by(student_id=student_id).delete(synchronize_session=False)
        ChatMessage.query.filter(
            or_(
                and_(ChatMessage.sender_type == 'student', ChatMessage.sender_id == student_id),
                and_(ChatMessage.recipient_type == 'student', ChatMessage.recipient_id == student_id)
            )
        ).delete(synchronize_session=False)

    def remove_teacher_records(teacher_id, school_id):
        clubs = Club.query.filter_by(teacher_id=teacher_id, school_id=school_id).all()
        for club in clubs:
            StudentClub.query.filter_by(club_id=club.id).delete(synchronize_session=False)
            db.session.delete(club)
        TeacherClassAssignment.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
        Schedule.query.filter_by(teacher_id=teacher_id, school_id=school_id).update(
            {Schedule.teacher_id: None}, synchronize_session=False
        )
        ChatMessage.query.filter(
            or_(
                and_(ChatMessage.sender_type == 'teacher', ChatMessage.sender_id == teacher_id),
                and_(ChatMessage.recipient_type == 'teacher', ChatMessage.recipient_id == teacher_id)
            )
        ).delete(synchronize_session=False)

    def save_teacher_profile_image(uploaded_file, teacher_id):
        if not uploaded_file or not uploaded_file.filename:
            return None
        try:
            filename = secure_filename(uploaded_file.filename)
            extension = os.path.splitext(filename)[1].lower()
            if not extension: extension = '.jpg'
            if extension not in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic'}:
                flash("Rasm formati noto'g'ri (faqat JPG, PNG, WEBP).", "warning")
                return None
            upload_dir = os.path.join(app.static_folder, 'uploads', 'teachers')
            os.makedirs(upload_dir, exist_ok=True)
            saved_name = f"teacher_{teacher_id}{extension}"
            uploaded_file.save(os.path.join(upload_dir, saved_name))
            return url_for('static', filename=f'uploads/teachers/{saved_name}')
        except Exception as e:
            print(f"Rasm yuklashda xato: {e}")
            flash("Rasmni yuklashda xatolik yuz berdi.", "danger")
            return None

    def save_student_profile_image(uploaded_file, student_id):
        if not uploaded_file or not uploaded_file.filename:
            return None
        try:
            filename = secure_filename(uploaded_file.filename)
            extension = os.path.splitext(filename)[1].lower()
            # Agar kengaytma bo'lmasa, .jpg deb olamiz
            if not extension: extension = '.jpg'
            if extension not in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic'}:
                flash("Rasm formati noto'g'ri (faqat JPG, PNG, WEBP).", "warning")
                return None
            upload_dir = os.path.join(app.static_folder, 'uploads', 'students')
            os.makedirs(upload_dir, exist_ok=True)
            saved_name = f"student_{student_id}{extension}"
            uploaded_file.save(os.path.join(upload_dir, saved_name))
            return url_for('static', filename=f'uploads/students/{saved_name}')
        except Exception as e:
            print(f"Rasm yuklashda xato: {e}")
            flash("Rasmni yuklashda xatolik yuz berdi.", "danger")
            return None
        
    @app.before_request
    def check_session_timeout():
        if 'school_id' in session and 'last_activity' in session:
            now = datetime.now(timezone.utc)
            last = session.get('last_activity')
            if last.tzinfo is None: last = last.replace(tzinfo=timezone.utc)
            if now - last > timedelta(minutes=30):
                session.clear()
                flash("Sessiya tugadi. Qaytadan kiring.", "warning")
                return redirect(url_for('home'))
        if 'school_id' in session:
            session['last_activity'] = datetime.now(timezone.utc)

    @app.route("/")
    def home():
        if 'school_id' in session:
            role = session.get('user_role')
            if role == 'student': return redirect(url_for('student_dashboard'))
            if role == 'teacher': return redirect(url_for('teacher_dashboard'))
            return redirect(url_for('dashboard'))
        
        public_news = News.query.order_by(News.created_at.desc()).limit(6).all()
        return render_template("login.html", news_list=public_news)
        
    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            name = sanitize_input(request.form.get('school_name'))
            address = sanitize_input(request.form.get('address'))
            phone = sanitize_input(request.form.get('phone'))
            email = sanitize_input(request.form.get('email'))
            login = sanitize_input(request.form.get('login'))
            password = request.form.get('password')
            
            if School.query.filter_by(email=email).first():
                flash("Bu email allaqachon ro'yxatdan o'tgan!", "danger")
                return redirect(url_for('register'))
                
            if School.query.filter_by(login=login).first():
                flash("Bu login band! Boshqa login tanlang.", "danger")
                return redirect(url_for('register'))
            
            password_hash = generate_password_hash(password)
            new_school = School(name=name, address=address, phone=phone, email=email, login=login, password_hash=password_hash)
            try:
                db.session.add(new_school); db.session.commit()
                flash("Muvaffaqiyatli ro'yxatdan o'tdingiz! Endi kirishingiz mumkin.", "success")
                return redirect(url_for('home'))
            except Exception as e:
                db.session.rollback()
                flash(f"Xatolik yuz berdi: {e}", "danger")
                
        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    def login():
        login_input = sanitize_input(request.form.get('username'))
        password_input = request.form.get('password')
        
        school = School.query.filter_by(login=login_input).first()
        if school and check_password_hash(school.password_hash, password_input):
            session.permanent = True; session['school_id'] = school.id; session['school_name'] = school.name
            session['user_role'] = 'admin'; session['last_activity'] = datetime.now(timezone.utc)
            return redirect(url_for('dashboard'))
        
        student = Student.query.filter_by(login=login_input).first()
        if student and check_password_hash(student.password_hash, password_input):
            session.permanent = True; session['school_id'] = student.school_id; session['student_id'] = student.id
            session['student_name'] = f"{student.first_name} {student.last_name}"; session['user_role'] = 'student'
            session['last_activity'] = datetime.now(timezone.utc)
            return redirect(url_for('student_dashboard'))
            
        teacher = Teacher.query.filter_by(login=login_input).first()
        if teacher and check_password_hash(teacher.password_hash, password_input):
            session.permanent = True; session['school_id'] = teacher.school_id; session['teacher_id'] = teacher.id
            session['teacher_name'] = f"{teacher.first_name} {teacher.last_name}"; session['user_role'] = 'teacher'
            session['last_activity'] = datetime.now(timezone.utc)
            return redirect(url_for('teacher_dashboard'))
            
        # Futuristik Xato Sahifasi
        error_html = """
        <!DOCTYPE html>
        <html lang="uz">
        <head>
            <meta charset="UTF-8">
            <title>Kirish Rad Etildi</title>
            <style>
                body { 
                    margin: 0; padding: 0; height: 100vh; display: flex; justify-content: center; align-items: center; 
                    background: #0f172a; font-family: 'Segoe UI', sans-serif; overflow: hidden; color: white;
                }
                .error-container { text-align: center; position: relative; z-index: 10; }
                .glitch-text { 
                    font-size: 2rem; font-weight: 800; color: #ef4444; text-transform: uppercase; 
                    letter-spacing: 2px; animation: glitch 1s infinite;
                }
                .sub-text { color: #94a3b8; margin-top: 10px; font-size: 1rem; }
                .btn-retry { 
                    margin-top: 30px; padding: 12px 30px; background: linear-gradient(45deg, #3b82f6, #8b5cf6); 
                    border: none; border-radius: 50px; color: white; font-weight: bold; cursor: pointer; 
                    transition: 0.3s; box-shadow: 0 0 20px rgba(59, 130, 246, 0.5);
                }
                .btn-retry:hover { transform: scale(1.05); box-shadow: 0 0 30px rgba(139, 92, 246, 0.7); }
                
                @keyframes glitch {
                    0% { transform: translate(0); }
                    20% { transform: translate(-2px, 2px); }
                    40% { transform: translate(-2px, -2px); }
                    60% { transform: translate(2px, 2px); }
                    80% { transform: translate(2px, -2px); }
                    100% { transform: translate(0); }
                }
                
                /* Orqa fon effektlari */
                .bg-grid { 
                    position: absolute; width: 200%; height: 200%; top: -50%; left: -50%; 
                    background-image: linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
                    linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
                    background-size: 50px 50px; transform: perspective(500px) rotateX(60deg); 
                    animation: moveGrid 10s linear infinite;
                }
                @keyframes moveGrid { 0% { transform: perspective(500px) rotateX(60deg) translateY(0); } 100% { transform: perspective(500px) rotateX(60deg) translateY(50px); } }
            </style>
        </head>
        <body>
            <div class="bg-grid"></div>
            <div class="error-container">
                <div style="font-size: 4rem; margin-bottom: 20px;">🛡️</div>
                <div class="glitch-text">KIRISH RAD ETILDI</div>
                <p class="sub-text">Tizim xavfsizligi: Login yoki parol noto'g'ri kiritildi.</p>
                <button onclick="window.history.back()" class="btn-retry">Qayta Urinish </button>
            </div>
        </body>
        </html>
        """
        return """<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SYSTEM LOCKED // ACCESS DENIED</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Share+Tech+Mono&display=swap" rel="stylesheet">
<style>
    :root {
        --primary: #0ff;
        --secondary: #f0f;
        --bg: #050505;
        --glass: rgba(10, 20, 30, 0.6);
    }
    
    body {
        margin: 0;
        padding: 0;
        background-color: var(--bg);
        color: #fff;
        font-family: 'Share Tech Mono', monospace;
        height: 100vh;
        display: flex;
        justify-content: center;
        align-items: center;
        overflow: hidden;
        perspective: 1000px;
    }

    /* Matrix Background Canvas */
    #matrix {
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 100%;
        z-index: -1;
        opacity: 0.3;
    }

    /* CRT Scanline Effect */
    .scanlines {
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        background: linear-gradient(to bottom, rgba(255,255,255,0), rgba(255,255,255,0) 50%, rgba(0,0,0,0.2) 50%, rgba(0,0,0,0.2));
        background-size: 100% 4px;
        pointer-events: none;
        z-index: 10;
        animation: scroll 10s linear infinite;
    }
    @keyframes scroll { 0% {background-position: 0 0;} 100% {background-position: 0 100%;} }

    /* Main Card Container */
    .card {
        position: relative;
        width: 500px;
        max-width: 90%;
        padding: 50px 40px;
        background: var(--glass);
        border: 1px solid var(--primary);
        box-shadow: 0 0 20px rgba(0, 255, 255, 0.2), inset 0 0 50px rgba(0, 255, 255, 0.05);
        backdrop-filter: blur(10px);
        transform-style: preserve-3d;
        animation: float 6s ease-in-out infinite;
        clip-path: polygon(
            0 0, 
            100% 0, 
            100% calc(100% - 40px), 
            calc(100% - 40px) 100%, 
            0 100%
        );
    }

    /* Decorative Corners */
    .card::before {
        content: '';
        position: absolute;
        top: -2px; left: -2px;
        width: 30px; height: 30px;
        border-top: 3px solid var(--primary);
        border-left: 3px solid var(--primary);
    }
    .card::after {
        content: '';
        position: absolute;
        bottom: -2px; right: -2px;
        width: 30px; height: 30px;
        border-bottom: 3px solid var(--primary);
        border-right: 3px solid var(--primary);
    }

    @keyframes float {
        0%, 100% { transform: translateY(0) rotateX(0deg); }
        50% { transform: translateY(-15px) rotateX(2deg); }
    }

    /* Glitch Title */
    h1 {
        font-family: 'Orbitron', sans-serif;
        text-align: center;
        font-size: 2.5rem;
        margin: 0 0 20px;
        color: #fff;
        text-transform: uppercase;
        letter-spacing: 4px;
        position: relative;
        text-shadow: 2px 2px var(--secondary);
    }
    
    h1::before, h1::after {
        content: attr(data-text);
        position: absolute;
        top: 0; left: 0;
        width: 100%; height: 100%;
        background: var(--bg);
    }
    
    h1::before {
        left: 2px;
        text-shadow: -1px 0 #ff00c1;
        clip: rect(44px, 450px, 56px, 0);
        animation: glitch-anim 5s infinite linear alternate-reverse;
    }
    
    h1::after {
        left: -2px;
        text-shadow: -1px 0 #00fff9;
        clip: rect(44px, 450px, 56px, 0);
        animation: glitch-anim2 5s infinite linear alternate-reverse;
    }

    @keyframes glitch-anim {
        0% { clip: rect(12px, 9999px, 32px, 0); }
        5% { clip: rect(85px, 9999px, 100px, 0); }
        10% { clip: rect(10px, 9999px, 80px, 0); }
        100% { clip: rect(12px, 9999px, 32px, 0); }
    }
    @keyframes glitch-anim2 {
        0% { clip: rect(65px, 9999px, 100px, 0); }
        5% { clip: rect(10px, 9999px, 40px, 0); }
        10% { clip: rect(90px, 9999px, 100px, 0); }
        100% { clip: rect(65px, 9999px, 100px, 0); }
    }

    /* Message Box */
    .message {
        text-align: center;
        color: #aaa;
        font-size: 1.1rem;
        margin-bottom: 40px;
        border-top: 1px solid rgba(0, 255, 255, 0.3);
        border-bottom: 1px solid rgba(0, 255, 255, 0.3);
        padding: 20px 0;
        background: rgba(0, 0, 0, 0.4);
        position: relative;
    }
    
    .message::before {
        content: 'WARNING';
        position: absolute;
        top: -10px;
        left: 50%;
        transform: translateX(-50%);
        background: var(--bg);
        padding: 0 10px;
        color: var(--secondary);
        font-size: 0.8rem;
        letter-spacing: 2px;
    }

    /* Button */
    .btn {
        display: block;
        width: 100%;
        padding: 18px;
        background: transparent;
        color: var(--primary);
        border: 2px solid var(--primary);
        font-family: 'Orbitron', sans-serif;
        font-size: 1.2rem;
        font-weight: bold;
        text-transform: uppercase;
        letter-spacing: 3px;
        cursor: pointer;
        position: relative;
        overflow: hidden;
        transition: all 0.3s;
        text-decoration: none;
        text-align: center;
        box-sizing: border-box;
        clip-path: polygon(10px 0, 100% 0, 100% calc(100% - 10px), calc(100% - 10px) 100%, 0 100%, 0 10px);
    }

    .btn:hover {
        background: var(--primary);
        color: #000;
        box-shadow: 0 0 40px var(--primary);
        transform: scale(1.02);
    }
    
    .btn:active {
        transform: scale(0.98);
    }

    /* Loading Bar Animation */
    .loader {
        height: 2px;
        width: 100%;
        background: #333;
        margin-top: 20px;
        position: relative;
        overflow: hidden;
    }
    .loader::after {
        content: '';
        position: absolute;
        top: 0; left: 0;
        width: 50%;
        height: 100%;
        background: var(--primary);
        animation: load 2s infinite ease-in-out;
    }
    @keyframes load {
        0% { transform: translateX(-100%); }
        100% { transform: translateX(200%); }
    }

</style>
</head>
<body>
    <canvas id="matrix"></canvas>
    <div class="scanlines"></div>
    
    <div class="card">
        <h1 data-text="KIRISH RAD ETILDI">KIRISH RAD ETILDI</h1>
        
        <div class="message">
            [SYSTEM ERROR]: Login yoki parol noto'g'ri.<br>
            Xavfsizlik protokoli faollashtirildi.
        </div>
        
        <a href="/login" onclick="fetch('/logout').then(() => window.location.href='/login'); return false;" class="btn">KIRISHGA QAYTISH >></a>
        
        <div class="loader"></div>
    </div>

    <script>
        // Matrix Rain Effect
        const c = document.getElementById('matrix');
        const ctx = c.getContext('2d');
        c.width = window.innerWidth;
        c.height = window.innerHeight;
        
        const chars = 'アァカサタナハマヤャラワガザダバパイィキシチニヒミリヂビピウゥクスツヌフムユュルグズブヅプエェケセテネヘメレゲゼデベペオォコソトノホモヨョロヲゴゾドボポヴッンABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        const fontSize = 14;
        const columns = c.width / fontSize;
        const drops = [];
        
        for(let i = 0; i < columns; i++) drops[i] = 1;
        
        function draw() {
            ctx.fillStyle = 'rgba(5, 5, 5, 0.05)';
            ctx.fillRect(0, 0, c.width, c.height);
            ctx.fillStyle = '#0F0';
            ctx.font = fontSize + 'px monospace';
            
            for(let i = 0; i < drops.length; i++) {
                const text = chars.charAt(Math.floor(Math.random() * chars.length));
                ctx.fillText(text, i * fontSize, drops[i] * fontSize);
                
                if(drops[i] * fontSize > c.height && Math.random() > 0.975) drops[i] = 0;
                drops[i]++;
            }
        }
        setInterval(draw, 35);
        
        window.addEventListener('resize', () => {
            c.width = window.innerWidth;
            c.height = window.innerHeight;
        });
    </script>
</body>
</html>""", 401

    # --- ADMIN DASHBOARD ---
    @app.route("/dashboard")
    def dashboard():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']; school = School.query.get(sid)
        school_classes = Class.query.filter_by(school_id=sid).order_by(Class.name).all()
        class_labels = [item.name for item in school_classes]
        class_student_counts = [Student.query.filter_by(school_id=sid, class_id=item.id).count() for item in school_classes]
        schedule_items = Schedule.query.filter_by(school_id=sid).all()
        day_names = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba"]
        schedule_counts = [sum(item.day_of_week == day for item in schedule_items) for day in day_names]
        try:
            club_class_rows = db.session.query(Class.name, func.count(StudentClub.id)) \
                .join(Student, Student.class_id == Class.id) \
                .join(StudentClub, Student.id == StudentClub.student_id) \
                .filter(Student.school_id == sid) \
                .group_by(Class.name) \
                .order_by(Class.name).all()
        except Exception as error:
            app.logger.warning("To'garak statistikasi yuklanmadi: %s", error)
            db.session.rollback()
            club_class_rows = []
        results = TestResult.query.join(Student).filter(Student.school_id == sid).all()
        average_score = round(sum(item.percentage or 0 for item in results) / len(results), 1) if results else 0
        passed_results = sum((item.percentage or 0) >= 60 for item in results)
        return render_template("dashboard.html", school=school, 
            class_count=Class.query.filter_by(school_id=sid).count(),
            student_count=Student.query.filter_by(school_id=sid).count(),
            teacher_count=Teacher.query.filter_by(school_id=sid).count(),
            test_count=Test.query.filter_by(school_id=sid).count(),
            book_count=Book.query.filter_by(school_id=sid).count(),
            news_count=News.query.filter_by(school_id=sid).count(),
            clubs_count=Club.query.filter_by(school_id=sid).count(),
            schedule_count=len(schedule_items),
            average_score=average_score,
            passed_results=passed_results,
            result_count=len(results),
            class_labels=json.dumps(class_labels),
            class_student_counts=json.dumps(class_student_counts),
            day_names=json.dumps(day_names),
            schedule_counts=json.dumps(schedule_counts),
            club_class_labels=json.dumps([row[0] for row in club_class_rows]),
            club_class_counts=json.dumps([row[1] for row in club_class_rows]))

    # --- O'QITUVCHI DASHBOARD ---
    @app.route("/teacher_dashboard")
    def teacher_dashboard():
        if 'school_id' not in session or session.get('user_role') != 'teacher': return redirect(url_for('home'))
        tid = session['teacher_id']
        teacher = Teacher.query.options(joinedload(Teacher.subject)).get(tid)
        my_schedules = Schedule.query.filter_by(teacher_id=tid).options(
            joinedload(Schedule.student_class), joinedload(Schedule.subject)
        ).order_by(
            db.case({"Dushanba":1,"Seshanba":2,"Chorshanba":3,"Payshanba":4,"Juma":5,"Shanba":6}, value=Schedule.day_of_week),
            Schedule.start_time
        ).all()
        days_order = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba"]
        grouped = {d: [] for d in days_order}
        unique_classes = set()
        assigned_classes = TeacherClassAssignment.query.filter_by(teacher_id=tid).all()
        unique_classes.update(assignment.student_class for assignment in assigned_classes)
        for s in my_schedules:
            if s.day_of_week in grouped:
                grouped[s.day_of_week].append(s)
                if s.student_class: unique_classes.add(s.student_class)
        clubs = Club.query.filter_by(school_id=session['school_id']).all()
        return render_template("teacher_dashboard.html", teacher=teacher, schedule=grouped, my_classes=list(unique_classes), clubs=clubs)

    # --- O'QITUVCHI-O'QUVCHI ICHKI CHAT ---
    
# Server restart trigger - fix bad gateway




# Server restart at Mon Oct  5 11:00:19 AM CEST 2026

# Emergency restart 2584104242367211027

# Emergency restart -8371375395446362482

# Emergency restart -6872958101979194201

# Emergency restart 5565573326811307490
