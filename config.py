import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'default-secret-key-change-in-production'
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = DATABASE_URL or ('sqlite:////tmp/school.db' if os.environ.get('VERCEL') else 'sqlite:///school.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session Security
    PERMANENT_SESSION_LIFETIME = 1800  # 30 daqiqa (soniyalarda)
    SESSION_COOKIE_HTTPONLY = True     # JavaScript session cookie'ga kira olmaydi
    SESSION_COOKIE_SECURE = False      # HTTPS bo'lmaganda False (localhost uchun)
    SESSION_COOKIE_SAMESITE = 'Lax'    # CSRF himoyasi uchun
    
    # WTF Forms (CSRF uchun)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600         # Token 1 soat amal qiladi
