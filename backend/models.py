from extensions import db
from datetime import datetime

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(200))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100), unique=True)
    login = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    logo = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    classes = db.relationship('Class', backref='school', lazy=True)
    students = db.relationship('Student', backref='school', lazy=True)
    teachers = db.relationship('Teacher', backref='school', lazy=True)
    subjects = db.relationship('Subject', backref='school', lazy=True)
    tests = db.relationship('Test', backref='school', lazy=True)
    schedules = db.relationship('Schedule', backref='school', lazy=True)
    books = db.relationship('Book', backref='school', lazy=True)
    news = db.relationship('News', backref='school', lazy=True)

    def __repr__(self):
        return f'<School {self.name}>'

class Class(db.Model):
    __tablename__ = 'classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(20), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    students = db.relationship('Student', backref='student_class', lazy=True)
    schedules = db.relationship('Schedule', backref='student_class', lazy=True)

    def __repr__(self):
        return f'<Class {self.name}>'

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    birth_date = db.Column(db.Date)
    gender = db.Column(db.String(10))
    student_id_code = db.Column(db.String(20), unique=True)
    login = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(200))
    profile_pic = db.Column(db.String(100))
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    xp = db.Column(db.Integer, default=0)
    level = db.Column(db.Integer, default=1)

    def __repr__(self):
        return f'<Student {self.first_name} {self.last_name}>'

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)

    def __repr__(self):
        return f'<Subject {self.name}>'

# YANGILANGAN TEACHER MODELI
class Teacher(db.Model):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20))
    login = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(200)) # Parol qo'shildi
    profile_pic = db.Column(db.String(100))   # Rasm qo'shildi
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'))
    subject = db.relationship('Subject', backref='teachers', lazy=True)
    schedules = db.relationship('Schedule', backref='schedule_teacher', lazy=True, overlaps="schedule_items,schedules") 

    def __repr__(self):
        return f'<Teacher {self.first_name} {self.last_name}>'

class TeacherClassAssignment(db.Model):
    __tablename__ = 'teacher_class_assignments'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'))

    teacher = db.relationship('Teacher', backref='class_assignments', lazy=True)
    student_class = db.relationship('Class', backref='teacher_assignments', lazy=True)
    subject = db.relationship('Subject', lazy=True)

class Test(db.Model):
    __tablename__ = 'tests'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'))
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'))
    created_by_teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    subject = db.relationship('Subject', backref='tests', lazy=True)
    test_class = db.relationship('Class', backref='tests', lazy=True)
    questions = db.relationship('TestQuestion', backref='test', lazy=True)

    def __repr__(self):
        return f'<Test {self.title}>'

class TestQuestion(db.Model):
    __tablename__ = 'test_questions'
    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey('tests.id'), nullable=False)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(200))
    option_b = db.Column(db.String(200))
    option_c = db.Column(db.String(200))
    option_d = db.Column(db.String(200))
    correct_answer = db.Column(db.String(1))
    topic = db.Column(db.String(100)) 
    subtopic = db.Column(db.String(100))

    def __repr__(self):
        return f'<Question {self.id}>'

class TestResult(db.Model):
    __tablename__ = 'test_results'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    test_id = db.Column(db.Integer, db.ForeignKey('tests.id'), nullable=False)
    score = db.Column(db.Integer)
    total_questions = db.Column(db.Integer)
    percentage = db.Column(db.Float)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    topic_analysis = db.Column(db.Text) 

    student = db.relationship('Student', backref='results', lazy=True)
    test = db.relationship('Test', backref='results', lazy=True)

    def __repr__(self):
        return f'<Result {self.student_id} - {self.test_id}>'

class Achievement(db.Model):
    __tablename__ = 'achievements'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    icon = db.Column(db.String(50), default="")
    xp_reward = db.Column(db.Integer, default=50)
    condition_type = db.Column(db.String(50))
    condition_value = db.Column(db.Integer, default=1)

    def __repr__(self):
        return f'<Achievement {self.name}>'

class StudentAchievement(db.Model):
    __tablename__ = 'student_achievements'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    achievement_id = db.Column(db.Integer, db.ForeignKey('achievements.id'), nullable=False)
    unlocked_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    student = db.relationship('Student', backref='unlocked_achievements', lazy=True)
    achievement = db.relationship('Achievement', backref='unlockers', lazy=True)

    def __repr__(self):
        return f'<StudentAchievement {self.student_id} - {self.achievement_id}>'

class Schedule(db.Model):
    __tablename__ = 'schedules'
    id = db.Column(db.Integer, primary_key=True)
    day_of_week = db.Column(db.String(20), nullable=False)
    start_time = db.Column(db.String(5), nullable=False)
    end_time = db.Column(db.String(5), nullable=False)
    room_number = db.Column(db.String(10))
    
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    class_id = db.Column(db.Integer, db.ForeignKey('classes.id'), nullable=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    
    subject = db.relationship('Subject', backref='schedule_items', lazy=True)
    teacher = db.relationship('Teacher', backref='schedule_items', lazy=True, overlaps="schedule_teacher,schedules") 

    def __repr__(self):
        return f'<Schedule {self.day_of_week} {self.start_time}>'

class Book(db.Model):
    __tablename__ = 'books'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(100), nullable=False)
    genre = db.Column(db.String(50))
    description = db.Column(db.Text)
    cover_url = db.Column(db.String(200))
    file_url = db.Column(db.String(200))
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<Book {self.title}>'

class News(db.Model):
    __tablename__ = 'news'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500))
    is_announcement = db.Column(db.Boolean, default=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<News {self.title}>'

class Club(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    max_students = db.Column(db.Integer, default=20)
    schedule = db.Column(db.String(100)) # Masalan: "Dushanba, 15:00"
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    
    # Munosabatlar
    teacher = db.relationship('Teacher', backref=db.backref('clubs', lazy=True))

class StudentClub(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    club_id = db.Column(db.Integer, db.ForeignKey('club.id'), nullable=False)
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    student = db.relationship('Student', backref=db.backref('club_memberships', lazy=True))
    club = db.relationship('Club', backref=db.backref('members', lazy=True))

class ChatMessage(db.Model):
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    sender_type = db.Column(db.String(20), nullable=False)
    sender_id = db.Column(db.Integer, nullable=False)
    recipient_type = db.Column(db.String(20), nullable=False)
    recipient_id = db.Column(db.Integer, nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    school = db.relationship('School', backref=db.backref('chat_messages', lazy=True))

class Presentation(db.Model):
    __tablename__ = 'presentations'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    file_url = db.Column(db.String(500), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id'), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    school = db.relationship('School', backref=db.backref('presentations', lazy=True))
    teacher = db.relationship('Teacher', backref=db.backref('presentations', lazy=True))
