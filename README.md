# 🏫 Maktab Portal (School Management System)

Zamonaviy, ko‘p maktabli va xavfsiz veb-platforma. O‘quvchilar, o‘qituvchilar va maktab ma’muriyati uchun yagona boshqaruv tizimi.

## ✨ Xususiyatlari
- **Multi-School:** Har bir maktab alohida ma'lumotlar bazasiga ega (Data Isolation).
- **Role-Based Access:** Admin, Teacher va Student rollari.
- **Test Tizimi:** Avtomatik tekshiriladigan testlar va mavzu bo'yicha tahlil.
- **Gamification:** XP, Level va Yutuqlar tizimi.
- **Dars Jadvali:** Interaktiv haftalik jadval.
- **Kutubxona & Yangiliklar:** Elektron resurslar va e'lonlar.
- **Xavfsizlik:** CSRF himoyasi, Session Timeout, Input Sanitization.
- **Responsive:** Mobil va desktop qurilmalarda mukammal ishlaydi.

## 🛠 Texnologiyalar
- **Backend:** Python 3.12, Flask 3.0
- **Database:** SQLite (SQLAlchemy ORM)
- **Frontend:** HTML5, CSS3, Vanilla JS, Chart.js
- **Security:** Flask-WTF (CSRF), Flask-Limiter, Bleach
- **Deployment:** Gunicorn, Nginx, Systemd

## ⚙️ O'rnatish (Ubuntu/Linux)

### 1. Talablarni o'rnatish
```bash
sudo apt update
sudo apt install python3-pip python3-venv git sqlite3