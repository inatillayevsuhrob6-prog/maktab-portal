from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from config import Config
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from backend.models import School, Class, Student, Teacher, TeacherClassAssignment, Subject, Test, TestQuestion, TestResult, Achievement, StudentAchievement, Schedule, Book, News, Club, StudentClub, ChatMessage
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

    @app.route("/login", methods=["POST"])
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
            
        return "Login yoki parol xato!", 401

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
        club_class_rows = db.session.query(Class.name, func.count(StudentClub.id)) \
            .join(Student, Student.class_id == Class.id) \
            .join(StudentClub, Student.id == StudentClub.student_id) \
            .filter(Student.school_id == sid) \
            .group_by(Class.name) \
            .order_by(Class.name).all()
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
    if 'user_role' not in session: return redirect(url_for('login'))
    return "<h1>O'qituvchi Kabineti</h1><p>Saboxat Nortosheva - Fan: Mental</p><a href='/dashboard'>Ortga</a>"

@app.route("/delete_teacher/<int:id>")
def delete_teacher(id):
    if 'user_role' not in session: return redirect(url_for('login'))
    return f"<h1>O'qituvchi (ID: {id}) o'chirildi!</h1><p>(Demo rejim)</p><a href='/teachers'>Ortga</a>"

@app.route("/presentations")
def presentations():
    if 'user_role' not in session: return redirect(url_for('login'))
    return "<h1>Taqdimotlar</h1><p>Tez orada ishga tushadi.</p><a href='/dashboard'>Ortga</a>"

@app.route("/chat")
def chat():
    if 'user_role' not in session: return redirect(url_for('login'))
    return "<h1>Ichki Chat</h1><p>Hozircha faol emas.</p><a href='/dashboard'>Ortga</a>"

@app.route("/library")
def library():
    if 'user_role' not in session: return redirect(url_for('login'))
    return "<h1>Kutubxona</h1><p>Yuklanmoqda...</p><a href='/dashboard'>Ortga</a>"

@app.route("/students")
def students():
    if 'user_role' not in session: return redirect(url_for('login'))
    return "<h1>O'quvchilar</h1><p>Ro'yxat tez orada chiqadi.</p><a href='/dashboard'>Ortga</a>"
