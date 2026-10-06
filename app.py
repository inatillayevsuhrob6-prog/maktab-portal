from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from config import Config
from extensions import db
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from backend.models import School, Class, Student, Teacher, TeacherClassAssignment, Subject, Test, TestQuestion, TestResult, Achievement, StudentAchievement, Schedule, Book, News, Club, StudentClub, ChatMessage, Presentation, Attendance, Grade, Spotlight, GameResult, GameChallenge, EducationalGame, EducationalGameQuestion
from sqlalchemy.orm import joinedload
from sqlalchemy import text, func, and_, or_
from flask_wtf.csrf import CSRFProtect, CSRFError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import json
import bleach
import os
import uuid
import random
from openai import OpenAI
from datetime import datetime, timedelta, timezone

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024
    os.makedirs(app.instance_path, exist_ok=True)
    
    csrf = CSRFProtect(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        flash("Sahifa eskirgan. Jadval yangilandi, amalni qayta bajaring.", "danger")
        return redirect(request.referrer or url_for('home'))

    @app.errorhandler(400)
    def handle_bad_request(error):
        if request.path == '/presentations/upload':
            app.logger.warning("Noto‘g‘ri taqdimot yuklash so‘rovi: %s", error)
            flash("Fayl yuklash so‘rovi noto‘g‘ri. Sahifani yangilab, PDF/PPT/PPTX faylni qayta tanlang.", "danger")
            return redirect(url_for('presentations'))
        return error

    @app.errorhandler(413)
    def handle_upload_too_large(error):
        if request.path == '/presentations/upload':
            flash("Taqdimot fayli 25 MB dan kichik bo‘lishi kerak.", "danger")
            return redirect(url_for('presentations'))
        return error
    
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
            if db.engine.dialect.name == 'sqlite':
                club_columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(club)"))]
                if 'leader_name' not in club_columns:
                    db.session.execute(text("ALTER TABLE club ADD COLUMN leader_name VARCHAR(100)"))
            else:
                db.session.execute(text("ALTER TABLE club ADD COLUMN IF NOT EXISTS leader_name VARCHAR(100)"))
                db.session.execute(text("ALTER TABLE club ALTER COLUMN teacher_id DROP NOT NULL"))
            db.session.commit()
            print("✅ 'club' va 'student_club' jadvallari yaratildi!")
        except Exception as e:
            print(f"❌ Club jadvalini yaratishda xatolik: {e}")
            db.session.rollback()

        try:
            if db.engine.dialect.name == 'sqlite':
                membership_columns = [row[1] for row in db.session.execute(text("PRAGMA table_info(student_club)"))]
                if 'phone' not in membership_columns:
                    db.session.execute(text("ALTER TABLE student_club ADD COLUMN phone VARCHAR(20)"))
            else:
                db.session.execute(text("ALTER TABLE student_club ADD COLUMN IF NOT EXISTS phone VARCHAR(20)"))
            db.session.commit()
        except Exception as e:
            print(f"To‘garak a’zosi telefon ustunini yangilashda xatolik: {e}")
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

    def week_window():
        local_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5)))
        week_start = local_now.date() - timedelta(days=local_now.weekday())
        start_local = datetime.combine(week_start, datetime.min.time(), tzinfo=timezone(timedelta(hours=5)))
        end_local = start_local + timedelta(days=7)
        return week_start, start_local.astimezone(timezone.utc).replace(tzinfo=None), end_local.astimezone(timezone.utc).replace(tzinfo=None)

    def weekly_student_scores(school_id):
        _, start_at, end_at = week_window()
        students = Student.query.filter_by(school_id=school_id).options(joinedload(Student.student_class)).all()
        scores = {student.id: {'student': student, 'tests': 0, 'attendance': 0, 'games': 0, 'points': 0} for student in students}
        for result in TestResult.query.join(Student).filter(Student.school_id == school_id, TestResult.submitted_at >= start_at, TestResult.submitted_at < end_at).all():
            item = scores.get(result.student_id)
            if item:
                item['tests'] += max(0, int(result.score or 0)) * 10 + (50 if result.percentage == 100 else 0)
        for record in Attendance.query.filter_by(school_id=school_id, status='present').filter(Attendance.attendance_date >= week_window()[0], Attendance.attendance_date < week_window()[0] + timedelta(days=7)).all():
            if record.student_id in scores: scores[record.student_id]['attendance'] += 10
        for result in GameResult.query.filter_by(school_id=school_id).filter(GameResult.played_at >= start_at, GameResult.played_at < end_at).all():
            if result.student_id in scores: scores[result.student_id]['games'] += result.points or 0
        for item in scores.values(): item['points'] = item['tests'] + item['attendance'] + item['games']
        return sorted(scores.values(), key=lambda item: (-item['points'], item['student'].last_name, item['student'].first_name))

    def class_weekly_scores(school_id):
        ranked = weekly_student_scores(school_id)
        groups = {}
        for item in ranked:
            cls = item['student'].student_class
            group = groups.setdefault(cls.id, {'class': cls, 'total': 0, 'count': 0})
            group['total'] += item['points']; group['count'] += 1
        result = [{'class': value['class'], 'points': round(value['total'] / value['count']) if value['count'] else 0, 'students': value['count']} for value in groups.values()]
        return sorted(result, key=lambda value: (-value['points'], value['class'].name))

    def current_spotlights(school_id):
        week_start = week_window()[0]
        rows = Spotlight.query.filter_by(school_id=school_id, week_start=week_start).all()
        people = []
        for row in rows:
            person = Student.query.filter_by(id=row.person_id, school_id=school_id).first() if row.person_type == 'student' else Teacher.query.filter_by(id=row.person_id, school_id=school_id).first()
            if person: people.append({'row': row, 'person': person, 'name': f'{person.first_name} {person.last_name}'})
        return people

    def teacher_class_ids(teacher_id):
        assigned = {row.class_id for row in TeacherClassAssignment.query.filter_by(teacher_id=teacher_id).all()}
        assigned.update(row.class_id for row in Schedule.query.filter_by(teacher_id=teacher_id).filter(Schedule.class_id.isnot(None)).all())
        return assigned

    def save_news_image(uploaded_file):
        """Save one validated news image under a collision-resistant name."""
        filename = secure_filename(uploaded_file.filename or '')
        extension = os.path.splitext(filename)[1].lower()
        if extension not in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
            raise ValueError("Rasm formati noto‘g‘ri. JPG, PNG, GIF yoki WEBP tanlang.")
        uploaded_file.stream.seek(0, os.SEEK_END)
        size = uploaded_file.stream.tell()
        uploaded_file.stream.seek(0)
        if size > 5 * 1024 * 1024:
            raise ValueError("Yangilik rasmi 5 MB dan kichik bo‘lishi kerak.")
        upload_dir = os.path.join(app.static_folder, 'uploads', 'news')
        os.makedirs(upload_dir, exist_ok=True)
        saved_name = f"{uuid.uuid4().hex}{extension}"
        disk_path = os.path.join(upload_dir, saved_name)
        uploaded_file.save(disk_path)
        return url_for('static', filename=f'uploads/news/{saved_name}'), disk_path

    def local_news_image_path(image_url):
        """Resolve only files inside our news upload directory."""
        prefix = '/static/uploads/news/'
        if not image_url or not image_url.startswith(prefix):
            return None
        upload_dir = os.path.realpath(os.path.join(app.static_folder, 'uploads', 'news'))
        filename = os.path.basename(image_url.split('?', 1)[0])
        path = os.path.realpath(os.path.join(upload_dir, filename))
        if filename and os.path.commonpath([upload_dir, path]) == upload_dir:
            return path
        return None

    def remove_news_image(image_url):
        path = local_news_image_path(image_url)
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                app.logger.warning('Yangilik rasmi o‘chirilmadi: %s', path)

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
        presentation_paths = []
        clubs = Club.query.filter_by(teacher_id=teacher_id, school_id=school_id).all()
        for club in clubs:
            StudentClub.query.filter_by(club_id=club.id).delete(synchronize_session=False)
            db.session.delete(club)
        TeacherClassAssignment.query.filter_by(teacher_id=teacher_id).delete(synchronize_session=False)
        Test.query.filter_by(created_by_teacher_id=teacher_id, school_id=school_id).update(
            {Test.created_by_teacher_id: None}, synchronize_session=False
        )
        presentations = Presentation.query.filter_by(teacher_id=teacher_id, school_id=school_id).all()
        upload_dir = os.path.realpath(os.path.join(app.static_folder, 'uploads', 'presentations'))
        for presentation in presentations:
            if presentation.file_url.startswith('/static/uploads/presentations/'):
                filename = os.path.basename(presentation.file_url.split('?', 1)[0])
                path = os.path.realpath(os.path.join(upload_dir, filename))
                if filename and os.path.commonpath([upload_dir, path]) == upload_dir:
                    presentation_paths.append(path)
            db.session.delete(presentation)
        Schedule.query.filter_by(teacher_id=teacher_id, school_id=school_id).update(
            {Schedule.teacher_id: None}, synchronize_session=False
        )
        ChatMessage.query.filter(
            or_(
                and_(ChatMessage.sender_type == 'teacher', ChatMessage.sender_id == teacher_id),
                and_(ChatMessage.recipient_type == 'teacher', ChatMessage.recipient_id == teacher_id)
            )
        ).delete(synchronize_session=False)
        return presentation_paths

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
            
        flash("Login yoki parol noto‘g‘ri. Ma’lumotlarni tekshirib, qayta urinib ko‘ring.", "danger")
        return redirect(url_for('home'))

    @app.route('/attendance', methods=['GET', 'POST'])
    def attendance():
        if session.get('user_role') != 'teacher' or not session.get('school_id'):
            return redirect(url_for('home'))
        tid, sid = session['teacher_id'], session['school_id']
        allowed_ids = teacher_class_ids(tid)
        classes = Class.query.filter(Class.school_id == sid, Class.id.in_(allowed_ids)).order_by(Class.name).all() if allowed_ids else []
        selected_id = request.values.get('class_id', type=int) or (classes[0].id if classes else None)
        selected = next((item for item in classes if item.id == selected_id), None)
        try: selected_date = datetime.strptime(request.values.get('date', ''), '%Y-%m-%d').date()
        except ValueError: selected_date = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5))).date()
        if request.method == 'POST':
            if not selected:
                flash('Sinfni tanlang.', 'danger'); return redirect(url_for('attendance'))
            today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5))).date()
            if selected_date > today:
                flash('Kelajak sanasi uchun davomat belgilab bo‘lmaydi.', 'danger')
                return redirect(url_for('attendance', class_id=selected.id, date=today.isoformat()))
            students = Student.query.filter_by(school_id=sid, class_id=selected.id).all()
            valid_statuses = {'present', 'excused', 'unexcused'}
            for student in students:
                status = request.form.get(f'status_{student.id}')
                record = Attendance.query.filter_by(student_id=student.id, attendance_date=selected_date).first()
                if status == '':
                    if record: db.session.delete(record)
                    continue
                if status not in valid_statuses: continue
                if not record:
                    record = Attendance(student_id=student.id, class_id=selected.id, teacher_id=tid, school_id=sid, attendance_date=selected_date, status=status)
                    db.session.add(record)
                record.class_id, record.teacher_id, record.school_id, record.status = selected.id, tid, sid, status
                record.note = sanitize_input(request.form.get(f'note_{student.id}', ''))[:250] or None
            db.session.commit(); flash('Davomat saqlandi.', 'success')
            return redirect(url_for('attendance', class_id=selected.id, date=selected_date.isoformat()))
        students = Student.query.filter_by(school_id=sid, class_id=selected.id).order_by(Student.last_name, Student.first_name).all() if selected else []
        records = {row.student_id: row for row in Attendance.query.filter_by(class_id=selected.id, attendance_date=selected_date).all()} if selected else {}
        return render_template('attendance.html', classes=classes, selected=selected, selected_date=selected_date, students=students, records=records)

    @app.route('/attendance/overview')
    def attendance_overview():
        if session.get('user_role') != 'admin' or not session.get('school_id'): return redirect(url_for('home'))
        sid = session['school_id']
        try: selected_date = datetime.strptime(request.args.get('date', ''), '%Y-%m-%d').date()
        except ValueError: selected_date = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5))).date()
        rows = []
        for cls in Class.query.filter_by(school_id=sid).order_by(Class.name).all():
            students = Student.query.filter_by(school_id=sid, class_id=cls.id).order_by(Student.last_name, Student.first_name).all()
            records = {row.student_id: row for row in Attendance.query.filter_by(school_id=sid, class_id=cls.id, attendance_date=selected_date).all()}
            marked_teachers = sorted({f'{row.teacher.first_name} {row.teacher.last_name}' for row in records.values() if row.teacher}, key=str.casefold)
            present = sum(1 for student in students if records.get(student.id) and records[student.id].status == 'present')
            absent = [{'student': student, 'record': records.get(student.id)} for student in students if records.get(student.id) and records[student.id].status in {'excused', 'unexcused'}]
            unmarked_students = [student for student in students if student.id not in records]
            unmarked = len(unmarked_students)
            rows.append({'class': cls, 'total': len(students), 'present': present, 'percent': round(present * 100 / len(students)) if students else 0, 'absent': absent, 'unmarked': unmarked, 'unmarked_students': unmarked_students, 'teachers': marked_teachers})
        return render_template('attendance_overview.html', rows=rows, selected_date=selected_date)

    @app.route('/grades', methods=['GET', 'POST'])
    def grades():
        if session.get('user_role') != 'teacher' or not session.get('school_id'): return redirect(url_for('home'))
        tid, sid = session['teacher_id'], session['school_id']
        assignments = TeacherClassAssignment.query.filter_by(teacher_id=tid).options(joinedload(TeacherClassAssignment.subject)).all()
        class_ids = teacher_class_ids(tid)
        classes = Class.query.filter(Class.school_id == sid, Class.id.in_(class_ids)).order_by(Class.name).all() if class_ids else []
        selected_id = request.values.get('class_id', type=int) or (classes[0].id if classes else None)
        selected = next((item for item in classes if item.id == selected_id), None)
        assignment = next((row for row in assignments if row.class_id == selected_id), None)
        subject_id = assignment.subject_id if assignment else None
        if request.method == 'POST':
            if not selected: flash('Sinfni tanlang.', 'danger'); return redirect(url_for('grades'))
            students = Student.query.filter_by(school_id=sid, class_id=selected.id).all()
            for student in students:
                raw = request.form.get(f'grade_{student.id}', '').strip()
                if not raw: continue
                try: value = int(raw)
                except ValueError: continue
                if value not in range(1, 6): continue
                db.session.add(Grade(student_id=student.id, class_id=selected.id, teacher_id=tid, subject_id=subject_id, school_id=sid, value=value, note=sanitize_input(request.form.get(f'note_{student.id}', ''))[:250] or None))
            db.session.commit(); flash('Baholar saqlandi.', 'success')
            return redirect(url_for('grades', class_id=selected.id))
        students = Student.query.filter_by(school_id=sid, class_id=selected.id).order_by(Student.last_name, Student.first_name).all() if selected else []
        recent = Grade.query.filter_by(school_id=sid, teacher_id=tid).order_by(Grade.created_at.desc()).limit(30).all()
        return render_template('grades.html', classes=classes, selected=selected, students=students, recent=recent, subject=assignment.subject if assignment else None)

    @app.route('/grades/overview')
    def grades_overview():
        if session.get('user_role') != 'admin' or not session.get('school_id'): return redirect(url_for('home'))
        rows = Grade.query.filter_by(school_id=session['school_id']).order_by(Grade.created_at.desc()).limit(100).all()
        return render_template('grades_overview.html', grades=rows)

    @app.route('/spotlight', methods=['GET', 'POST'])
    def spotlight_manage():
        if session.get('user_role') != 'admin' or not session.get('school_id'): return redirect(url_for('home'))
        sid = session['school_id']; week_start = week_window()[0]
        if request.method == 'POST':
            person_type = request.form.get('person_type')
            person_id = request.form.get('person_id', type=int)
            model = Student if person_type == 'student' else Teacher if person_type == 'teacher' else None
            person = model.query.filter_by(id=person_id, school_id=sid).first() if model and person_id else None
            reason = sanitize_input(request.form.get('reason', '')).strip()[:300]
            if not person or not reason:
                flash('Ishtirokchi va yutuq sababini kiriting.', 'danger')
            else:
                row = Spotlight.query.filter_by(school_id=sid, person_type=person_type, week_start=week_start).first()
                if not row:
                    row = Spotlight(school_id=sid, person_type=person_type, week_start=week_start)
                    db.session.add(row)
                row.person_id, row.reason, row.selected_at = person.id, reason, datetime.utcnow()
                db.session.commit(); flash('Hafta yulduzi yangilandi.', 'success')
            return redirect(url_for('spotlight_manage'))
        return render_template('spotlight.html', spotlights=current_spotlights(sid), students=Student.query.filter_by(school_id=sid).order_by(Student.first_name).all(), teachers=Teacher.query.filter_by(school_id=sid).order_by(Teacher.first_name).all())

    @app.route('/leaderboard')
    def leaderboard():
        if session.get('user_role') not in {'admin', 'teacher', 'student'} or not session.get('school_id'): return redirect(url_for('home'))
        sid = session['school_id']; student_scores = weekly_student_scores(sid)
        current_id = session.get('student_id') if session.get('user_role') == 'student' else None
        own_rank = next((index for index, item in enumerate(student_scores, 1) if item['student'].id == current_id), None)
        return render_template(
            'leaderboard.html',
            students=student_scores[:50],
            classes=class_weekly_scores(sid),
            spotlights=current_spotlights(sid),
            own_rank=own_rank,
            current_student_id=current_id,
            week_start=week_window()[0],
        )

    GAME_BANK = {
        'box': {'title':'Sirli quti', 'icon':'🎁', 'prompt':'8 × 7 nechaga teng?', 'answer':'56', 'choices':['48','54','56','64']},
        'tug': {'title':'Arqon tortish', 'icon':'🪢', 'prompt':'Suv odatdagi bosimda necha °C da muzlaydi?', 'answer':'0°C', 'choices':['0°C','10°C','32°C','100°C']},
        'wheel': {'title':'Omad charxi', 'icon':'🎡', 'prompt':'Quyosh tizimidagi Qizil sayyora qaysi?', 'answer':'Mars', 'choices':['Venera','Mars','Yupiter','Merkuriy']},
        'race': {'title':'Poyga', 'icon':'🏁', 'prompt':'144 ÷ 12 nechaga teng?', 'answer':'12', 'choices':['10','11','12','14']},
        'anagram': {'title':'Anagram', 'icon':'🔤', 'prompt':'“TIKOB” harflaridan qanday so‘z tuziladi?', 'answer':'KITOB', 'choices':[]},
    }

    @app.route('/games')
    def games():
        role, sid = session.get('user_role'), session.get('school_id')
        if role not in {'admin', 'teacher', 'student'} or not sid: return redirect(url_for('home'))
        classes = []
        games_for_page = dict(GAME_BANK)
        if role == 'admin':
            classes = Class.query.filter_by(school_id=sid).order_by(Class.name).all()
            custom_games = EducationalGame.query.filter_by(school_id=sid).order_by(EducationalGame.created_at.desc()).all()
        elif role == 'teacher':
            allowed_ids = teacher_class_ids(session['teacher_id'])
            classes = Class.query.filter(Class.school_id == sid, Class.id.in_(allowed_ids)).order_by(Class.name).all() if allowed_ids else []
            custom_games = EducationalGame.query.filter_by(school_id=sid, created_by_role='teacher', created_by_id=session['teacher_id']).order_by(EducationalGame.created_at.desc()).all()
        else:
            student = Student.query.filter_by(id=session['student_id'], school_id=sid).first_or_404()
            custom_games = EducationalGame.query.filter(EducationalGame.school_id == sid, EducationalGame.is_active.is_(True), or_(EducationalGame.class_id.is_(None), EducationalGame.class_id == student.class_id)).order_by(EducationalGame.created_at.desc()).all()
        for game in custom_games:
            games_for_page[f'custom-{game.id}'] = {'title': game.title, 'icon': GAME_BANK.get(game.game_type, GAME_BANK['box'])['icon'], 'description': game.description or 'Ustoz tayyorlagan savol-javob o‘yini.', 'question_count': len(game.questions), 'class_name': game.student_class.name if game.student_class else 'Barcha sinflar'}
        recent = []
        if role == 'student':
            for result in GameResult.query.filter_by(student_id=session['student_id']).order_by(GameResult.played_at.desc()).limit(8).all():
                custom = None
                if result.game_key.startswith('custom-'):
                    try: custom = EducationalGame.query.filter_by(id=int(result.game_key[7:]), school_id=sid).first()
                    except ValueError: pass
                metadata = games_for_page.get(result.game_key, {})
                recent.append({'title': custom.title if custom else metadata.get('title', 'Bilim o‘yini'), 'icon': GAME_BANK.get(custom.game_type, GAME_BANK['box'])['icon'] if custom else metadata.get('icon', '🎮'), 'points': result.points})
        return render_template('games.html', games=games_for_page, recent=recent, role=role, classes=classes, custom_games=custom_games)

    @app.route('/games/create', methods=['POST'])
    def game_create():
        role, sid = session.get('user_role'), session.get('school_id')
        if role not in {'admin', 'teacher'} or not sid: return redirect(url_for('home'))
        title = sanitize_input(request.form.get('title', '')).strip()[:100]
        description = sanitize_input(request.form.get('description', '')).strip()[:300]
        game_type = request.form.get('game_type', '')
        if game_type not in GAME_BANK or not title:
            flash('O‘yin nomi va turini to‘g‘ri kiriting.', 'danger'); return redirect(url_for('games'))
        class_id = request.form.get('class_id', type=int)
        if role == 'teacher':
            if not class_id or class_id not in teacher_class_ids(session['teacher_id']):
                flash('O‘yinni faqat o‘zingiz dars beradigan sinfga biriktiring.', 'danger'); return redirect(url_for('games'))
        elif class_id and not Class.query.filter_by(id=class_id, school_id=sid).first():
            flash('Tanlangan sinf topilmadi.', 'danger'); return redirect(url_for('games'))
        questions = []
        for number in range(1, 6):
            prompt = sanitize_input(request.form.get(f'question_{number}', '')).strip()[:1000]
            if not prompt: continue
            options = [sanitize_input(request.form.get(f'option_{number}_{letter}', '')).strip()[:120] for letter in 'abcd']
            correct_letter = request.form.get(f'correct_{number}', '').lower()
            if not all(options) or correct_letter not in {'a', 'b', 'c', 'd'}:
                flash(f'{number}-savolning 4 ta javob variantini kiriting va to‘g‘ri javobni belgilang.', 'danger'); return redirect(url_for('games'))
            questions.append({'prompt': prompt, 'options': options, 'answer': options['abcd'.index(correct_letter)]})
        if not questions:
            flash('Kamida bitta savol va uning javob variantlarini kiriting.', 'danger'); return redirect(url_for('games'))
        game = EducationalGame(school_id=sid, class_id=class_id, created_by_role=role, created_by_id=session['teacher_id'] if role == 'teacher' else sid, title=title, game_type=game_type, description=description or None)
        db.session.add(game); db.session.flush()
        for item in questions:
            db.session.add(EducationalGameQuestion(game_id=game.id, prompt=item['prompt'], option_a=item['options'][0], option_b=item['options'][1], option_c=item['options'][2], option_d=item['options'][3], correct_answer=item['answer']))
        db.session.commit(); flash(f'“{title}” o‘yini {len(questions)} ta savol bilan saqlandi.', 'success')
        return redirect(url_for('games'))

    @app.route('/games/start/<game_key>', methods=['POST'])
    def game_start(game_key):
        if session.get('user_role') != 'student' or not session.get('school_id'): return redirect(url_for('home'))
        session.pop('custom_game_progress', None)
        question_number, question_total = 1, 1
        game = GAME_BANK.get(game_key)
        if game:
            prompt, answer, choices = game['prompt'], game['answer'], game['choices']
        elif game_key.startswith('custom-'):
            student = Student.query.filter_by(id=session['student_id'], school_id=session['school_id']).first_or_404()
            try: game_id = int(game_key[7:])
            except ValueError: return redirect(url_for('games'))
            custom_game = EducationalGame.query.filter(EducationalGame.id == game_id, EducationalGame.school_id == student.school_id, EducationalGame.is_active.is_(True), or_(EducationalGame.class_id.is_(None), EducationalGame.class_id == student.class_id)).first_or_404()
            questions = EducationalGameQuestion.query.filter_by(game_id=custom_game.id).order_by(EducationalGameQuestion.id).all()
            if not questions: flash('Bu o‘yinda hozircha savollar yo‘q.', 'warning'); return redirect(url_for('games'))
            question_ids = [item.id for item in questions]
            session['custom_game_progress'] = {'game_id': custom_game.id, 'question_ids': question_ids, 'index': 0}
            question_number, question_total = 1, len(question_ids)
            question = questions[0]
            game = {'title': custom_game.title, 'icon': GAME_BANK.get(custom_game.game_type, GAME_BANK['box'])['icon']}
            prompt, answer = question.prompt, question.correct_answer
            choices = [value for value in [question.option_a, question.option_b, question.option_c, question.option_d] if value]
            game_key = f'custom-{custom_game.id}'
        else:
            return redirect(url_for('games'))
        challenge = GameChallenge(token=str(uuid.uuid4()), student_id=session['student_id'], school_id=session['school_id'], game_key=game_key, prompt=prompt, answer=answer, choices_json=json.dumps(choices, ensure_ascii=False))
        db.session.add(challenge); db.session.commit()
        if game_key.startswith('custom-'):
            progress = session.get('custom_game_progress') or {}
            session['custom_game_progress'] = {**progress, 'token': challenge.token}
        return render_template('game_play.html', game=game, challenge=challenge, choices=random.sample(choices, len(choices)) if choices else [], question_number=question_number, question_total=question_total, feedback=None)

    @app.route('/games/answer', methods=['POST'])
    def game_answer():
        if session.get('user_role') != 'student' or not session.get('school_id'): return redirect(url_for('home'))
        token = request.form.get('token', '')
        challenge = GameChallenge.query.filter_by(token=token, student_id=session['student_id'], school_id=session['school_id']).first()
        if not challenge: flash('O‘yin savoli eskirgan. Qayta boshlang.', 'danger'); return redirect(url_for('games'))
        if challenge.created_at < datetime.utcnow() - timedelta(minutes=15):
            db.session.delete(challenge); db.session.commit(); flash('O‘yin vaqti tugadi. Qayta urinib ko‘ring.', 'warning'); return redirect(url_for('games'))
        correct = request.form.get('answer', '').strip().casefold() == challenge.answer.strip().casefold()
        local_now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5)))
        local_start = datetime.combine(local_now.date(), datetime.min.time(), tzinfo=local_now.tzinfo)
        day_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
        day_end = (local_start + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
        scored_today = GameResult.query.filter_by(student_id=session['student_id']).filter(GameResult.played_at >= day_start, GameResult.played_at < day_end, GameResult.points > 0).count()
        points = 15 if correct and scored_today < 5 else 0
        if correct:
            if points:
                student = Student.query.filter_by(id=session['student_id'], school_id=session['school_id']).first()
                if student: student.xp = (student.xp or 0) + points; student.level = (student.xp // 500) + 1
                db.session.add(GameResult(student_id=session['student_id'], school_id=session['school_id'], game_key=challenge.game_key, score=1, points=points))
        game_key = challenge.game_key

        if game_key.startswith('custom-'):
            try: custom_game_id = int(game_key[7:])
            except ValueError: custom_game_id = None
            progress = session.get('custom_game_progress') or {}
            question_ids = progress.get('question_ids') or []
            current_index = progress.get('index', 0)
            if progress.get('game_id') != custom_game_id or progress.get('token') != token or current_index >= len(question_ids):
                db.session.delete(challenge); db.session.commit()
                session.pop('custom_game_progress', None)
                flash('O‘yin sessiyasi tugadi. O‘yinni qaytadan boshlang.', 'warning')
                return redirect(url_for('games'))

            custom_game = EducationalGame.query.filter_by(id=custom_game_id, school_id=session['school_id'], is_active=True).first()
            if not custom_game:
                db.session.delete(challenge); db.session.commit()
                session.pop('custom_game_progress', None)
                flash('Bu o‘yin endi mavjud emas.', 'warning')
                return redirect(url_for('games'))
            game = {'title': custom_game.title, 'icon': GAME_BANK.get(custom_game.game_type, GAME_BANK['box'])['icon']}
            choices = json.loads(challenge.choices_json or '[]')

            if not correct:
                return render_template('game_play.html', game=game, challenge=challenge, choices=random.sample(choices, len(choices)) if choices else [], question_number=current_index + 1, question_total=len(question_ids), feedback='Javob noto‘g‘ri. Yana bir marta urinib ko‘ring.')

            current_index += 1
            db.session.delete(challenge)
            if current_index >= len(question_ids):
                db.session.commit()
                session.pop('custom_game_progress', None)
                if points: flash('Ajoyib! Barcha savollar tugadi. To‘g‘ri javob uchun +15 XP oldingiz 🎉', 'success')
                else: flash('Ajoyib! Barcha savollar tugadi. Bugungi XP limiti ishlatildi.', 'success')
                return redirect(url_for('games', played=game_key))

            next_question = EducationalGameQuestion.query.filter_by(id=question_ids[current_index], game_id=custom_game.id).first()
            if not next_question:
                db.session.commit()
                session.pop('custom_game_progress', None)
                flash('Keyingi savol topilmadi. O‘yin yakunlandi.', 'warning')
                return redirect(url_for('games', played=game_key))
            next_choices = [value for value in [next_question.option_a, next_question.option_b, next_question.option_c, next_question.option_d] if value]
            next_challenge = GameChallenge(token=str(uuid.uuid4()), student_id=session['student_id'], school_id=session['school_id'], game_key=game_key, prompt=next_question.prompt, answer=next_question.correct_answer, choices_json=json.dumps(next_choices, ensure_ascii=False))
            db.session.add(next_challenge)
            db.session.commit()
            session['custom_game_progress'] = {**progress, 'index': current_index, 'token': next_challenge.token}
            return render_template('game_play.html', game=game, challenge=next_challenge, choices=random.sample(next_choices, len(next_choices)) if next_choices else [], question_number=current_index + 1, question_total=len(question_ids), feedback='To‘g‘ri javob! Keyingi savolga o‘tdingiz.' + (' +15 XP 🎉' if points else ''))

        db.session.delete(challenge); db.session.commit()
        if points: flash('To‘g‘ri javob! +15 XP 🎉', 'success')
        elif correct: flash('Javob to‘g‘ri! Bugungi 5 ta ball beriladigan urinishdan foydalandingiz. Ertaga davom eting.', 'info')
        else: flash('Bu safar topilmadi. Keyingi o‘yinda omad!', 'warning')
        return redirect(url_for('games', played=game_key))

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
        dashboard_clubs = Club.query.filter_by(school_id=sid).order_by(Club.name).all()
        average_score = round(sum(item.percentage or 0 for item in results) / len(results), 1) if results else 0
        passed_results = sum((item.percentage or 0) >= 60 for item in results)
        today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5))).date()
        today_rows = []
        for cls in school_classes:
            roster = Student.query.filter_by(school_id=sid, class_id=cls.id).count()
            marked = Attendance.query.filter_by(school_id=sid, class_id=cls.id, attendance_date=today).all()
            present = sum(item.status == 'present' for item in marked)
            today_rows.append({'class': cls, 'present': present, 'total': roster, 'percent': round(present * 100 / roster) if roster else 0})
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
            club_class_counts=json.dumps([row[1] for row in club_class_rows]),
            dashboard_clubs=dashboard_clubs,
            dashboard_spotlights=current_spotlights(sid),
            dashboard_students=weekly_student_scores(sid)[:5],
            dashboard_classes=class_weekly_scores(sid)[:5],
            dashboard_attendance=today_rows)

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
        assigned_class_ids = {assignment.class_id for assignment in assigned_classes}
        unique_classes.update(assignment.student_class for assignment in assigned_classes)
        for s in my_schedules:
            if s.day_of_week in grouped:
                grouped[s.day_of_week].append(s)
                if s.student_class: unique_classes.add(s.student_class)
        clubs = Club.query.filter_by(school_id=session['school_id']).order_by(func.lower(Club.name), Club.schedule).all()
        sid = session['school_id']
        return render_template("teacher_dashboard.html", teacher=teacher, schedule=grouped, my_classes=sorted(unique_classes, key=lambda item: item.name.casefold()), assigned_class_ids=assigned_class_ids, clubs=clubs,
            spotlights=current_spotlights(sid), weekly_students=weekly_student_scores(sid)[:5], weekly_classes=class_weekly_scores(sid)[:5])

    # --- O'QITUVCHI-O'QUVCHI ICHKI CHAT ---
    @app.route("/chat")
    def chat():
        role = session.get('user_role')
        if 'school_id' not in session or role not in {'admin', 'student', 'teacher'}:
            return redirect(url_for('home'))

        sid = session['school_id']
        if role == 'admin':
            messages = ChatMessage.query.filter_by(school_id=sid).order_by(ChatMessage.created_at.desc()).all()
            teachers = Teacher.query.filter_by(school_id=sid).order_by(Teacher.first_name, Teacher.last_name).all()
            students = Student.query.filter_by(school_id=sid).order_by(Student.first_name, Student.last_name).all()
            return render_template("chat_admin.html", messages=messages, teachers=teachers, students=students)

        if role == 'student':
            current_user_id = session['student_id']
            contacts = Teacher.query.filter_by(school_id=sid).order_by(Teacher.first_name, Teacher.last_name).all()
            contact_type = 'teacher'
            selected_id = request.args.get('contact_id', type=int) or (contacts[0].id if contacts else None)
            selected = next((item for item in contacts if item.id == selected_id), None)
        else:
            current_user_id = session['teacher_id']
            contacts = Student.query.filter_by(school_id=sid).order_by(Student.first_name, Student.last_name).all()
            contact_type = 'student'
            selected_id = request.args.get('contact_id', type=int) or (contacts[0].id if contacts else None)
            selected = next((item for item in contacts if item.id == selected_id), None)

        messages = []
        if selected:
            messages = ChatMessage.query.filter(
                ChatMessage.school_id == sid,
                or_(
                    and_(ChatMessage.sender_type == role, ChatMessage.sender_id == current_user_id,
                         ChatMessage.recipient_type == contact_type, ChatMessage.recipient_id == selected.id),
                    and_(ChatMessage.sender_type == contact_type, ChatMessage.sender_id == selected.id,
                        ChatMessage.recipient_type == role, ChatMessage.recipient_id == current_user_id),
                    and_(ChatMessage.sender_type == 'admin', ChatMessage.recipient_type == role,
                        ChatMessage.recipient_id == current_user_id)
                )
            ).order_by(ChatMessage.created_at.asc()).all()

        return render_template(
            "chat.html",
            contacts=contacts,
            selected=selected,
            selected_type=contact_type,
            messages=messages,
            current_role=role,
            current_user_id=current_user_id
        )

    @app.route("/chat/send", methods=["POST"])
    def send_chat_message():
        role = session.get('user_role')
        if 'school_id' not in session or role not in {'admin', 'student', 'teacher'}:
            return redirect(url_for('home'))

        recipient_type = request.form.get('recipient_type')
        recipient_id = request.form.get('recipient_id', type=int)
        body = sanitize_input(request.form.get('body', '')).strip()
        if recipient_type not in {'student', 'teacher'} or not recipient_id or not body:
            flash("Xabar va qabul qiluvchini tanlang.", "warning")
            return redirect(url_for('chat'))

        if role != 'admin' and recipient_type == role:
            flash("O'zingizga xabar yubora olmaysiz.", "warning")
            return redirect(url_for('chat'))

        model = Teacher if recipient_type == 'teacher' else Student
        recipient = model.query.filter_by(id=recipient_id, school_id=session['school_id']).first()
        if not recipient:
            flash("Qabul qiluvchi topilmadi.", "danger")
            return redirect(url_for('chat'))

        sender_id = session['teacher_id'] if role == 'teacher' else session['student_id'] if role == 'student' else session['school_id']
        db.session.add(ChatMessage(
            school_id=session['school_id'],
            sender_type=role,
            sender_id=sender_id,
            recipient_type=recipient_type,
            recipient_id=recipient_id,
            body=body[:2000]
        ))
        db.session.commit()
        return redirect(url_for('chat', contact_id=recipient_id))

    def can_manage_chat_message(message):
        return session.get('user_role') == 'admin'

    @app.route("/chat/message/<int:message_id>/edit", methods=["GET", "POST"])
    def edit_chat_message(message_id):
        if 'school_id' not in session or session.get('user_role') != 'admin':
            return redirect(url_for('home'))
        message = ChatMessage.query.filter_by(id=message_id, school_id=session['school_id']).first_or_404()
        if not can_manage_chat_message(message):
            return redirect(url_for('chat'))
        if request.method == 'POST':
            body = sanitize_input(request.form.get('body', '')).strip()
            if not body:
                flash("Xabar bo‘sh bo‘lishi mumkin emas.", "warning")
                return render_template("edit_chat_message.html", message=message)
            message.body = body[:2000]
            db.session.commit()
            flash("Xabar tahrirlandi.", "success")
            return redirect(url_for('chat'))
        return render_template("edit_chat_message.html", message=message)

    @app.route("/chat/message/<int:message_id>/delete", methods=["POST"])
    def delete_chat_message(message_id):
        if 'school_id' not in session or session.get('user_role') != 'admin':
            return redirect(url_for('home'))
        message = ChatMessage.query.filter_by(id=message_id, school_id=session['school_id']).first_or_404()
        if not can_manage_chat_message(message):
            return redirect(url_for('chat'))
        contact_id = message.recipient_id
        db.session.delete(message)
        db.session.commit()
        flash("Xabar o‘chirildi.", "success")
        return redirect(url_for('chat'))

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
        # The template reads each teacher's subject. Load it in the same query
        # so a large school does not issue one extra database query per teacher.
        teachers = (Teacher.query
                    .options(joinedload(Teacher.subject))
                    .filter_by(school_id=session['school_id'])
                    .order_by(Teacher.first_name, Teacher.last_name)
                    .all())
        return render_template("teachers.html", teachers=teachers)

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
            lesson_day = request.form.get('lesson_day'); start_time = request.form.get('start_time'); end_time = request.form.get('end_time')
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
        if 'school_id' not in session or session.get('user_role') not in {'admin', 'teacher'}: return redirect(url_for('home'))
        return render_template("tests.html", tests=Test.query.filter_by(school_id=session['school_id']).all())

    @app.route("/create_test", methods=["GET", "POST"])
    def create_test():
        if 'school_id' not in session or session.get('user_role') not in {'admin', 'teacher'}: return redirect(url_for('home'))
        sid = session['school_id']
        if request.method == "POST":
            t = Test(title=sanitize_input(request.form.get('title')), school_id=sid, subject_id=request.form.get('subject_id'), class_id=request.form.get('class_id'), created_by_teacher_id=session.get('teacher_id'))
            db.session.add(t); db.session.commit(); return redirect(url_for('add_question', test_id=t.id))
        return render_template("create_test.html", subjects=Subject.query.filter_by(school_id=sid).all(), classes=Class.query.filter_by(school_id=sid).all())

    @app.route("/add_question/<int:test_id>", methods=["GET", "POST"])
    def add_question(test_id):
        if 'school_id' not in session or session.get('user_role') not in {'admin', 'teacher'}: return redirect(url_for('home'))
        test = Test.query.filter_by(id=test_id, school_id=session['school_id']).first_or_404()
        if session.get('user_role') == 'teacher' and test.created_by_teacher_id != session.get('teacher_id'):
            return redirect(url_for('tests'))
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
        results = TestResult.query.join(Student).join(Test).filter(Student.school_id == session['school_id']).order_by(TestResult.submitted_at.desc()).all()
        return render_template("all_test_results.html", results=results)

    @app.route("/student_dashboard")
    def student_dashboard():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        st = Student.query.get(session['student_id'])
        if not st or st.school_id != session['school_id']:
            session.clear()
            return redirect(url_for('home'))
        res = TestResult.query.filter_by(student_id=st.id).order_by(TestResult.submitted_at.desc()).limit(5).all()
        ach = StudentAchievement.query.filter_by(student_id=st.id).all()
        nws = News.query.filter_by(school_id=st.school_id).order_by(News.created_at.desc()).limit(3).all()
        clubs = Club.query.filter_by(school_id=st.school_id).order_by(Club.name).all()
        latest_grades = Grade.query.filter_by(student_id=st.id).order_by(Grade.created_at.desc()).limit(5).all()
        week_scores = weekly_student_scores(st.school_id)
        own_rank = next((index for index, item in enumerate(week_scores, 1) if item['student'].id == st.id), None)
        labels = [r.test.title[:15] for r in reversed(res)]; data = [r.percentage for r in reversed(res)]
        while len(data) < 5: labels.insert(0, f"Test {len(data)+1}"); data.insert(0, 0)
        return render_template("student_dashboard.html", student=st, results=res, achievements=ach, news=nws, clubs=clubs, chart_labels=json.dumps(labels), chart_data=json.dumps(data), latest_grades=latest_grades, weekly_rank=own_rank, weekly_scores=week_scores[:5], weekly_classes=class_weekly_scores(st.school_id)[:5], spotlights=current_spotlights(st.school_id))

    @app.route("/student_profile", methods=["GET", "POST"])
    def student_profile():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        student = Student.query.filter_by(id=session['student_id'], school_id=session['school_id']).first_or_404()
        if request.method == "POST":
            student.first_name = sanitize_input(request.form.get('first_name')) or student.first_name
            student.last_name = sanitize_input(request.form.get('last_name')) or student.last_name
            student.gender = sanitize_input(request.form.get('gender')) or student.gender
            birth_date = request.form.get('birth_date')
            if birth_date: student.birth_date = datetime.strptime(birth_date, '%Y-%m-%d').date()
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
        if scid: query = query.filter_by(class_id=scid)
        items = query.order_by(db.case({"Dushanba":1,"Seshanba":2,"Chorshanba":3,"Payshanba":4,"Juma":5,"Shanba":6}, value=Schedule.day_of_week), Schedule.start_time).all()
        return render_template("manage_schedule.html", classes=cls, selected_class_id=scid, schedule_items=items, subjects=Subject.query.filter_by(school_id=sid).all(), teachers=Teacher.query.filter_by(school_id=sid).all())

    @app.route("/schedule/add", methods=["POST"])
    def add_schedule():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        tid = request.form.get('teacher_id', type=int); class_id = request.form.get('class_id', type=int) or None; subject_id = request.form.get('subject_id', type=int)
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
            teacher_id = request.form.get('teacher_id', type=int); subject_id = request.form.get('subject_id', type=int); class_id = request.form.get('class_id', type=int) or None
            if not teacher_id or not subject_id:
                flash("O'qituvchi va fan tanlanishi shart.", "danger")
                return render_template("edit_schedule.html", lesson=lesson, classes=classes, subjects=subjects, teachers=teachers)
            lesson.day_of_week = request.form.get('day_of_week'); lesson.start_time = request.form.get('start_time'); lesson.end_time = request.form.get('end_time')
            lesson.room_number = sanitize_input(request.form.get('room_number')); lesson.class_id = class_id; lesson.subject_id = subject_id; lesson.teacher_id = teacher_id
            db.session.commit(); return redirect(url_for('manage_schedule', class_id=class_id))
        return render_template("edit_schedule.html", lesson=lesson, classes=classes, subjects=subjects, teachers=teachers)

    @app.route("/schedule/delete/<int:schedule_id>", methods=["POST"])
    def delete_schedule(schedule_id):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        lesson = Schedule.query.filter_by(id=schedule_id, school_id=session['school_id']).first_or_404()
        class_id = lesson.class_id; db.session.delete(lesson); db.session.commit()
        flash("Dars o'chirildi.", "success"); return redirect(url_for('manage_schedule', class_id=class_id))

    @app.route("/schedule/view")
    def view_schedule():
        if 'school_id' not in session or session.get('user_role') != 'student': return redirect(url_for('home'))
        st = Student.query.filter_by(id=session['student_id'], school_id=session['school_id']).first_or_404()
        items = Schedule.query.filter(Schedule.school_id == st.school_id, Schedule.class_id == st.class_id).order_by(db.case({"Dushanba":1,"Seshanba":2,"Chorshanba":3,"Payshanba":4,"Juma":5,"Shanba":6}, value=Schedule.day_of_week), Schedule.start_time).all()
        gs = {d:[] for d in ["Dushanba","Seshanba","Chorshanba","Payshanba","Juma","Shanba"]}
        for i in items: 
            if i.day_of_week in gs: gs[i.day_of_week].append(i)
        return render_template("view_schedule.html", schedule=gs, student=st)

    @app.route("/teacher/schedule")
    def teacher_schedule():
        if 'school_id' not in session or session.get('user_role') != 'teacher':
            return redirect(url_for('home'))
        teacher_id = session['teacher_id']
        items = Schedule.query.filter_by(
            school_id=session['school_id'], teacher_id=teacher_id
        ).options(
            joinedload(Schedule.student_class), joinedload(Schedule.subject)
        ).order_by(
            db.case({"Dushanba": 1, "Seshanba": 2, "Chorshanba": 3,
                     "Payshanba": 4, "Juma": 5, "Shanba": 6},
                    value=Schedule.day_of_week),
            Schedule.start_time
        ).all()
        days = {day: [] for day in ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba"]}
        for item in items:
            if item.day_of_week in days:
                days[item.day_of_week].append(item)
        return render_template("teacher_schedule.html", schedule=days)

    @app.route("/library/manage")
    def manage_library():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        return render_template("manage_library.html", books=Book.query.filter_by(school_id=session['school_id']).all())

    @app.route("/presentations")
    def presentations():
        if 'school_id' not in session or session.get('user_role') not in {'admin', 'student', 'teacher'}:
            return redirect(url_for('home'))
        items = Presentation.query.filter_by(school_id=session['school_id']).order_by(Presentation.created_at.desc()).all()
        return render_template("presentations.html", presentations=items, current_role=session.get('user_role'))

    @app.route("/presentations/upload", methods=["POST"])
    def upload_presentation():
        if 'school_id' not in session or session.get('user_role') != 'teacher':
            return redirect(url_for('home'))
        uploaded = request.files.get('presentation_file')
        if not uploaded or not uploaded.filename:
            flash("Taqdimot faylini tanlang.", "warning")
            return redirect(url_for('presentations'))
        filename = secure_filename(uploaded.filename)
        extension = os.path.splitext(filename)[1].lower()
        if extension not in {'.pdf', '.ppt', '.pptx'}:
            flash("Faqat PDF, PPT yoki PPTX fayl yuklash mumkin.", "danger")
            return redirect(url_for('presentations'))
        upload_dir = os.path.join(app.static_folder, 'uploads', 'presentations')
        os.makedirs(upload_dir, exist_ok=True)
        saved_name = f"{session['teacher_id']}_{int(datetime.now().timestamp())}_{filename}"
        uploaded.save(os.path.join(upload_dir, saved_name))
        db.session.add(Presentation(
            title=sanitize_input(request.form.get('title')) or filename,
            description=sanitize_input(request.form.get('description')),
            file_url=url_for('static', filename=f'uploads/presentations/{saved_name}'),
            school_id=session['school_id'],
            teacher_id=session['teacher_id']
        ))
        db.session.commit()
        flash("Taqdimot muvaffaqiyatli yuklandi.", "success")
        return redirect(url_for('presentations'))

    def can_manage_presentation(presentation):
        role = session.get('user_role')
        return (role == 'admin' or
                (role == 'teacher' and presentation.teacher_id == session.get('teacher_id')))

    @app.route("/presentations/<int:presentation_id>/edit", methods=["GET", "POST"])
    def edit_presentation(presentation_id):
        if 'school_id' not in session or session.get('user_role') not in {'admin', 'teacher'}:
            return redirect(url_for('home'))
        presentation = Presentation.query.filter_by(
            id=presentation_id, school_id=session['school_id']
        ).first_or_404()
        if not can_manage_presentation(presentation):
            return redirect(url_for('presentations'))
        if request.method == 'POST':
            title = sanitize_input(request.form.get('title', '')).strip()
            if not title:
                flash("Taqdimot nomini kiriting.", "warning")
                return render_template("edit_presentation.html", presentation=presentation)
            presentation.title = title[:200]
            presentation.description = sanitize_input(request.form.get('description', '')).strip()
            db.session.commit()
            flash("Taqdimot yangilandi.", "success")
            return redirect(url_for('presentations'))
        return render_template("edit_presentation.html", presentation=presentation)

    @app.route("/presentations/<int:presentation_id>/delete", methods=["POST"])
    def delete_presentation(presentation_id):
        if 'school_id' not in session or session.get('user_role') not in {'admin', 'teacher'}:
            return redirect(url_for('home'))
        presentation = Presentation.query.filter_by(
            id=presentation_id, school_id=session['school_id']
        ).first_or_404()
        if not can_manage_presentation(presentation):
            return redirect(url_for('presentations'))
        upload_dir = os.path.realpath(os.path.join(app.static_folder, 'uploads', 'presentations'))
        is_local_upload = presentation.file_url.startswith('/static/uploads/presentations/')
        filename = os.path.basename(presentation.file_url.split('?', 1)[0]) if is_local_upload else ''
        file_path = os.path.realpath(os.path.join(upload_dir, filename))
        db.session.delete(presentation)
        db.session.commit()
        if filename and os.path.commonpath([upload_dir, file_path]) == upload_dir and os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError:
                app.logger.warning("Taqdimot faylini o‘chirish amalga oshmadi: %s", file_path)
        flash("Taqdimot o‘chirildi.", "success")
        return redirect(url_for('presentations'))

    @app.route("/library/add", methods=["POST"])
    def add_book():
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        try:
            db.session.add(Book(
                title=sanitize_input(request.form.get('title')), 
                author=sanitize_input(request.form.get('author')), 
                genre=request.form.get('genre'), 
                description=sanitize_input(request.form.get('description')), 
                cover_url=sanitize_input(request.form.get('cover_url')), 
                file_url=sanitize_input(request.form.get('file_url')), 
                school_id=session['school_id']
            ))
            db.session.commit()
            return redirect(url_for('manage_library'))
        except Exception as e:
            db.session.rollback()
            print(f"Kitob qo'shishda xato: {e}")
            flash(f"Xatolik yuz berdi: {e}", "danger")
            return redirect(url_for('manage_library'))

    @app.route("/library")
    def student_library():
        if 'school_id' not in session or session.get('user_role') not in {'student', 'teacher'}: return redirect(url_for('home'))
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
        image_path = None
        uploaded_file = request.files.get('news_image')
        if uploaded_file and uploaded_file.filename:
            try:
                image_path, _ = save_news_image(uploaded_file)
            except ValueError as error:
                flash(str(error), 'danger')
                return redirect(url_for('manage_news'))
        news_item = News(title=sanitize_input(request.form.get('title')), content=sanitize_input(request.form.get('content')), image_url=image_path, is_announcement=(request.form.get('is_announcement')=='on'), school_id=session['school_id'])
        db.session.add(news_item)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            if image_path:
                remove_news_image(image_path)
            app.logger.exception('Yangilikni saqlashda xatolik')
            flash("Yangilikni saqlashda xatolik yuz berdi.", 'danger')
        else:
            flash("Yangilik muvaffaqiyatli joylandi.", 'success')
        return redirect(url_for('manage_news'))

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

    @app.route("/ask_ai_chat_stream", methods=["POST"])
    @csrf.exempt
    def ask_ai_chat_stream():
        if 'school_id' not in session: return jsonify({"error": "Unauthorized"}), 401
        data = request.get_json(); user_message = data.get('message', '')
        if not user_message: return jsonify({"reply": ""})
        try:
            api_key = os.environ.get('GROQ_API_KEY')
            if not api_key: return jsonify({"reply": "⚠️ Groq API kaliti topilmadi."})
            client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
            response = client.chat.completions.create(model="openai/gpt-oss-20b", messages=[{"role": "system", "content": "Siz maktab o'quvchilari uchun mehribon AI yordamchisiz. Qisqa va aniq javob bering."}, {"role": "user", "content": user_message}])
            reply = response.choices[0].message.content; return jsonify({"reply": reply})
        except Exception as e:
            print(f"Groq Xatosi: {e}"); return jsonify({"reply": f"Xatolik: {str(e)}"}), 500

    @app.route("/clear_chat", methods=["POST"])
    @csrf.exempt
    def clear_chat():
        if 'school_id' in session: session['chat_history'] = []; session.modified = True
        return jsonify({"status": "cleared"})

    # --- TO'GARAKLAR ROUTE LARI ---
    @app.route("/clubs/stats")
    def clubs_stats():
        if 'school_id' not in session or session.get('user_role') != 'admin': 
            return jsonify({"total_members": 0})
        
        try:
            sid = session['school_id']
            
            # To'g'ri usul: StudentClub va Student jadvallarini join qilish
            total_members = db.session.query(func.count(StudentClub.id))\
                .join(Student, Student.id == StudentClub.student_id)\
                .filter(Student.school_id == sid)\
                .scalar() or 0
            
            return jsonify({"total_members": total_members})
        except Exception as e:
            print(f"Stats error: {e}")
            return jsonify({"total_members": 0})

    
    @app.route("/clubs/members/list")
    def get_club_members_list():
        role = session.get('user_role')
        if 'school_id' not in session or role not in {'admin', 'teacher'}:
            return jsonify([])
        
        try:
            sid = session['school_id']
            query = db.session.query(StudentClub, Student, Club, Class) \
                .join(Student, Student.id == StudentClub.student_id) \
                .join(Club, Club.id == StudentClub.club_id) \
                .outerjoin(Class, Student.class_id == Class.id) \
                .filter(Student.school_id == sid, Club.school_id == sid)
            club_id = request.args.get('club_id', type=int)
            if club_id:
                query = query.filter(Club.id == club_id)
            rows = query.order_by(Club.name, Class.name, Student.last_name).all()
            result = [{
                "name": f"{student.first_name} {student.last_name}",
                "class": school_class.name if school_class else "Sinf ko‘rsatilmagan",
                "phone": membership.phone or "Ko‘rsatilmagan",
                "club": club.name,
            } for membership, student, club, school_class in rows]
            return jsonify(result)
        except Exception as e:
            print(f"Members list error: {e}")
            return jsonify([])

    @app.route("/clubs/manage")
    def manage_clubs():
        if 'school_id' not in session or session.get('user_role') not in {'admin', 'teacher'}: return redirect(url_for('home'))
        clubs = Club.query.filter_by(school_id=session['school_id']).all()
        current_teacher = Teacher.query.filter_by(id=session.get('teacher_id'), school_id=session['school_id']).first() if session.get('user_role') == 'teacher' else None
        return render_template("manage_clubs.html", clubs=clubs, current_role=session.get('user_role'), current_teacher_id=session.get('teacher_id'), current_teacher=current_teacher)

    @app.route("/clubs/add", methods=["POST"])
    def add_club():
        role = session.get('user_role')
        if 'school_id' not in session or role not in {'admin', 'teacher'}: return redirect(url_for('home'))
        teacher_id = session.get('teacher_id') if role == 'teacher' else None
        club_name = sanitize_input(request.form.get('name', '')).strip()
        leader_name = sanitize_input(request.form.get('leader_name', '')).strip()
        if not club_name or not leader_name:
            flash("To‘garak nomi va rahbarining ismini kiriting.", "warning")
            return redirect(url_for('manage_clubs'))
        if role == 'teacher' and not Teacher.query.filter_by(id=teacher_id, school_id=session['school_id']).first():
            flash("O‘qituvchi hisobi topilmadi. Qayta kiring va urinib ko‘ring.", "danger")
            return redirect(url_for('manage_clubs'))
        valid_days = ['Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba', 'Yakshanba']
        days = request.form.getlist('days')
        days = [day for day in valid_days if day in days]
        start_time = request.form.get('start_time', '').strip()
        end_time = request.form.get('end_time', '').strip()
        if not days or not start_time or not end_time or end_time <= start_time:
            flash("To‘garak kunlarini va boshlanish/tugash vaqtini to‘g‘ri kiriting.", "warning")
            return redirect(url_for('manage_clubs'))
        schedule = f"{', '.join(days)} | {start_time}–{end_time}"
        club = Club(
            name=club_name[:200],
            description=sanitize_input(request.form.get('description')),
            teacher_id=teacher_id,
            leader_name=leader_name[:100],
            schedule=schedule,
            school_id=session['school_id']
        )
        try:
            db.session.add(club)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("To‘garakni saqlashda xatolik (school_id=%s, role=%s)", session.get('school_id'), role)
            flash("To‘garak saqlanmadi. Sahifani yangilab qayta urinib ko‘ring; muammo qolsa administratorga xabar bering.", "danger")
        return redirect(url_for('manage_clubs'))

    @app.route("/clubs/edit/<int:club_id>", methods=["GET", "POST"])
    def edit_club(club_id):
        role = session.get('user_role')
        if 'school_id' not in session or role not in {'admin', 'teacher'}:
            return redirect(url_for('home'))
        club = Club.query.filter_by(id=club_id, school_id=session['school_id']).first_or_404()
        if role == 'teacher' and club.teacher_id != session.get('teacher_id'):
            flash("Faqat o‘zingiz boshqaradigan to‘garakni tahrirlashingiz mumkin.", "danger")
            return redirect(url_for('manage_clubs'))

        valid_days = ['Dushanba', 'Seshanba', 'Chorshanba', 'Payshanba', 'Juma', 'Shanba', 'Yakshanba']
        schedule_parts = (club.schedule or '').split('|', 1)
        edit_days = [day.strip() for day in schedule_parts[0].split(',') if day.strip()] if schedule_parts else []
        edit_start_time = edit_end_time = ''
        if len(schedule_parts) == 2:
            time_parts = schedule_parts[1].strip().replace('–', '-').split('-', 1)
            if len(time_parts) == 2:
                edit_start_time, edit_end_time = [part.strip() for part in time_parts]

        if request.method == 'POST':
            club_name = sanitize_input(request.form.get('name', '')).strip()
            leader_name = sanitize_input(request.form.get('leader_name', '')).strip()
            days = [day for day in valid_days if day in request.form.getlist('days')]
            start_time = request.form.get('start_time', '').strip()
            end_time = request.form.get('end_time', '').strip()
            if not club_name or not leader_name:
                flash("To‘garak nomi va rahbarining ismini kiriting.", "warning")
            elif not days or not start_time or not end_time or end_time <= start_time:
                flash("To‘garak kunlari va boshlanish/tugash vaqtlarini to‘g‘ri kiriting.", "warning")
            else:
                club.name = club_name[:200]
                club.description = sanitize_input(request.form.get('description'))
                club.leader_name = leader_name[:100]
                club.schedule = f"{', '.join(days)} | {start_time}–{end_time}"
                try:
                    db.session.commit()
                    flash("To‘garak ma’lumotlari yangilandi.", "success")
                    return redirect(url_for('manage_clubs'))
                except Exception:
                    db.session.rollback()
                    app.logger.exception("To‘garakni tahrirlashda xatolik (club_id=%s)", club_id)
                    flash("To‘garakni saqlashda xatolik yuz berdi. Qayta urinib ko‘ring.", "danger")

            edit_days = days
            edit_start_time = start_time
            edit_end_time = end_time

        clubs = Club.query.filter_by(school_id=session['school_id']).order_by(Club.name).all()
        current_teacher = Teacher.query.filter_by(id=session.get('teacher_id'), school_id=session['school_id']).first() if role == 'teacher' else None
        return render_template(
            "manage_clubs.html", clubs=clubs, current_role=role,
            current_teacher_id=session.get('teacher_id'), current_teacher=current_teacher,
            edit_club=club, edit_days=edit_days, edit_start_time=edit_start_time,
            edit_end_time=edit_end_time
        )

    @app.route("/clubs/delete/<int:club_id>")
    def delete_club(club_id):
        role = session.get('user_role')
        if 'school_id' not in session or role not in {'admin', 'teacher'}: return redirect(url_for('home'))
        club = Club.query.filter_by(id=club_id, school_id=session['school_id']).first_or_404()
        if role == 'teacher' and club.teacher_id != session['teacher_id']:
            flash("Faqat o'zingiz boshqaradigan to'garakni o'chira olasiz.", "danger")
            return redirect(url_for('manage_clubs'))
        
        # 1. Avval shu to'garakdagi barcha a'zolarni o'chirish
        StudentClub.query.filter_by(club_id=club.id).delete()
        
        # 2. Keyin to'garakning o'zini o'chirish
        db.session.delete(club)
        db.session.commit()
        
        flash("To'garak va unga tegishli ma'lumotlar o'chirildi.", "success")
        return redirect(url_for('manage_clubs'))

    @app.route("/clubs")
    def view_clubs():
        if 'school_id' not in session: return redirect(url_for('home'))
        clubs = Club.query.filter_by(school_id=session['school_id']).all()
        return render_template("clubs.html", clubs=clubs)

    @app.route("/clubs/join/<int:club_id>", methods=["POST"])
    def join_club(club_id):
        if 'school_id' not in session or session.get('user_role') != 'student': 
            return jsonify({"status": "error", "message": "Ruxsat yo‘q."}), 403
        
        student_id = session.get('student_id')
        club = Club.query.filter_by(id=club_id, school_id=session['school_id']).first()
        if not club:
            return jsonify({"status": "error", "message": "To‘garak topilmadi."}), 404

        phone = (request.form.get('phone') or '').strip()
        phone_digits = ''.join(character for character in phone if character in '0123456789')
        if not 9 <= len(phone_digits) <= 15:
            return jsonify({"status": "error", "message": "Telefon raqamini to‘g‘ri kiriting."}), 400
        if len(phone_digits) == 9:
            phone = '+998' + phone_digits
        elif phone_digits.startswith('998') and len(phone_digits) == 12:
            phone = '+' + phone_digits
        else:
            phone = '+' + phone_digits

        existing = StudentClub.query.filter_by(student_id=student_id, club_id=club_id).first()
        if existing:
            return jsonify({"status": "warning", "message": "Siz allaqachon a’zosiz."})
        else:
            db.session.add(StudentClub(student_id=student_id, club_id=club_id, phone=phone))
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                app.logger.exception("To‘garakka a’zo yozishda xatolik (club_id=%s)", club_id)
                return jsonify({"status": "error", "message": "A’zolik saqlanmadi. Qayta urinib ko‘ring."}), 500
            return jsonify({"status": "success", "message": "To‘garakka muvaffaqiyatli a’zo bo‘ldingiz!"})

    # --- O'CHIRISH ROUTE LARI ---
    @app.route("/delete_class/<int:cid>")
    def delete_class(cid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        c = Class.query.filter_by(id=cid, school_id=session['school_id']).first_or_404()
        for student in Student.query.filter_by(class_id=c.id, school_id=session['school_id']).all():
            remove_student_records(student.id)
            db.session.delete(student)
        Schedule.query.filter_by(class_id=c.id, school_id=session['school_id']).delete(synchronize_session=False)
        TeacherClassAssignment.query.filter_by(class_id=c.id).delete(synchronize_session=False)
        Test.query.filter_by(class_id=c.id, school_id=session['school_id']).update({Test.class_id: None}, synchronize_session=False)
        db.session.delete(c)
        db.session.commit()
        return redirect(url_for('classes'))

    @app.route("/delete_student/<int:sid>", methods=["POST"])
    def delete_student(sid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        s = Student.query.filter_by(id=sid, school_id=session['school_id']).first_or_404()
        remove_student_records(s.id)
        db.session.delete(s)
        db.session.commit()
        return redirect(url_for('students'))

    @app.route("/delete_teacher/<int:tid>", methods=["POST"])
    def delete_teacher(tid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        t = Teacher.query.filter_by(id=tid, school_id=session['school_id']).first_or_404()
        presentation_paths = remove_teacher_records(t.id, session['school_id'])
        db.session.delete(t)
        db.session.commit()
        for path in presentation_paths:
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    app.logger.warning("Taqdimot faylini o‘chirish amalga oshmadi: %s", path)
        return redirect(url_for('teachers'))

    @app.route("/delete_test/<int:test_id>")
    def delete_test(test_id):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        t = Test.query.filter_by(id=test_id, school_id=session['school_id']).first_or_404()
        TestResult.query.filter_by(test_id=t.id).delete(synchronize_session=False); TestQuestion.query.filter_by(test_id=t.id).delete(synchronize_session=False)
        db.session.delete(t); db.session.commit(); return redirect(url_for('tests'))

    @app.route("/delete_book/<int:bid>")
    def delete_book(bid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        b = Book.query.filter_by(id=bid, school_id=session['school_id']).first_or_404(); db.session.delete(b); db.session.commit(); return redirect(url_for('manage_library'))

    @app.route("/delete_news/<int:nid>")
    def delete_news(nid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        n = News.query.filter_by(id=nid, school_id=session['school_id']).first_or_404()
        image_url = n.image_url
        db.session.delete(n)
        db.session.commit()
        remove_news_image(image_url)
        return redirect(url_for('manage_news'))

    # --- TAHRIRLASH ROUTE LARI ---
    @app.route("/edit_class/<int:cid>", methods=["GET", "POST"])
    def edit_class(cid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        c = Class.query.filter_by(id=cid, school_id=session['school_id']).first_or_404()
        if request.method == "POST": c.name = sanitize_input(request.form.get('class_name')); db.session.commit(); return redirect(url_for('classes'))
        return render_template("edit_class.html", c=c)

    @app.route("/edit_student/<int:sid>", methods=["GET", "POST"])
    def edit_student(sid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        s = Student.query.filter_by(id=sid, school_id=session['school_id']).first_or_404()
        classes = Class.query.filter_by(school_id=session['school_id']).all()
        if request.method == "POST":
            old_first = s.first_name; old_last = s.last_name
            s.first_name = sanitize_input(request.form.get('first_name')); s.last_name = sanitize_input(request.form.get('last_name')); s.class_id = request.form.get('class_id')
            if old_first != s.first_name or old_last != s.last_name:
                new_login = f"{s.first_name.lower()}.{s.last_name.lower()}"
                existing = Student.query.filter_by(login=new_login).first()
                if not existing or existing.id == s.id: s.login = new_login
                else: flash(f"Yangi login ({new_login}) band. Login o'zgartirilmadi.", "warning")
            db.session.commit(); return redirect(url_for('students'))
        return render_template("edit_student.html", s=s, classes=classes)

    @app.route("/edit_teacher/<int:tid>", methods=["GET", "POST"])
    @app.route("/admin/edit_teacher/<int:tid>", methods=["GET", "POST"])
    def edit_teacher(tid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        sid = session['school_id']; t = Teacher.query.filter_by(id=tid, school_id=sid).first_or_404()
        classes = Class.query.filter_by(school_id=sid).order_by(Class.name).all()
        if request.method == "POST":
            t.first_name = sanitize_input(request.form.get('first_name')); t.last_name = sanitize_input(request.form.get('last_name'))
            new_login = sanitize_input(request.form.get('login'))
            existing_login = Teacher.query.filter_by(login=new_login).first()
            if existing_login and existing_login.id != t.id:
                flash("Bu login allaqachon ishlatilgan. Boshqa login tanlang.", "danger")
                return render_template("edit_teacher.html", t=t, classes=classes)
            subject_name = sanitize_input(request.form.get('subject_name'))
            subject = Subject.query.filter_by(name=subject_name.strip(), school_id=sid).first()
            if not subject: subject = Subject(name=subject_name.strip(), school_id=sid); db.session.add(subject); db.session.flush()
            t.subject_id = subject.id; t.login = new_login; t.phone = sanitize_input(request.form.get('phone'))
            selected_class_ids = {int(value) for value in request.form.getlist('class_ids') if value.isdigit()}
            valid_class_ids = {school_class.id for school_class in classes if school_class.id in selected_class_ids}
            TeacherClassAssignment.query.filter_by(teacher_id=t.id).delete()
            db.session.add_all([TeacherClassAssignment(teacher_id=t.id, class_id=class_id, subject_id=subject.id) for class_id in valid_class_ids])
            uploaded_image = request.files.get('profile_image')
            if uploaded_image and uploaded_image.filename: t.profile_pic = save_teacher_profile_image(uploaded_image, t.id)
            else: t.profile_pic = sanitize_input(request.form.get('profile_pic')) or t.profile_pic
            new_pass = request.form.get('password')
            if new_pass: t.password_hash = generate_password_hash(new_pass)
            db.session.commit(); return redirect(url_for('teachers'))
        assigned_class_ids = [assignment.class_id for assignment in TeacherClassAssignment.query.filter_by(teacher_id=t.id).all()]
        return render_template("edit_teacher.html", t=t, classes=classes, assigned_class_ids=assigned_class_ids)

    @app.route("/edit_book/<int:bid>", methods=["GET", "POST"])
    def edit_book(bid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        b = Book.query.filter_by(id=bid, school_id=session['school_id']).first_or_404()
        if request.method == "POST": b.title = sanitize_input(request.form.get('title')); b.author = sanitize_input(request.form.get('author')); b.genre = request.form.get('genre'); b.file_url = sanitize_input(request.form.get('file_url')); db.session.commit(); return redirect(url_for('manage_library'))
        return render_template("edit_book.html", b=b)

    @app.route("/edit_news/<int:nid>", methods=["GET", "POST"])
    def edit_news(nid):
        if 'school_id' not in session or session.get('user_role') != 'admin': return redirect(url_for('home'))
        n = News.query.filter_by(id=nid, school_id=session['school_id']).first_or_404()
        if request.method == "POST":
            n.title = sanitize_input(request.form.get('title')); n.content = sanitize_input(request.form.get('content'))
            old_image_url = n.image_url
            uploaded_file = request.files.get('news_image')
            new_image_url = None
            if uploaded_file and uploaded_file.filename:
                try:
                    new_image_url, _ = save_news_image(uploaded_file)
                except ValueError as error:
                    flash(str(error), 'danger')
                    return render_template("edit_news.html", n=n)
                n.image_url = new_image_url
            n.is_announcement = (request.form.get('is_announcement') == 'on')
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                if new_image_url:
                    remove_news_image(new_image_url)
                app.logger.exception('Yangilikni tahrirlashda xatolik')
                flash("Yangilikni saqlashda xatolik yuz berdi.", 'danger')
                return render_template("edit_news.html", n=n)
            if new_image_url and old_image_url != new_image_url:
                remove_news_image(old_image_url)
            flash("Yangilik muvaffaqiyatli yangilandi.", 'success')
            return redirect(url_for('manage_news'))
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
            
            # Logo faylini yuklash
            uploaded_logo = request.files.get('logo_file')
            if uploaded_logo and uploaded_logo.filename:
                try:
                    filename = secure_filename(uploaded_logo.filename)
                    ext = os.path.splitext(filename)[1].lower()
                    if ext in {'.jpg', '.jpeg', '.png', '.gif', '.webp'}:
                        upload_dir = os.path.join(app.static_folder, 'uploads', 'logos')
                        os.makedirs(upload_dir, exist_ok=True)
                        saved_name = f"school_{session['school_id']}{ext}"
                        uploaded_logo.save(os.path.join(upload_dir, saved_name))
                        school.logo = url_for('static', filename=f'uploads/logos/{saved_name}')
                        flash("Logo muvaffaqiyatli yangilandi!", "success")
                    else:
                        flash("Faqat rasmlar (JPG, PNG) yuklash mumkin.", "warning")
                except Exception as e:
                    print(f"Logo yuklash xatosi: {e}")
                    flash("Logoni yuklashda xatolik yuz berdi.", "danger")
            
            db.session.commit()
            session['school_name'] = school.name
            flash("Ma'lumotlar saqlandi.", "success")
            return redirect(url_for('admin_profile'))
        return render_template("admin_profile.html", school=school)

    @app.route("/logout")
    def logout():
        session.clear(); return redirect(url_for('home'))
        
    return app

# Gunicorn uchun app obyektini yaratish
app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
