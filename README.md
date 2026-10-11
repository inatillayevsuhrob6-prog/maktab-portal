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

### Maxfiy sozlamalar
Ishga tushirishdan oldin `.env` ichida `SECRET_KEY` uchun tasodifiy, maxfiy qiymat belgilang. Uni yaratish uchun `python -c "import secrets; print(secrets.token_hex(32))"` buyrug‘idan foydalaning; qiymatni GitHub'ga joylamang. HTTPS hostingda `SESSION_COOKIE_SECURE=True` bo‘lsin; faqat HTTP'dagi lokal sinov uchun uni vaqtincha `False` qiling. Ilova kirish kaliti belgilanmagan bo‘lsa ishga tushmaydi.

Ommaviy bosh sahifa va ro‘yxatdan o‘tish ochiq qoladi. Ilovaning ichki sahifalari login talab qiladi. Brauzerda ishlashi uchun HTML/CSS/JavaScript foydalanuvchiga yuboriladi; serverdagi Python kod va maxfiy kalitlar esa `static` papkaga qo‘yilmasligi va repozitoriy maxfiy saqlanishi kerak.

### 1. Talablarni o'rnatish
```bash
sudo apt update
sudo apt install python3-pip python3-venv git sqlite3
