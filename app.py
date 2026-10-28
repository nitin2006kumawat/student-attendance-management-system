"""Student Attendance Management System - Flask backend."""
import csv, io, json, math, os, random, secrets, sqlite3
from datetime import date, timedelta
from werkzeug.security import check_password_hash, generate_password_hash
import pandas as pd
from flask import Flask, Response, g, jsonify, redirect, render_template, request, session, url_for

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)
app.config["DATABASE"] = os.path.join(BASE, "database", "attendance.db")
STATUSES = ("Present", "Absent", "Leave")
LEAVE_MODES = ("exclude", "present", "absent")

SCHEMA = """
CREATE TABLE IF NOT EXISTS students(
  id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL UNIQUE,
  roll_no TEXT NOT NULL UNIQUE, name TEXT NOT NULL, course TEXT NOT NULL, section TEXT NOT NULL,
  semester TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS subjects(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE, code TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS attendance(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('Present','Absent','Leave')),
  UNIQUE(student_id, subject_id, date));
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS admins(
  id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  password_hash TEXT NOT NULL);
"""

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    db = sqlite3.connect(app.config["DATABASE"])
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    student_columns = {r[1] for r in db.execute("PRAGMA table_info(students)")}
    if "semester" not in student_columns:
        db.execute("ALTER TABLE students ADD COLUMN semester TEXT NOT NULL DEFAULT ''")
    if "email" not in student_columns:
        db.execute("ALTER TABLE students ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    db.executemany("INSERT OR IGNORE INTO settings VALUES(?,?)", [("threshold", "75"), ("leave_mode", "exclude")])
    db.commit(); db.close()

def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]

@app.context_processor
def inject_template_values():
    return {"csrf_token": csrf_token, "admin_username": session.get("username", "")}

@app.before_request
def protect_routes():
    endpoint = request.endpoint or ""
    is_data_endpoint = request.path.startswith("/api/") or request.path.startswith("/export/")
    if endpoint == "static":
        return None
    expected = session.get("csrf_token", "")
    supplied = request.headers.get("X-CSRFToken") or request.form.get("csrf_token", "")
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and (
        not expected or not secrets.compare_digest(expected, supplied)
    ):
        return err("Invalid or expired CSRF token. Refresh the page and try again.", 400)
    if endpoint in ("login", "setup"):
        return None
    if not get_db().execute("SELECT 1 FROM admins LIMIT 1").fetchone():
        if is_data_endpoint:
            return err("Initial administrator setup is required.", 503)
        return redirect(url_for("setup"))
    if not session.get("admin_id"):
        if is_data_endpoint:
            return err("Please sign in to continue.", 401)
        return redirect(url_for("login", next=request.full_path))
    return None

def err(msg, code=400):
    return jsonify(error=msg), code

def rows(sql, p=()):
    return [dict(r) for r in get_db().execute(sql, p).fetchall()]

def json_data():
    value = request.get_json(silent=True)
    return value if isinstance(value, dict) else {}

def get_settings():
    s = {r["key"]: r["value"] for r in get_db().execute("SELECT * FROM settings")}
    return float(s.get("threshold", 75)), s.get("leave_mode", "exclude")

def calc_percent(present, absent, leave=0, mode="exclude"):
    """Default: Present / (Present + Absent) * 100. Leave is excluded unless configured."""
    if mode == "present":
        num, den = present + leave, present + absent + leave
    elif mode == "absent":
        num, den = present, present + absent + leave
    else:
        num, den = present, present + absent
    return round(100 * num / den, 1) if den else 0.0

# ---------------- authentication ----------------
def is_loopback():
    return request.remote_addr in ("127.0.0.1", "::1")

@app.route("/setup", methods=["GET", "POST"])
def setup():
    if not is_loopback():
        return "Initial setup is available only from this computer.", 403
    if get_db().execute("SELECT 1 FROM admins LIMIT 1").fetchone():
        return redirect(url_for("login"))
    error = ""
    if request.method == "POST":
        username = str(request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if len(username) < 3:
            error = "Username must contain at least 3 characters."
        elif len(password) < 12:
            error = "Password must contain at least 12 characters."
        else:
            cur = get_db().execute(
                "INSERT INTO admins(username,password_hash) VALUES(?,?)",
                (username, generate_password_hash(password)),
            )
            get_db().commit()
            session.clear()
            session["admin_id"] = cur.lastrowid
            session["username"] = username
            csrf_token()
            session.permanent = True
            return redirect(url_for("page_index"))
    return render_template("auth.html", mode="setup", error=error)

@app.route("/login", methods=["GET", "POST"])
def login():
    if not get_db().execute("SELECT 1 FROM admins LIMIT 1").fetchone():
        return redirect(url_for("setup"))
    if session.get("admin_id"):
        return redirect(url_for("page_index"))
    error = ""
    if request.method == "POST":
        username = str(request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        admin = get_db().execute(
            "SELECT id, username, password_hash FROM admins WHERE username=? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if not admin or not check_password_hash(admin["password_hash"], password):
            error = "Invalid username or password."
        else:
            session.clear()
            session["admin_id"] = admin["id"]
            session["username"] = admin["username"]
            csrf_token()
            session.permanent = True
            destination = request.args.get("next", "")
            if not destination.startswith("/") or destination.startswith("//") or "\\" in destination:
                destination = url_for("page_index")
            return redirect(destination)
    return render_template("auth.html", mode="login", error=error)

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- pages ----------------
PAGES = {"index": "/", "students": "/students", "attendance": "/attendance", "subjects": "/subjects",
         "analytics": "/analytics", "reports": "/reports", "settings": "/settings"}
def _page(name):
    return lambda: render_template(f"{name}.html", active=name)
for _n, _u in PAGES.items():
    app.add_url_rule(_u, "page_" + _n, _page(_n))

# ---------------- students ----------------
def clean_student(d):
    v = {k: str(d.get(k) or "").strip() for k in
         ("student_id", "roll_no", "name", "course", "section", "semester")}
    v["email"] = str(d.get("email") or "").strip()
    missing = [k.replace("_", " ") for k, x in v.items() if k != "email" and not x]
    if missing:
        return None, "Required: " + ", ".join(missing)
    if len(v["name"]) < 2:
        return None, "Name is too short"
    if v["email"] and ("@" not in v["email"] or v["email"].startswith("@") or v["email"].endswith("@")):
        return None, "Enter a valid email address"
    return v, None

def student_write(sql, vals):
    try:
        cur = get_db().execute(sql, vals); get_db().commit(); return cur, None
    except sqlite3.IntegrityError as e:
        return None, ("Student ID already exists" if "student_id" in str(e) else "Roll number already exists")

@app.get("/api/meta")
def meta():
    return jsonify(courses=[r["course"] for r in rows("SELECT DISTINCT course FROM students ORDER BY 1")],
                   sections=[r["section"] for r in rows("SELECT DISTINCT section FROM students ORDER BY 1")])

@app.get("/api/students")
def list_students():
    sql, p = "SELECT * FROM students WHERE 1=1", []
    q = request.args.get("q", "").strip()
    if q:
        sql += " AND (name LIKE ? OR student_id LIKE ? OR roll_no LIKE ?)"; p += [f"%{q}%"] * 3
    for k in ("course", "section"):
        if request.args.get(k):
            sql += f" AND {k}=?"; p.append(request.args[k])
    return jsonify(rows(sql + " ORDER BY roll_no", p))

@app.get("/api/students/<int:sid>")
def student_detail(sid):
    st = rows("SELECT * FROM students WHERE id=?", (sid,))
    if not st:
        return err("Student not found", 404)
    _, mode = get_settings()
    df = load_df({"student": sid})
    overall = group_pct(df.assign(all="Overall"), ["all"], mode)
    return jsonify(student=st[0], subjects=group_pct(df, ["subid", "subject"], mode),
                   overall=overall[0]["percentage"] if overall else 0)

@app.post("/api/students")
def add_student():
    v, e = clean_student(json_data())
    if e: return err(e)
    cur, e = student_write("INSERT INTO students(student_id,roll_no,name,course,section,semester,email) VALUES(?,?,?,?,?,?,?)", tuple(v.values()))
    return err(e, 409) if e else (jsonify(id=cur.lastrowid), 201)

@app.put("/api/students/<int:sid>")
def edit_student(sid):
    v, e = clean_student(json_data())
    if e: return err(e)
    cur, e = student_write("UPDATE students SET student_id=?,roll_no=?,name=?,course=?,section=?,semester=?,email=? WHERE id=?", (*v.values(), sid))
    if e: return err(e, 409)
    return jsonify(ok=True) if cur.rowcount else err("Student not found", 404)

@app.delete("/api/students/<int:sid>")
def del_student(sid):
    cur = get_db().execute("DELETE FROM students WHERE id=?", (sid,)); get_db().commit()
    return jsonify(ok=True) if cur.rowcount else err("Student not found", 404)

# ---------------- subjects ----------------
def subject_write(sql, vals):
    d = json_data()
    name, code = str(d.get("name") or "").strip(), str(d.get("code") or "").strip()
    if not name: return err("Subject name is required")
    try:
        cur = get_db().execute(sql, (name, code, *vals)); get_db().commit()
    except sqlite3.IntegrityError:
        return err("Subject already exists", 409)
    return cur

@app.get("/api/subjects")
def list_subjects():
    return jsonify(rows("SELECT s.*, (SELECT COUNT(*) FROM attendance a WHERE a.subject_id=s.id) records FROM subjects s ORDER BY name"))

@app.post("/api/subjects")
def add_subject():
    r = subject_write("INSERT INTO subjects(name,code) VALUES(?,?)", ())
    return r if isinstance(r, tuple) else (jsonify(id=r.lastrowid), 201)

@app.put("/api/subjects/<int:sid>")
def edit_subject(sid):
    r = subject_write("UPDATE subjects SET name=?,code=? WHERE id=?", (sid,))
    if isinstance(r, tuple): return r
    return jsonify(ok=True) if r.rowcount else err("Subject not found", 404)

@app.delete("/api/subjects/<int:sid>")
def del_subject(sid):
    cur = get_db().execute("DELETE FROM subjects WHERE id=?", (sid,)); get_db().commit()
    return jsonify(ok=True) if cur.rowcount else err("Subject not found", 404)

# ---------------- attendance ----------------
def load_df(args):
    sql = ("SELECT a.id, a.date, a.status, s.id sid, s.student_id, s.roll_no, s.name, s.course, s.section, "
           "j.id subid, j.name subject FROM attendance a JOIN students s ON s.id=a.student_id "
           "JOIN subjects j ON j.id=a.subject_id WHERE 1=1")
    p = []
    for key, col in (("student", "s.id"), ("subject", "j.id"), ("course", "s.course"), ("section", "s.section"), ("status", "a.status")):
        if args.get(key):
            sql += f" AND {col}=?"; p.append(args[key])
    if args.get("start"): sql += " AND a.date>=?"; p.append(args["start"])
    if args.get("end"): sql += " AND a.date<=?"; p.append(args["end"])
    return pd.read_sql_query(sql + " ORDER BY a.date DESC, a.id DESC", get_db(), params=p)

def validate_filters(args):
    for key in ("student", "subject"):
        if args.get(key):
            try:
                if int(args[key]) < 1:
                    raise ValueError
            except (TypeError, ValueError):
                return err(f"{key.title()} filter must be a positive ID")
    if args.get("status") and args["status"] not in STATUSES:
        return err("Status filter must be Present, Absent or Leave")
    try:
        start = date.fromisoformat(args["start"]) if args.get("start") else None
        end = date.fromisoformat(args["end"]) if args.get("end") else None
    except (TypeError, ValueError):
        return err("Date filters must use YYYY-MM-DD format")
    if start and end and start > end:
        return err("Start date must be on or before end date")
    return None

def count_students_in_scope(args):
    sql, params = "SELECT COUNT(*) FROM students WHERE 1=1", []
    for key in ("student", "course", "section"):
        if args.get(key):
            column = "id" if key == "student" else key
            sql += f" AND {column}=?"
            params.append(args[key])
    return get_db().execute(sql, params).fetchone()[0]

def group_pct(df, keys, mode):
    if df.empty: return []
    c = df.pivot_table(index=keys, columns="status", values="id", aggfunc="count", fill_value=0)
    c = c.reindex(columns=list(STATUSES), fill_value=0).reset_index()
    c["percentage"] = [calc_percent(r.Present, r.Absent, r.Leave, mode) for r in c.itertuples()]
    return json.loads(c.to_json(orient="records"))

def clean_att(d):
    sid, subid = positive_id(d.get("student_id")), positive_id(d.get("subject_id"))
    if sid is None or subid is None:
        return None, "Student and subject are required"
    try:
        day = date.fromisoformat(str(d.get("date") or ""))
    except ValueError:
        return None, "A valid date is required"
    if str(d.get("status") or "") not in STATUSES:
        return None, "Status must be Present, Absent or Leave"
    return (sid, subid, day.isoformat(), d["status"]), None

def positive_id(value):
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    if result < 1 or str(value).strip() != str(result):
        return None
    return result

@app.get("/api/attendance")
def list_att():
    invalid = validate_filters(request.args)
    if invalid: return invalid
    df = load_df(request.args)
    q = request.args.get("q", "").strip().lower()
    if q and not df.empty:
        df = df[df.name.str.lower().str.contains(q, regex=False) | df.student_id.str.lower().str.contains(q, regex=False)]
    return Response(df.to_json(orient="records"), mimetype="application/json")

def att_write(sql, extra=()):
    v, e = clean_att(json_data())
    if e: return err(e)
    try:
        cur = get_db().execute(sql, (*v, *extra)); get_db().commit(); return cur
    except sqlite3.IntegrityError as ex:
        if "UNIQUE" in str(ex):
            return err("Attendance already recorded for this student, subject and date", 409)
        return err("Selected student or subject does not exist", 400)

@app.post("/api/attendance")
def add_att():
    r = att_write("INSERT INTO attendance(student_id,subject_id,date,status) VALUES(?,?,?,?)")
    return r if isinstance(r, tuple) else (jsonify(id=r.lastrowid), 201)

@app.put("/api/attendance/<int:aid>")
def edit_att(aid):
    r = att_write("UPDATE attendance SET student_id=?,subject_id=?,date=?,status=? WHERE id=?", (aid,))
    if isinstance(r, tuple): return r
    return jsonify(ok=True) if r.rowcount else err("Record not found", 404)

@app.delete("/api/attendance/<int:aid>")
def del_att(aid):
    cur = get_db().execute("DELETE FROM attendance WHERE id=?", (aid,)); get_db().commit()
    return jsonify(ok=True) if cur.rowcount else err("Record not found", 404)

@app.post("/api/attendance/bulk")
def bulk_attendance():
    d = json_data()
    course, section = str(d.get("course") or "").strip(), str(d.get("section") or "").strip()
    subject_id = positive_id(d.get("subject_id"))
    try:
        day = date.fromisoformat(str(d.get("date") or "")).isoformat()
    except (TypeError, ValueError):
        return err("A valid subject and date are required")
    if subject_id is None:
        return err("A valid subject and date are required")
    status = str(d.get("status") or "")
    if not course or not section:
        return err("Course and section are required")
    if status not in STATUSES:
        return err("Status must be Present, Absent or Leave")
    if not get_db().execute("SELECT 1 FROM subjects WHERE id=?", (subject_id,)).fetchone():
        return err("Selected subject does not exist")
    students = [r["id"] for r in get_db().execute(
        "SELECT id FROM students WHERE course=? AND section=?", (course, section)
    )]
    if not students:
        return err("No students found for this course and section", 404)
    db = get_db()
    existing = db.execute(
        "SELECT COUNT(*) FROM attendance a JOIN students s ON s.id=a.student_id "
        "WHERE s.course=? AND s.section=? AND a.subject_id=? AND a.date=?",
        (course, section, subject_id, day),
    ).fetchone()[0]
    try:
        db.executemany(
            "INSERT INTO attendance(student_id,subject_id,date,status) VALUES(?,?,?,?) "
            "ON CONFLICT(student_id,subject_id,date) DO UPDATE SET status=excluded.status",
            [(sid, subject_id, day, status) for sid in students],
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return err("Could not save bulk attendance; verify the selected class and subject.", 400)
    return jsonify(total=len(students), created=len(students) - existing, updated=existing)

# ---------------- analytics / reports ----------------
@app.get("/api/analytics")
def analytics():
    invalid = validate_filters(request.args)
    if invalid: return invalid
    th, mode = get_settings()
    try:
        th = float(request.args.get("threshold", th))
    except ValueError:
        return err("Threshold must be a number")
    if not math.isfinite(th) or not 0 <= th <= 100:
        return err("Threshold must be a number between 0 and 100")
    df = load_df(request.args)
    students = group_pct(df, ["sid", "student_id", "name"], mode)
    n = {s: int((df.status == s).sum()) for s in STATUSES}
    overall = calc_percent(n["Present"], n["Absent"], n["Leave"], mode)
    return jsonify(
        threshold=th, leave_mode=mode, overall=overall, counts=n, records=len(df),
        total_students=count_students_in_scope(request.args),
        students=students, subjects=group_pct(df, ["subid", "subject"], mode),
        trend=sorted(group_pct(df, ["date"], mode), key=lambda r: r["date"]),
        below=sorted([s for s in students if s["percentage"] < th], key=lambda s: s["percentage"]),
        recent=json.loads(df.head(8).to_json(orient="records")))

@app.get("/export/attendance.csv")
def export_csv():
    invalid = validate_filters(request.args)
    if invalid: return invalid
    df = load_df(request.args)
    buf = io.StringIO(); w = csv.writer(buf)
    w.writerow(["Date", "Student ID", "Roll No", "Name", "Course", "Section", "Subject", "Status"])
    for r in df.itertuples():
        values = [r.date, r.student_id, r.roll_no, r.name, r.course, r.section, r.subject, r.status]
        w.writerow([csv_safe(value) for value in values])
    return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=attendance_report.csv"})

def csv_safe(value):
    text = str(value)
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + text
    return text

# ---------------- settings & demo data ----------------
@app.get("/api/settings")
def read_settings():
    th, mode = get_settings(); return jsonify(threshold=th, leave_mode=mode)

@app.put("/api/settings")
def write_settings():
    d = json_data()
    try:
        if isinstance(d.get("threshold"), bool):
            raise ValueError
        th = float(d.get("threshold"))
        if not math.isfinite(th) or not 0 <= th <= 100:
            raise ValueError
    except (TypeError, ValueError):
        return err("Threshold must be a number between 0 and 100")
    if d.get("leave_mode") not in LEAVE_MODES:
        return err("Invalid leave handling option")
    db = get_db()
    db.executemany("INSERT OR REPLACE INTO settings VALUES(?,?)", [("threshold", str(th)), ("leave_mode", d["leave_mode"])]); db.commit()
    return jsonify(ok=True)

NAMES = ["Aarav Mehta", "Diya Sharma", "Kabir Singh", "Ananya Iyer", "Rohan Verma", "Meera Nair", "Vihaan Gupta",
         "Isha Kapoor", "Arjun Reddy", "Saanvi Joshi", "Neil Fernandes", "Tara Bose"]
SUBJECTS = [("Python Programming", "BCA301"), ("Database Management", "BCA302"), ("Web Technologies", "BCA303"),
            ("Data Structures", "BCA304"), ("Computer Networks", "BCA305")]

@app.post("/api/seed")
def seed():
    db = get_db()
    if any(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("students", "subjects", "attendance")):
        return err("Demo data is only available in an empty database. Existing records will not be replaced.", 409)
    rnd = random.Random(42)
    try:
        db.execute("BEGIN")
        student_ids = []
        for i, nm in enumerate(NAMES, 1):
            cur = db.execute("INSERT INTO students(student_id,roll_no,name,course,section,semester) VALUES(?,?,?,?,?,?)",
                             (f"BCA2024{i:03d}", f"{i:02d}", nm, "BCA - Year 3", "A" if i <= 6 else "B", "6"))
            student_ids.append(cur.lastrowid)
        subject_ids = []
        for nm, code in SUBJECTS:
            subject_ids.append(db.execute("INSERT INTO subjects(name,code) VALUES(?,?)", (nm, code)).lastrowid)
        chance = [0.95, 0.9, 0.62, 0.85, 0.7, 0.93, 0.8, 0.58, 0.88, 0.76, 0.97, 0.66]
        days, d = [], date.today()
        while len(days) < 20:
            if d.weekday() < 5: days.append(d)
            d -= timedelta(days=1)
        recs = []
        for index, sid in enumerate(student_ids):
            for subid in subject_ids:
                for day in days:
                    x = rnd.random()
                    recs.append((sid, subid, day.isoformat(), "Present" if x < chance[index] else ("Leave" if x < chance[index] + 0.03 else "Absent")))
        db.executemany("INSERT INTO attendance(student_id,subject_id,date,status) VALUES(?,?,?,?)", recs)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return jsonify(students=len(NAMES), subjects=len(SUBJECTS), records=len(recs))

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", debug=False)
