# Student Attendance Management System

A beginner-friendly BCA final-year project for managing students, subjects, daily attendance, analytics, and printable/CSV reports. It runs locally with Flask and SQLite and does not require paid services.

## Features

- Admin sign-in, a first-run administrator setup page, password hashing, session cookies, and CSRF protection.
- Student and subject add, view, edit, search/filter, and delete operations. Student fields include student ID, roll number, name, course, section, semester, and optional email.
- Individual attendance entry/editing and bulk class marking for Present, Absent, or Leave.
- Database-enforced unique attendance per student, subject, and date. Bulk marking updates an existing entry for that class/date instead of creating duplicates.
- Dashboard and analytics backed by SQLite data, with student, subject, course, section, and date filters.
- Student-wise attendance summaries, below-threshold lists, subject comparisons, attendance trends, recent activity, filtered CSV export, and a print-friendly report.
- Configurable attendance threshold (default 75%) and Leave handling.
- Demo data for an empty database only. It refuses to overwrite existing records.

**Default attendance formula:** `Present / (Present + Absent) × 100`. Leave is excluded. Zero counted sessions produce 0% without a divide-by-zero error. The optional settings for counting Leave as Present or Absent are also reflected in all calculations.

## Technologies

- Python 3.10+ and Flask
- SQLite (Python standard library)
- Pandas for attendance grouping and summary calculations
- NumPy is installed as Pandas' dependency
- HTML, CSS, JavaScript, and Chart.js

## Folder structure

```text
student_attendance_system/
├── app.py
├── database/
│   └── attendance.db
├── static/
│   ├── css/style.css
│   └── js/app.js
├── templates/
│   ├── auth.html
│   ├── base.html
│   └── ...application pages
├── tests/
│   └── test_app.py
├── requirements.txt
├── README.md
└── PROJECT_SUBMISSION_GUIDE.md
```

## Database design

The application creates `database/attendance.db` on first launch and upgrades the existing schema in place. The migration adds student semester/email fields and the administrators table without deleting existing student, subject, attendance, or settings rows.

- `students`: numeric primary key, unique student ID, unique roll number, name, course, section, semester, optional email.
- `subjects`: numeric primary key, case-insensitive unique subject name, optional code.
- `attendance`: student and subject foreign keys, ISO date, checked status, and a unique `(student_id, subject_id, date)` constraint. Deleting a student or subject cascades to its related attendance.
- `settings`: attendance threshold and Leave handling mode.
- `admins`: unique username and Werkzeug-generated password hash; plaintext passwords are never stored.

## Windows 11 installation and run

Open PowerShell in this project folder. If the existing `venv` is present, reuse it; do not delete it.

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
python app.py
```

If PowerShell blocks activation, either run `Set-ExecutionPolicy -Scope Process Bypass` for that terminal or invoke `.\venv\Scripts\python.exe` directly. Python must be on PATH if using the `python` command.

Open <http://127.0.0.1:5000>. On the first run, create the administrator in the setup page using a username of at least 3 characters and a password of at least 12 characters. The setup page only accepts requests from the local computer. Choose a password you can retain: password recovery is not configured.

Set `FLASK_SECRET_KEY` to a persistent, randomly generated value before starting the server so sessions remain valid across restarts. The application generates a temporary random key if this variable is omitted; sessions then expire when the process restarts. Never put a real secret into source control.

The app binds to `127.0.0.1` with Flask debug mode disabled. Do not expose this development application directly to a public network.

## Charts and offline use

Flask, SQLite, CRUD, attendance calculations, and CSV export work locally. Chart.js is loaded from jsDelivr in `templates/base.html`, so charts require an internet connection. This project does not currently bundle Chart.js locally; if the CDN is unavailable, the rest of the application remains local but the charts cannot render.

## Sample data

Use **Settings → Load demo data** only when students, subjects, and attendance tables are empty. It creates fictional data (12 students, 5 subjects, and 1,200 attendance records). It will never clear or replace existing records.

## Tests

Run the suite against temporary SQLite databases (the real `database/attendance.db` is not used by tests):

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests cover the attendance formula and Leave handling, duplicate prevention, below-threshold reporting, subject filtering, status validation, student create/edit, filtered CSV export, bulk class marking, setup/password hashing, authentication/CSRF, and empty analytics.

## Troubleshooting

- **Cannot sign in:** check the username/password. There is no password-recovery route; preserve the administrator password securely.
- **Initial setup page does not load:** open the application from the same computer at `127.0.0.1`; setup intentionally rejects remote clients.
- **Signed out after a restart:** configure a persistent `FLASK_SECRET_KEY` in the same PowerShell session before running `python app.py`.
- **Charts are blank:** check the internet connection/CDN access. The rest of the app does not depend on the CDN.
- **Demo data refused:** the action is intentionally limited to an empty database to protect existing records.
- **Port 5000 is already in use:** stop the other local Flask process or change the `app.run` port in `app.py` for your local demo.

## Submission material

See [PROJECT_SUBMISSION_GUIDE.md](./PROJECT_SUBMISSION_GUIDE.md) for objectives, architecture, schema, algorithms, test results, screenshot suggestions, and viva questions.
