from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from config import Config
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from backend.models import School, Class, Student, Teacher, TeacherClassAssignment, Subject, Test, TestQuestion, TestResult, Achievement, StudentAchievement, Schedule, Book, News
from sqlalchemy.orm import joinedload
from sqlalchemy import text
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import bleach
import os
from openai import OpenAI
from datetime import datetime, timedelta, timezone

def migrate_schedule_class_column():
    if db.engine.dialect.name != 'sqlite':
        return
    columns = db.session.execute(text('PRAGMA table_info(schedules)')).mappings().all()
    class_column = next((column for column in columns if column['name'] == 'class_id'), None)
    if not class_column or not class_column['notnull']:
        return
    db.session.execute(text('PRAGMA foreign_keys=OFF'))
    db.session.execute(text('ALTER TABLE schedules RENAME TO schedules_old'))
    db.session.execute(text('''
        CREATE TABLE schedules (
            id INTEGER NOT NULL PRIMARY KEY,
            day_of_week VARCHAR(20) NOT NULL,
            start_time VARCHAR(5) NOT NULL,
            end_time VARCHAR(5) NOT NULL,
            room_number VARCHAR(10),
            school_id INTEGER NOT NULL,
            class_id INTEGER,
            subject_id INTEGER NOT NULL,
            teacher_id INTEGER,
            FOREIGN KEY(school_id) REFERENCES schools (id),
            FOREIGN KEY(class_id) REFERENCES classes (id),
            FOREIGN KEY(subject_id) REFERENCES subjects (id),
            FOREIGN KEY(teacher_id) REFERENCES teachers (id)
        )
    '''))
    db.session.execute(text('''
        INSERT INTO schedules (id, day_of_week, start_time, end_time, room_number, school_id, class_id, subject_id, teacher_id)
        SELECT id, day_of_week, start_time, end_time, room_number, school_id, class_id, subject_id, teacher_id
        FROM schedules_old
    '''))
    db.session.execute(text('DROP TABLE schedules_old'))
    db.session.execute(text('PRAGMA foreign_keys=ON'))
    db.session.commit()

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
        db.create_all()
        migrate_schedule_class_column()
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

    def save_teacher_profile_image(uploaded_file, teacher_id):
        if not uploaded_file or not uploaded_file.filename:
            return None
        filename = secure_filename(uploaded_file.filename)
        extension = os.path.splitext(filename)[1].lower()
        if extension not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            raise ValueError("Rasm faqat JPG, JPEG, PNG, GIF yoki WEBP formatida bo'lishi kerak.")
        upload_dir = os.path.join(app.static_folder, 'uploads', 'teachers')
        os.makedirs(upload_dir, exist_ok=True)
        saved_name = f"teacher_{teacher_id}{extension}"
        uploaded_file.save(os.path.join(upload_dir, saved_name))
        return url_for('static', filename=f'uploads/teachers/{saved_name}')

    def save_student_profile_image(uploaded_file, student_id):
        if not uploaded_file or not uploaded_file.filename:
            return None
        filename = secure_filename(uploaded_file.filename)
        extension = os.path.splitext(filename)[1].lower()
        if extension not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            raise ValueError("Rasm faqat JPG, JPEG, PNG, GIF yoki WEBP formatida bo'lishi kerak.")
        upload_dir = os.path.join(app.static_folder, 'uploads', 'students')
        os.makedirs(upload_dir, exist_ok=True)
        saved_name = f"student_{student_id}{extension}"
        uploaded_file.save(os.path.join(upload_dir, saved_name))
        return url_for('static', filename=f'uploads/students/{saved_name}')
        
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
        return render_template("login.html")
        
    @app.route("/register")
    def register_page(): return render_template("register.html")

    @app.route("/register", methods=["POST"])
    @limiter.limit("5 per minute")
    def register():
        name = sanitize_input(request.form.get('school_name'))
        address = sanitize_input(request.form.get('address'))
        phone = sanitize_input(request.form.get('phone'))
        email = sanitize_input(request.form.get('email'))
        login = sanitize_input(request.form.get('login'))
        password = request.form.get('password')
        if School.query.filter_by(login=login).first(): return "Login band.", 409
        password_hash = generate_password_hash(password)
        new_school = School(name=name, address=address, phone=phone, email=email, login=login, password_hash=password_hash)
        try:
            db.session.add(new_school); db.session.commit(); return redirect(url_for('home'))
        except Exception as e:
            db.session.rollback(); return f"Xatolik: {e}"

    @app.route("/login", methods=["POST"])
    @limiter.limit("10 per minute")
    def login():
        login_input = sanitize_input(request.form.get('username'))
        password_input = request.form.get('password')
        
        # Admin login
        school = School.query.filter_by(login=login_input).first()
        if school and check_password_hash(school.password_hash, password_input):
            session.permanent = True; session['school_id'] = school.id; session['school_name'] = school.name
            session['user_role'] = 'admin'; session['last_activity'] = datetime.now(timezone.utc)
            return redirect(url_for('dashboard'))
        
        # O'quvchi login
        student = Student.query.filter_by(login=login_input).first()
        if student and check_password_hash(student.password_hash, password_input):
            session.permanent = True; session['school_id'] = student.school_id; session['student_id'] = student.id
            session['student_name'] = f"{student.first_name} {student.last_name}"; session['user_role'] = 'student'
            session['last_activity'] = datetime.now(timezone.utc)
            return redirect(url_for('student_dashboard'))
            
        # O'qituvchi login
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
            schedule_count=len(schedule_items),
            average_score=average_score,
            passed_results=passed_results,
            result_count=len(results),
            class_labels=json.dumps(class_labels),
            class_student_counts=json.dumps(class_student_counts),
            day_names=json.dumps(day_names),
            schedule_counts=json.dumps(schedule_counts))

    # --- O'QITUVCHI DASHBOARD ---
    @app.route("/teacher_dashboard")
    def teacher_dashboard():
        if 'school_id' not in session or session.get('user_role') != 'teacher': return redirect(url_for('home'))
        tid = session['teacher_id']
        teacher = Teacher.query.options(joinedload(Teacher.subject)).get(tid)
        
        my_schedules = Schedule.query.filter_by(teacher_id=tid).options(
            joinedload(Schedule.student_class),
            joinedload(Schedule.subject)
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
                if s.student_class:
                    unique_classes.add(s.student_class)
                
        return render_template("teacher_dashboard.html", 
                               teacher=teacher, 
                               schedule=grouped, 
                               my_classes=list(unique_classes))

    # --- O'QITUVCHI PROFIL SOZLAMALARI ---
    @app.route("/teacher_profile", methods=["GET", "POST"])
    def teacher_profile():
        if 'school_id' not in session or session.get('user_role') != 'teacher': return redirect(url_for('home'))
        tid = session['teacher_id']
        teacher = Teacher.query.get(tid)
        
        if request.method == "POST":
            action = request.form.get('action')
            
            try:
                if action == 'update_info':
                    teacher.first_name = sanitize_input(request.form.get('first_name'))
                    teacher.last_name = sanitize_input(request.form.get('last_name'))
                    teacher.phone = sanitize_input(request.form.get('phone'))
                    uploaded_image = request.files.get('profile_image')
                    if uploaded_image and uploaded_image.filename:
                        teacher.profile_pic = save_teacher_profile_image(uploaded_image, teacher.id)
                    else:
                        teacher.profile_pic = sanitize_input(request.form.get('profile_pic')) or teacher.profile_pic
                    session['teacher_name'] = f"{teacher.first_name} {teacher.last_name}"
                    flash("Ma'lumotlar muvaffaqiyatli saqlandi!", "success")
                    
                elif action == 'change_password':
                    new_pass = request.form.get('new_password')
                    if new_pass and len(new_pass) >= 6:
                        teacher.password_hash = generate_password_hash(new_pass)
                        flash("Parol muvaffaqiyatli o'zgartirildi!", "success")
                    else:
                        flash("Parol kamida 6 ta belgidan iborat bo'lishi kerak.", "danger")
                        
                elif action == 'change_login':
                    new_login = sanitize_input(request.form.get('new_login'))
                    existing = Teacher.query.filter_by(login=new_login).first()
                    if not existing or existing.id == teacher.id:
                        teacher.login = new_login
                        flash("Login o'zgartirildi! Keyingi safar yangi login bilan kiring.", "success")
                    else:
                        flash("Bu login allaqachon band.", "danger")
                        
                db.session.commit()
                
            except Exception as e:
                db.session.rollback()
                flash(f"Xatolik yuz berdi: {str(e)}", "danger")
                
            return redirect(url_for('teacher_profile'))
            
        return render_template("teacher_profile.html", teacher=teacher)

    # --- BOSHQA ROUTE LAR ---
    @app.route("/classes")
    def classes():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        classes_with_counts = [{'id': c.id, 'name': c.name, 'student_count': Student.query.filter_by(class_id=c.id, school_id=sid).count()} for c in Class.query.filter_by(school_id=sid).all()]
        return render_template("classes.html", classes=classes_with_counts)

    @app.route("/add_class", methods=["POST"])
    def add_class():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        db.session.add(Class(name=sanitize_input(request.form.get('class_name')), school_id=session['school_id'])); db.session.commit()
        return redirect(url_for('classes'))

    @app.route("/students")
    def students():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']; query = Student.query.filter_by(school_id=sid)
        cf = request.args.get('class_id')
        if cf: query = query.filter_by(class_id=cf)
        return render_template("students.html", students=query.all(), classes=Class.query.filter_by(school_id=sid).all(), current_class=cf)

    @app.route("/add_student", methods=["GET", "POST"])
    def add_student():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        if request.method == "POST":
            fn = sanitize_input(request.form.get('first_name')); ln = sanitize_input(request.form.get('last_name'))
            cid = request.form.get('class_id')
            db.session.add(Student(first_name=fn, last_name=ln, school_id=sid, class_id=cid, login=f"{fn.lower()}.{ln.lower()}", password_hash=generate_password_hash("123456")))
            try: db.session.commit()
            except: db.session.rollback()
            return redirect(url_for('students'))
        return render_template("add_student.html", classes=Class.query.filter_by(school_id=sid).all())

    @app.route("/teachers")
    def teachers():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        return render_template("teachers.html", teachers=Teacher.query.filter_by(school_id=session['school_id']).all())

    @app.route("/add_teacher", methods=["GET", "POST"])
    def add_teacher():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        if request.method == "POST":
            fn = sanitize_input(request.form.get('first_name')); ln = sanitize_input(request.form.get('last_name'))
            t_login = sanitize_input(request.form.get('login', f"{fn.lower()}.{ln.lower()}"))
            t_pass = request.form.get('password', '123456')
            if Teacher.query.filter_by(login=t_login).first():
                flash("Bu login allaqachon ishlatilgan. Boshqa login tanlang.", "danger")
                return render_template("add_teacher.html", classes=Class.query.filter_by(school_id=sid).order_by(Class.name).all())

            sn = sanitize_input(request.form.get('subject_name'))
            subj = Subject.query.filter_by(name=sn.strip(), school_id=sid).first()
            if not subj: subj = Subject(name=sn.strip(), school_id=sid); db.session.add(subj); db.session.flush()
            selected_class_ids = {int(value) for value in request.form.getlist('class_ids') if value.isdigit()}
            valid_classes = Class.query.filter(Class.school_id == sid, Class.id.in_(selected_class_ids)).all() if selected_class_ids else []
            lesson_day = request.form.get('lesson_day')
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            room_number = sanitize_input(request.form.get('room_number'))
            
            teacher = Teacher(first_name=fn, last_name=ln, school_id=sid, subject_id=subj.id, login=t_login, password_hash=generate_password_hash(t_pass))
            db.session.add(teacher); db.session.flush()
            db.session.add_all([TeacherClassAssignment(teacher_id=teacher.id, class_id=school_class.id, subject_id=subj.id) for school_class in valid_classes])
            if lesson_day and start_time and end_time:
                lesson_classes = valid_classes or [None]
                db.session.add_all([Schedule(day_of_week=lesson_day, start_time=start_time, end_time=end_time, room_number=room_number, school_id=sid, class_id=school_class.id if school_class else None, subject_id=subj.id, teacher_id=teacher.id) for school_class in lesson_classes])
            try: db.session.commit()
            except Exception as error:
                db.session.rollback()
                flash(f"O'qituvchi qo'shishda xatolik: {error}", "danger")
                return render_template("add_teacher.html", classes=Class.query.filter_by(school_id=sid).order_by(Class.name).all())
            return redirect(url_for('teachers'))
        return render_template("add_teacher.html", classes=Class.query.filter_by(school_id=sid).order_by(Class.name).all())

    @app.route("/tests")
    def tests():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        return render_template("tests.html", tests=Test.query.filter_by(school_id=session['school_id']).all())

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from config import Config
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from backend.models import School, Class, Student, Teacher, TeacherClassAssignment, Subject, Test, TestQuestion, TestResult, Achievement, StudentAchievement, Schedule, Book, News
from sqlalchemy.orm import joinedload
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import bleach
import os

from datetime import datetime, timedelta, timezone

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
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
        db.create_all()
        migrate_schedule_class_column()
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

    def save_teacher_profile_image(uploaded_file, teacher_id):
        if not uploaded_file or not uploaded_file.filename:
            return None
        filename = secure_filename(uploaded_file.filename)
        extension = os.path.splitext(filename)[1].lower()
        if extension not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            raise ValueError("Rasm faqat JPG, JPEG, PNG, GIF yoki WEBP formatida bo'lishi kerak.")
        upload_dir = os.path.join(app.static_folder, 'uploads', 'teachers')
        os.makedirs(upload_dir, exist_ok=True)
        saved_name = f"teacher_{teacher_id}{extension}"
        uploaded_file.save(os.path.join(upload_dir, saved_name))
        return url_for('static', filename=f'uploads/teachers/{saved_name}')
        
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
        return render_template("login.html")
        
    @app.route("/register")
    def register_page(): return render_template("register.html")

    @app.route("/register", methods=["POST"])
    @limiter.limit("5 per minute")
    def register():
        name = sanitize_input(request.form.get('school_name'))
        address = sanitize_input(request.form.get('address'))
        phone = sanitize_input(request.form.get('phone'))
        email = sanitize_input(request.form.get('email'))
        login = sanitize_input(request.form.get('login'))
        password = request.form.get('password')
        if School.query.filter_by(login=login).first(): return "Login band.", 409
        password_hash = generate_password_hash(password)
        new_school = School(name=name, address=address, phone=phone, email=email, login=login, password_hash=password_hash)
        try:
            db.session.add(new_school); db.session.commit(); return redirect(url_for('home'))
        except Exception as e:
            db.session.rollback(); return f"Xatolik: {e}"

    @app.route("/login", methods=["POST"])
    @limiter.limit("10 per minute")
    def login():
        login_input = sanitize_input(request.form.get('username'))
        password_input = request.form.get('password')
        
        # Admin login
        school = School.query.filter_by(login=login_input).first()
        if school and check_password_hash(school.password_hash, password_input):
            session.permanent = True; session['school_id'] = school.id; session['school_name'] = school.name
            session['user_role'] = 'admin'; session['last_activity'] = datetime.now(timezone.utc)
            return redirect(url_for('dashboard'))
        
        # O'quvchi login
        student = Student.query.filter_by(login=login_input).first()
        if student and check_password_hash(student.password_hash, password_input):
            session.permanent = True; session['school_id'] = student.school_id; session['student_id'] = student.id
            session['student_name'] = f"{student.first_name} {student.last_name}"; session['user_role'] = 'student'
            session['last_activity'] = datetime.now(timezone.utc)
            return redirect(url_for('student_dashboard'))
            
        # O'qituvchi login
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
            schedule_count=len(schedule_items),
            average_score=average_score,
            passed_results=passed_results,
            result_count=len(results),
            class_labels=json.dumps(class_labels),
            class_student_counts=json.dumps(class_student_counts),
            day_names=json.dumps(day_names),
            schedule_counts=json.dumps(schedule_counts))

    # --- O'QITUVCHI DASHBOARD ---
    @app.route("/teacher_dashboard")
    def teacher_dashboard():
        if 'school_id' not in session or session.get('user_role') != 'teacher': return redirect(url_for('home'))
        tid = session['teacher_id']
        teacher = Teacher.query.options(joinedload(Teacher.subject)).get(tid)
        
        my_schedules = Schedule.query.filter_by(teacher_id=tid).options(
            joinedload(Schedule.student_class),
            joinedload(Schedule.subject)
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
                if s.student_class:
                    unique_classes.add(s.student_class)
                
        return render_template("teacher_dashboard.html", 
                               teacher=teacher, 
                               schedule=grouped, 
                               my_classes=list(unique_classes))

    # --- O'QITUVCHI PROFIL SOZLAMALARI ---
    @app.route("/teacher_profile", methods=["GET", "POST"])
    def teacher_profile():
        if 'school_id' not in session or session.get('user_role') != 'teacher': return redirect(url_for('home'))
        tid = session['teacher_id']
        teacher = Teacher.query.get(tid)
        
        if request.method == "POST":
            action = request.form.get('action')
            
            try:
                if action == 'update_info':
                    teacher.first_name = sanitize_input(request.form.get('first_name'))
                    teacher.last_name = sanitize_input(request.form.get('last_name'))
                    teacher.phone = sanitize_input(request.form.get('phone'))
                    uploaded_image = request.files.get('profile_image')
                    if uploaded_image and uploaded_image.filename:
                        teacher.profile_pic = save_teacher_profile_image(uploaded_image, teacher.id)
                    else:
                        teacher.profile_pic = sanitize_input(request.form.get('profile_pic')) or teacher.profile_pic
                    session['teacher_name'] = f"{teacher.first_name} {teacher.last_name}"
                    flash("Ma'lumotlar muvaffaqiyatli saqlandi!", "success")
                    
                elif action == 'change_password':
                    new_pass = request.form.get('new_password')
                    if new_pass and len(new_pass) >= 6:
                        teacher.password_hash = generate_password_hash(new_pass)
                        flash("Parol muvaffaqiyatli o'zgartirildi!", "success")
                    else:
                        flash("Parol kamida 6 ta belgidan iborat bo'lishi kerak.", "danger")
                        
                elif action == 'change_login':
                    new_login = sanitize_input(request.form.get('new_login'))
                    existing = Teacher.query.filter_by(login=new_login).first()
                    if not existing or existing.id == teacher.id:
                        teacher.login = new_login
                        flash("Login o'zgartirildi! Keyingi safar yangi login bilan kiring.", "success")
                    else:
                        flash("Bu login allaqachon band.", "danger")
                        
                db.session.commit()
                
            except Exception as e:
                db.session.rollback()
                flash(f"Xatolik yuz berdi: {str(e)}", "danger")
                
            return redirect(url_for('teacher_profile'))
            
        return render_template("teacher_profile.html", teacher=teacher)

    # --- BOSHQA ROUTE LAR ---
    @app.route("/classes")
    def classes():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        classes_with_counts = [{'id': c.id, 'name': c.name, 'student_count': Student.query.filter_by(class_id=c.id, school_id=sid).count()} for c in Class.query.filter_by(school_id=sid).all()]
        return render_template("classes.html", classes=classes_with_counts)

    @app.route("/add_class", methods=["POST"])
    def add_class():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        db.session.add(Class(name=sanitize_input(request.form.get('class_name')), school_id=session['school_id'])); db.session.commit()
        return redirect(url_for('classes'))

    @app.route("/students")
    def students():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']; query = Student.query.filter_by(school_id=sid)
        cf = request.args.get('class_id')
        if cf: query = query.filter_by(class_id=cf)
        return render_template("students.html", students=query.all(), classes=Class.query.filter_by(school_id=sid).all(), current_class=cf)

    @app.route("/add_student", methods=["GET", "POST"])
    def add_student():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        if request.method == "POST":
            fn = sanitize_input(request.form.get('first_name')); ln = sanitize_input(request.form.get('last_name'))
            cid = request.form.get('class_id')
            db.session.add(Student(first_name=fn, last_name=ln, school_id=sid, class_id=cid, login=f"{fn.lower()}.{ln.lower()}", password_hash=generate_password_hash("123456")))
            try: db.session.commit()
            except: db.session.rollback()
            return redirect(url_for('students'))
        return render_template("add_student.html", classes=Class.query.filter_by(school_id=sid).all())

    @app.route("/teachers")
    def teachers():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        return render_template("teachers.html", teachers=Teacher.query.filter_by(school_id=session['school_id']).all())

    @app.route("/add_teacher", methods=["GET", "POST"])
    def add_teacher():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        if request.method == "POST":
            fn = sanitize_input(request.form.get('first_name')); ln = sanitize_input(request.form.get('last_name'))
            t_login = sanitize_input(request.form.get('login', f"{fn.lower()}.{ln.lower()}"))
            t_pass = request.form.get('password', '123456')
            if Teacher.query.filter_by(login=t_login).first():
                flash("Bu login allaqachon ishlatilgan. Boshqa login tanlang.", "danger")
                return render_template("add_teacher.html", classes=Class.query.filter_by(school_id=sid).order_by(Class.name).all())

            sn = sanitize_input(request.form.get('subject_name'))
            subj = Subject.query.filter_by(name=sn.strip(), school_id=sid).first()
            if not subj: subj = Subject(name=sn.strip(), school_id=sid); db.session.add(subj); db.session.flush()
            selected_class_ids = {int(value) for value in request.form.getlist('class_ids') if value.isdigit()}
            valid_classes = Class.query.filter(Class.school_id == sid, Class.id.in_(selected_class_ids)).all() if selected_class_ids else []
            lesson_day = request.form.get('lesson_day')
            start_time = request.form.get('start_time')
            end_time = request.form.get('end_time')
            room_number = sanitize_input(request.form.get('room_number'))
            
            teacher = Teacher(first_name=fn, last_name=ln, school_id=sid, subject_id=subj.id, login=t_login, password_hash=generate_password_hash(t_pass))
            db.session.add(teacher); db.session.flush()
            db.session.add_all([TeacherClassAssignment(teacher_id=teacher.id, class_id=school_class.id, subject_id=subj.id) for school_class in valid_classes])
            if lesson_day and start_time and end_time:
                lesson_classes = valid_classes or [None]
                db.session.add_all([Schedule(day_of_week=lesson_day, start_time=start_time, end_time=end_time, room_number=room_number, school_id=sid, class_id=school_class.id if school_class else None, subject_id=subj.id, teacher_id=teacher.id) for school_class in lesson_classes])
            try: db.session.commit()
            except Exception as error:
                db.session.rollback()
                flash(f"O'qituvchi qo'shishda xatolik: {error}", "danger")
                return render_template("add_teacher.html", classes=Class.query.filter_by(school_id=sid).order_by(Class.name).all())
            return redirect(url_for('teachers'))
        return render_template("add_teacher.html", classes=Class.query.filter_by(school_id=sid).order_by(Class.name).all())

    @app.route("/tests")
    def tests():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        return render_template("tests.html", tests=Test.query.filter_by(school_id=session['school_id']).all())

    @app.route("/create_test", methods=["GET", "POST"])
    def create_test():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        if request.method == "POST":
            t = Test(title=sanitize_input(request.form.get('title')), school_id=sid, subject_id=request.form.get('subject_id'), class_id=request.form.get('class_id'))
            db.session.add(t); db.session.commit(); return redirect(url_for('add_question', test_id=t.id))
        return render_template("create_test.html", subjects=Subject.query.filter_by(school_id=sid).all(), classes=Class.query.filter_by(school_id=sid).all())

    @app.route("/add_question/<int:test_id>", methods=["GET", "POST"])
    def add_question(test_id):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        test = Test.query.filter_by(id=test_id, school_id=session['school_id']).first_or_404()
        if request.method == "POST":
            db.session.add(TestQuestion(test_id=test_id, question_text=sanitize_input(request.form.get('question_text')), option_a=sanitize_input(request.form.get('option_a')), option_b=sanitize_input(request.form.get('option_b')), option_c=sanitize_input(request.form.get('option_c')), option_d=sanitize_input(request.form.get('option_d')), correct_answer=request.form.get('correct_answer'), topic=sanitize_input(request.form.get('topic')), subtopic=sanitize_input(request.form.get('subtopic'))))
            db.session.commit()
            flash("Savol saqlandi. Keyingi savolni kiriting.", "success")
            return redirect(url_for('add_question', test_id=test_id))
        return render_template("add_question.html", test=test)

    @app.route("/test_results/<int:test_id>")
    def test_results(test_id):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        test = Test.query.filter_by(id=test_id, school_id=session['school_id']).first_or_404()
        results = TestResult.query.filter_by(test_id=test_id).all()
        stats = {}; total = len(results)
        for r in results:
            if r.topic_analysis:
                d = json.loads(r.topic_analysis)
                for k,v in d.items():
                    if k not in stats: stats[k] = {'c':0,'t':0}
                    stats[k]['c'] += v.get('correct', v.get('c', 0))
                    stats[k]['t'] += v.get('total', v.get('t', 0))
        analyzed = [{'name':k, 'pct': round((v['c']/v['t']*100) if v['t']>0 else 0, 1), 'st': 'danger' if (v['c']/v['t']*100 if v['t']>0 else 0)<60 else ('warning' if (v['c']/v['t']*100 if v['t']>0 else 0)<80 else 'success')} for k,v in stats.items()]
        analyzed.sort(key=lambda x: x['pct'])
        return render_template("test_results.html", test=test, results=results, analyzed_topics=analyzed, total_students=total)

    @app.route("/test_results")
    def all_test_results():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        results = TestResult.query.join(Student).join(Test).filter(
            Student.school_id == session['school_id']
        ).order_by(TestResult.submitted_at.desc()).all()
        return render_template("all_test_results.html", results=results)

    @app.route("/student_dashboard")
    def student_dashboard():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        st = Student.query.get(session['student_id'])
        res = TestResult.query.filter_by(student_id=st.id).order_by(TestResult.submitted_at.desc()).limit(5).all()
        ach = StudentAchievement.query.filter_by(student_id=st.id).all()
        nws = News.query.filter_by(school_id=st.school_id).order_by(News.created_at.desc()).limit(3).all()
        labels = [r.test.title[:15] for r in reversed(res)]; data = [r.percentage for r in reversed(res)]
        while len(data) < 5: labels.insert(0, f"Test {len(data)+1}"); data.insert(0, 0)
        return render_template("student_dashboard.html", student=st, results=res, achievements=ach, news=nws, chart_labels=json.dumps(labels), chart_data=json.dumps(data))

    @app.route("/student_profile", methods=["GET", "POST"])
    def student_profile():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        student = Student.query.filter_by(id=session['student_id'], school_id=session['school_id']).first_or_404()
        if request.method == "POST":
            student.first_name = sanitize_input(request.form.get('first_name')) or student.first_name
            student.last_name = sanitize_input(request.form.get('last_name')) or student.last_name
            student.gender = sanitize_input(request.form.get('gender')) or student.gender
            birth_date = request.form.get('birth_date')
            if birth_date:
                student.birth_date = datetime.strptime(birth_date, '%Y-%m-%d').date()
            uploaded_image = request.files.get('profile_image')
            if uploaded_image and uploaded_image.filename:
                student.profile_pic = save_student_profile_image(uploaded_image, student.id)
            db.session.commit()
            session['student_name'] = f"{student.first_name} {student.last_name}"
            flash("Profil muvaffaqiyatli saqlandi.", "success")
            return redirect(url_for('student_profile'))
        return render_template("student_profile.html", student=student)

    @app.route("/my_tests")
    def my_tests():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        st = db.session.query(Student).options(joinedload(Student.student_class)).get(session['student_id'])
        if not st: return redirect(url_for('logout'))
        tests = db.session.query(Test).options(joinedload(Test.subject), joinedload(Test.questions)).filter_by(class_id=st.class_id, school_id=st.school_id).all()
        done = [r.test_id for r in TestResult.query.filter_by(student_id=st.id).all()]
        return render_template("my_tests.html", student=st, tests=tests, done_ids=done)

    @app.route("/take_test/<int:test_id>")
    def take_test(test_id):
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        st = Student.query.get(session['student_id'])
        test = Test.query.filter_by(id=test_id, school_id=st.school_id, class_id=st.class_id).first_or_404()
        return render_template("take_test.html", test=test, student=st)

    @app.route("/submit_test/<int:test_id>", methods=["POST"])
    def submit_test(test_id):
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        st = Student.query.get(session['student_id']); test = Test.query.filter_by(id=test_id, school_id=st.school_id).first_or_404()
        qs = TestQuestion.query.filter_by(test_id=test_id).all(); score=0; tot=len(qs); ts={}
        for q in qs:
            ua = request.form.get(f'q_{q.id}')
            ic = bool(ua) and str(ua).strip().lower() == str(q.correct_answer or '').strip().lower()
            if ic: score+=1
            tn = q.topic or "Noma'lum"
            if tn not in ts: ts[tn]={'c':0,'t':0}
            ts[tn]['t']+=1
            if ic: ts[tn]['c']+=1
        pct = (score/tot*100) if tot>0 else 0
        if TestResult.query.filter_by(student_id=st.id, test_id=test_id).first(): return "Allaqachon ishlangan.", 400
        result = TestResult(student_id=st.id, test_id=test_id, score=score, total_questions=tot, percentage=pct, topic_analysis=json.dumps(ts))
        db.session.add(result)
        xp = score*10 + (50 if pct==100 else 0); st.xp += xp
        nl = (st.xp // 500) + 1
        if nl > st.level: st.level = nl; flash(f"Level {nl} ga ko'tarildingiz!", "success")
        db.session.commit(); session['student_name'] = f"{st.first_name} {st.last_name} (Lvl {st.level})"
        questions_data = [{'id': q.id, 'text': q.question_text, 'correct': q.correct_answer, 'topic': q.topic} for q in qs]
        return render_template("test_result.html", result=result, test=test, topic_stats=ts, earned_xp=xp, questions_data=json.dumps(questions_data))

    @app.route("/schedule/manage")
    def manage_schedule():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']; cls = Class.query.filter_by(school_id=sid).all()
        scid = request.args.get('class_id', type=int)
        query = Schedule.query.filter_by(school_id=sid)
        if scid:
            query = query.filter_by(class_id=scid)
        items = query.order_by(db.case({"Dushanba":1,"Seshanba":2,"Chorshanba":3,"Payshanba":4,"Juma":5,"Shanba":6}, value=Schedule.day_of_week), Schedule.start_time).all()
        return render_template("manage_schedule.html", classes=cls, selected_class_id=scid, schedule_items=items, subjects=Subject.query.filter_by(school_id=sid).all(), teachers=Teacher.query.filter_by(school_id=sid).all())

    @app.route("/schedule/add", methods=["POST"])
    def add_schedule():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        tid = request.form.get('teacher_id', type=int)
        class_id = request.form.get('class_id', type=int) or None
        subject_id = request.form.get('subject_id', type=int)
        if not tid or not subject_id:
            flash("O'qituvchi va fan tanlanishi shart.", "danger")
            return redirect(url_for('manage_schedule', class_id=class_id))
        db.session.add(Schedule(day_of_week=request.form.get('day_of_week'), start_time=request.form.get('start_time'), end_time=request.form.get('end_time'), room_number=sanitize_input(request.form.get('room_number')), school_id=session['school_id'], class_id=class_id, subject_id=subject_id, teacher_id=tid))
        db.session.commit(); return redirect(url_for('manage_schedule', class_id=class_id))

    @app.route("/schedule/edit/<int:schedule_id>", methods=["GET", "POST"])
    def edit_schedule(schedule_id):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        lesson = Schedule.query.filter_by(id=schedule_id, school_id=sid).first_or_404()
        classes = Class.query.filter_by(school_id=sid).order_by(Class.name).all()
        subjects = Subject.query.filter_by(school_id=sid).order_by(Subject.name).all()
        teachers = Teacher.query.filter_by(school_id=sid).order_by(Teacher.last_name).all()
        if request.method == "POST":
            teacher_id = request.form.get('teacher_id', type=int)
            subject_id = request.form.get('subject_id', type=int)
            class_id = request.form.get('class_id', type=int) or None
            if not teacher_id or not subject_id:
                flash("O'qituvchi va fan tanlanishi shart.", "danger")
                return render_template("edit_schedule.html", lesson=lesson, classes=classes, subjects=subjects, teachers=teachers)
            lesson.day_of_week = request.form.get('day_of_week')
            lesson.start_time = request.form.get('start_time')
            lesson.end_time = request.form.get('end_time')
            lesson.room_number = sanitize_input(request.form.get('room_number'))
            lesson.class_id = class_id
            lesson.subject_id = subject_id
            lesson.teacher_id = teacher_id
            db.session.commit()
            return redirect(url_for('manage_schedule', class_id=class_id))
        return render_template("edit_schedule.html", lesson=lesson, classes=classes, subjects=subjects, teachers=teachers)

    @app.route("/schedule/delete/<int:schedule_id>", methods=["POST"])
    def delete_schedule(schedule_id):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        lesson = Schedule.query.filter_by(id=schedule_id, school_id=session['school_id']).first_or_404()
        class_id = lesson.class_id
        db.session.delete(lesson)
        db.session.commit()
        flash("Dars o'chirildi.", "success")
        return redirect(url_for('manage_schedule', class_id=class_id))

    @app.route("/schedule/view")
    def view_schedule():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        st = Student.query.filter_by(id=session['student_id'], school_id=session['school_id']).first_or_404()
        items = Schedule.query.filter(
            Schedule.school_id == st.school_id,
            Schedule.class_id == st.class_id
        ).order_by(
            db.case({"Dushanba":1,"Seshanba":2,"Chorshanba":3,"Payshanba":4,"Juma":5,"Shanba":6}, value=Schedule.day_of_week),
            Schedule.start_time
        ).all()
        gs = {d:[] for d in ["Dushanba","Seshanba","Chorshanba","Payshanba","Juma","Shanba"]}
        for i in items: 
            if i.day_of_week in gs: gs[i.day_of_week].append(i)
        return render_template("view_schedule.html", schedule=gs, student=st)

    @app.route("/library/manage")
    def manage_library():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        return render_template("manage_library.html", books=Book.query.filter_by(school_id=session['school_id']).all())

    @app.route("/library/add", methods=["POST"])
    def add_book():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        db.session.add(Book(title=sanitize_input(request.form.get('title')), author=sanitize_input(request.form.get('author')), genre=request.form.get('genre'), description=sanitize_input(request.form.get('description')), cover_url=sanitize_input(request.form.get('cover_url')), file_url=sanitize_input(request.form.get('file_url')), school_id=session['school_id']))
        db.session.commit(); return redirect(url_for('manage_library'))

    @app.route("/library")
    def student_library():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        sid = session['school_id']; gf = request.args.get('genre')
        q = Book.query.filter_by(school_id=sid)
        if gf: q = q.filter_by(genre=gf)
        genres = [g[0] for g in db.session.query(Book.genre).filter_by(school_id=sid).distinct().all() if g[0]]
        return render_template("student_library.html", books=q.all(), genres=genres, current_genre=gf)

    @app.route("/news/manage")
    def manage_news():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        return render_template("manage_news.html", news=News.query.filter_by(school_id=session['school_id']).order_by(News.created_at.desc()).all())

    @app.route("/news/add", methods=["POST"])
    def add_news():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        db.session.add(News(title=sanitize_input(request.form.get('title')), content=sanitize_input(request.form.get('content')), is_announcement=(request.form.get('is_announcement')=='on'), school_id=session['school_id']))
        db.session.commit(); return redirect(url_for('manage_news'))

    @app.route("/news")
    def student_news():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        return render_template("student_news.html", news=News.query.filter_by(school_id=session['school_id']).order_by(News.created_at.desc()).all())

    @app.route("/search")
    def search():
        if 'school_id' not in session: return redirect(url_for('home'))
        q = sanitize_input(request.args.get('q','').strip())
        if not q: return redirect(url_for('home'))
        sid = session['school_id']; p = f"%{q}%"
        res = {
            'students': Student.query.filter(Student.school_id==sid, db.or_(Student.first_name.ilike(p), Student.last_name.ilike(p))).all(),
            'teachers': Teacher.query.filter(Teacher.school_id==sid, db.or_(Teacher.first_name.ilike(p), Teacher.last_name.ilike(p))).all(),
            'classes': Class.query.filter(Class.school_id==sid, Class.name.ilike(p)).all(),
            'tests': Test.query.filter(Test.school_id==sid, Test.title.ilike(p)).all(),
            'books': Book.query.filter(Book.school_id==sid, db.or_(Book.title.ilike(p), Book.author.ilike(p))).all(),
            'news': News.query.filter(News.school_id==sid, db.or_(News.title.ilike(p), News.content.ilike(p))).all()
        }
        return render_template("search_results.html", results=res, query=q, total=sum(len(v) for v in res.values()))

    # --- AI CHAT ROUTES ---
    @app.route("/ai_chat")
    def ai_chat_page():
        if 'school_id' not in session: return redirect(url_for('home'))
        if 'chat_history' not in session: session['chat_history'] = []
        return render_template("ai_chat.html")
    @app.route("/delete_student/<int:sid>")
    def delete_student(sid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        s = Student.query.filter_by(id=sid, school_id=session['school_id']).first_or_404()
        db.session.delete(s); db.session.commit(); return redirect(url_for('students'))

    @app.route("/delete_teacher/<int:tid>")
    def delete_teacher(tid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        t = Teacher.query.filter_by(id=tid, school_id=session['school_id']).first_or_404()
        db.session.delete(t); db.session.commit(); return redirect(url_for('teachers'))

    @app.route("/delete_test/<int:test_id>")
    def delete_test(test_id):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        t = Test.query.filter_by(id=test_id, school_id=session['school_id']).first_or_404()
        TestResult.query.filter_by(test_id=t.id).delete(synchronize_session=False)
        TestQuestion.query.filter_by(test_id=t.id).delete(synchronize_session=False)
        db.session.delete(t); db.session.commit(); return redirect(url_for('tests'))

    @app.route("/delete_book/<int:bid>")
    def delete_book(bid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        b = Book.query.filter_by(id=bid, school_id=session['school_id']).first_or_404()
        db.session.delete(b); db.session.commit(); return redirect(url_for('manage_library'))

    @app.route("/delete_news/<int:nid>")
    def delete_news(nid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        n = News.query.filter_by(id=nid, school_id=session['school_id']).first_or_404()
        db.session.delete(n); db.session.commit(); return redirect(url_for('manage_news'))

    # --- TAHRIRLASH ROUTE LARI ---
    @app.route("/edit_class/<int:cid>", methods=["GET", "POST"])
    def edit_class(cid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        c = Class.query.filter_by(id=cid, school_id=session['school_id']).first_or_404()
        if request.method == "POST":
            c.name = sanitize_input(request.form.get('class_name'))
            db.session.commit(); return redirect(url_for('classes'))
        return render_template("edit_class.html", c=c)

    @app.route("/edit_student/<int:sid>", methods=["GET", "POST"])
    def edit_student(sid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        s = Student.query.filter_by(id=sid, school_id=session['school_id']).first_or_404()
        classes = Class.query.filter_by(school_id=session['school_id']).all()
        if request.method == "POST":
            old_first = s.first_name
            old_last = s.last_name
            
            s.first_name = sanitize_input(request.form.get('first_name'))
            s.last_name = sanitize_input(request.form.get('last_name'))
            s.class_id = request.form.get('class_id')
            
            # Agar ism yoki familiya o'zgargan bo'lsa, loginni ham yangilaymiz
            if old_first != s.first_name or old_last != s.last_name:
                new_login = f"{s.first_name.lower()}.{s.last_name.lower()}"
                # Login band emasligini tekshirish (o'zi bundan tashqari)
                existing = Student.query.filter_by(login=new_login).first()
                if not existing or existing.id == s.id:
                    s.login = new_login
                else:
                    flash(f"Yangi login ({new_login}) band. Login o'zgartirilmadi.", "warning")
                    
            db.session.commit(); return redirect(url_for('students'))
        return render_template("edit_student.html", s=s, classes=classes)

    @app.route("/edit_teacher/<int:tid>", methods=["GET", "POST"])
    @app.route("/admin/edit_teacher/<int:tid>", methods=["GET", "POST"])
    def edit_teacher(tid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']
        t = Teacher.query.filter_by(id=tid, school_id=sid).first_or_404()
        classes = Class.query.filter_by(school_id=sid).order_by(Class.name).all()
        if request.method == "POST":
            t.first_name = sanitize_input(request.form.get('first_name'))
            t.last_name = sanitize_input(request.form.get('last_name'))
            new_login = sanitize_input(request.form.get('login'))
            existing_login = Teacher.query.filter_by(login=new_login).first()
            if existing_login and existing_login.id != t.id:
                flash("Bu login allaqachon ishlatilgan. Boshqa login tanlang.", "danger")
                return render_template("edit_teacher.html", t=t, classes=classes)
            subject_name = sanitize_input(request.form.get('subject_name'))
            subject = Subject.query.filter_by(name=subject_name.strip(), school_id=sid).first()
            if not subject:
                subject = Subject(name=subject_name.strip(), school_id=sid)
                db.session.add(subject)
                db.session.flush()
            t.subject_id = subject.id
            t.login = new_login
            t.phone = sanitize_input(request.form.get('phone'))
            selected_class_ids = {int(value) for value in request.form.getlist('class_ids') if value.isdigit()}
            valid_class_ids = {school_class.id for school_class in classes if school_class.id in selected_class_ids}
            TeacherClassAssignment.query.filter_by(teacher_id=t.id).delete()
            db.session.add_all([TeacherClassAssignment(teacher_id=t.id, class_id=class_id, subject_id=subject.id) for class_id in valid_class_ids])
            uploaded_image = request.files.get('profile_image')
            if uploaded_image and uploaded_image.filename:
                t.profile_pic = save_teacher_profile_image(uploaded_image, t.id)
            else:
                t.profile_pic = sanitize_input(request.form.get('profile_pic')) or t.profile_pic
            new_pass = request.form.get('password')
            if new_pass: t.password_hash = generate_password_hash(new_pass)
            db.session.commit(); return redirect(url_for('teachers'))
        assigned_class_ids = [assignment.class_id for assignment in TeacherClassAssignment.query.filter_by(teacher_id=t.id).all()]
        return render_template("edit_teacher.html", t=t, classes=classes, assigned_class_ids=assigned_class_ids)

    @app.route("/edit_book/<int:bid>", methods=["GET", "POST"])
    def edit_book(bid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        b = Book.query.filter_by(id=bid, school_id=session['school_id']).first_or_404()
        if request.method == "POST":
            b.title = sanitize_input(request.form.get('title'))
            b.author = sanitize_input(request.form.get('author'))
            b.genre = request.form.get('genre')
            b.file_url = sanitize_input(request.form.get('file_url'))
            db.session.commit(); return redirect(url_for('manage_library'))
        return render_template("edit_book.html", b=b)

    @app.route("/edit_news/<int:nid>", methods=["GET", "POST"])
    def edit_news(nid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        n = News.query.filter_by(id=nid, school_id=session['school_id']).first_or_404()
        if request.method == "POST":
            n.title = sanitize_input(request.form.get('title'))
            n.content = sanitize_input(request.form.get('content'))
            n.is_announcement = (request.form.get('is_announcement') == 'on')
            db.session.commit(); return redirect(url_for('manage_news'))
        return render_template("edit_news.html", n=n)

    @app.route("/admin_profile", methods=["GET", "POST"])
    def admin_profile():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        school = School.query.get_or_404(session['school_id'])
        if request.method == "POST":
            school.name = sanitize_input(request.form.get('name')) or school.name
            school.address = sanitize_input(request.form.get('address'))
            school.phone = sanitize_input(request.form.get('phone'))
            school.email = sanitize_input(request.form.get('email'))
            school.logo = sanitize_input(request.form.get('logo'))
            db.session.commit()
            session['school_name'] = school.name
            flash("Admin profili muvaffaqiyatli saqlandi.", "success")
            return redirect(url_for('admin_profile'))
        return render_template("admin_profile.html", school=school)
    
    @app.route("/ask_ai_chat_stream", methods=["POST"])
    @csrf.exempt
    def ask_ai_chat_stream():
        if 'school_id' not in session: 
            return jsonify({"error": "Unauthorized"}), 401
            
        data = request.get_json()
        user_message = data.get('message', '')
        
        if not user_message:
            return jsonify({"reply": ""})

        try:
            api_key = os.environ.get('GROQ_API_KEY')
            if not api_key:
                return jsonify({"reply": "⚠️ Groq API kaliti topilmadi."})
                
            client = OpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=api_key
            )
            
            response = client.chat.completions.create(
                model="openai/gpt-oss-120b",
                messages=[
                    {"role": "system", "content": "Siz maktab o'quvchilari uchun mehribon AI yordamchisiz. Qisqa va aniq javob bering."},
                    {"role": "user", "content": user_message}
                ]
            )
            
            reply = response.choices[0].message.content
            return jsonify({"reply": reply})
            
        except Exception as e:
            print(f"Groq Xatosi: {e}")
            return jsonify({"reply": f"Xatolik: {str(e)}"}), 500

    @app.route("/clear_chat", methods=["POST"])
    @csrf.exempt
    def clear_chat():
        if 'school_id' in session:
            session['chat_history'] = []
            session.modified = True
        return jsonify({"status": "cleared"})


    @app.route("/logout")
    def logout():
        session.clear(); return redirect(url_for('home'))
        
    return app

if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
