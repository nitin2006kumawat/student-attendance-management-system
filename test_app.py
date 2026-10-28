import csv
import io
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as A
from werkzeug.security import check_password_hash, generate_password_hash


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        A.app.config.update(DATABASE=self.path, TESTING=True)
        A.init_db()
        db = sqlite3.connect(self.path)
        db.execute(
            "INSERT INTO admins(username,password_hash) VALUES(?,?)",
            ("teacher", generate_password_hash("secure-test-password")),
        )
        db.commit()
        db.close()
        self.c = A.app.test_client()
        with self.c.session_transaction() as session:
            session["admin_id"] = 1
            session["username"] = "teacher"
            session["csrf_token"] = "test-token"
        self.headers = {"X-CSRFToken": "test-token"}
        self.add_student()
        self.c.post("/api/subjects", json={"name": "Maths", "code": "M1"}, headers=self.headers)
        self.c.post("/api/subjects", json={"name": "Physics", "code": "P1"}, headers=self.headers)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def add_student(self, student_id="S1", roll_no="1", **fields):
        data = {
            "student_id": student_id, "roll_no": roll_no, "name": "Test One",
            "course": "BCA", "section": "A", "semester": "6",
        }
        data.update(fields)
        return self.c.post("/api/students", json=data, headers=self.headers)

    def mark(self, day, status, subject=1, student=1):
        return self.c.post(
            "/api/attendance",
            json={"student_id": student, "subject_id": subject, "date": day, "status": status},
            headers=self.headers,
        )

    def test_eight_present_two_absent_is_80_percent(self):
        for i in range(10):
            self.mark(f"2026-03-{i+1:02d}", "Present" if i < 8 else "Absent")
        self.assertEqual(self.c.get("/api/analytics").json["overall"], 80.0)
        self.assertEqual(A.calc_percent(8, 2), 80.0)

    def test_leave_is_excluded_from_default_denominator(self):
        for i, status in enumerate(["Present"] * 8 + ["Leave"] * 2):
            self.mark(f"2026-03-{i+1:02d}", status)
        self.assertEqual(self.c.get("/api/analytics").json["overall"], 100.0)
        response = self.c.put(
            "/api/settings", json={"threshold": 75, "leave_mode": "absent"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.c.get("/api/analytics").json["overall"], 80.0)
        response = self.c.put(
            "/api/settings", json={"threshold": 75, "leave_mode": "present"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.c.get("/api/analytics").json["overall"], 100.0)

    def test_duplicate_attendance_is_rejected(self):
        self.assertEqual(self.mark("2026-03-01", "Present").status_code, 201)
        self.assertEqual(self.mark("2026-03-01", "Absent").status_code, 409)

    def test_attendance_can_be_edited(self):
        created = self.mark("2026-03-01", "Absent")
        response = self.c.put(
            f"/api/attendance/{created.json['id']}",
            json={"student_id": 1, "subject_id": 1, "date": "2026-03-01", "status": "Present"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.c.get("/api/attendance").json[0]["status"], "Present")

    def test_student_with_60_percent_is_below_75_threshold(self):
        for i in range(10):
            self.mark(f"2026-03-{i+1:02d}", "Present" if i < 6 else "Absent")
        data = self.c.get("/api/analytics?threshold=75").json
        self.assertEqual([s["name"] for s in data["below"]], ["Test One"])
        self.assertEqual(data["below"][0]["percentage"], 60.0)

    def test_subject_filter_limits_records_and_analytics(self):
        self.mark("2026-03-01", "Present", subject=1)
        self.mark("2026-03-01", "Absent", subject=2)
        self.assertEqual(len(self.c.get("/api/attendance?subject=2").json), 1)
        data = self.c.get("/api/analytics?subject=2").json
        self.assertEqual((data["records"], data["overall"]), (1, 0.0))

    def test_invalid_or_blank_status_is_rejected(self):
        for status in ("", "Maybe", None):
            response = self.mark("2026-03-02", status)
            self.assertEqual(response.status_code, 400)
            self.assertIn("Status", response.json["error"])

    def test_student_creation_and_editing(self):
        created = self.add_student(
            "S2", "2", name="Second Student", semester="4", email="student@example.edu"
        )
        self.assertEqual(created.status_code, 201)
        student_id = created.json["id"]
        response = self.c.put(
            f"/api/students/{student_id}",
            json={
                "student_id": "S2", "roll_no": "22", "name": "Updated Student",
                "course": "BCA", "section": "B", "semester": "5", "email": "",
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        student = self.c.get("/api/students").json[1]
        self.assertEqual((student["roll_no"], student["section"], student["semester"]), ("22", "B", "5"))
        self.assertEqual(student["email"], "")

    def test_csv_export_applies_filters(self):
        self.mark("2026-03-01", "Present", subject=1)
        self.mark("2026-03-02", "Absent", subject=2)
        response = self.c.get("/export/attendance.csv?subject=2")
        self.assertEqual(response.status_code, 200)
        rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][0], "2026-03-02")
        self.assertEqual(rows[1][6], "Physics")

    def test_csv_escapes_spreadsheet_formulas(self):
        created = self.add_student("=SUM(1,1)", "2")
        self.assertEqual(created.status_code, 201)
        self.mark("2026-03-01", "Present", student=2)
        response = self.c.get("/export/attendance.csv")
        self.assertIn("'=SUM(1,1)", response.get_data(as_text=True))

    def test_unauthorized_requests_are_denied(self):
        client = A.app.test_client()
        response = client.get("/api/analytics")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(client.get("/").status_code, 302)

    def test_csrf_is_required_for_changes(self):
        response = self.c.post(
            "/api/subjects", json={"name": "History"}, headers={"X-CSRFToken": "invalid"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("CSRF", response.json["error"])

    def test_empty_analytics_does_not_crash(self):
        db = sqlite3.connect(self.path)
        db.execute("DELETE FROM attendance")
        db.commit()
        db.close()
        response = self.c.get("/api/analytics")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["records"], 0)
        self.assertEqual(response.json["overall"], 0.0)
        self.assertEqual(response.json["students"], [])
        self.assertEqual(response.json["trend"], [])

    def test_bulk_attendance_creates_and_updates_class_records(self):
        self.add_student("S2", "2")
        self.mark("2026-03-01", "Absent", subject=1, student=1)
        response = self.c.post(
            "/api/attendance/bulk",
            json={
                "course": "BCA", "section": "A", "subject_id": 1,
                "date": "2026-03-01", "status": "Present",
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"total": 2, "created": 1, "updated": 1})
        records = self.c.get("/api/attendance?subject=1").json
        self.assertEqual([r["status"] for r in records], ["Present", "Present"])

    def test_duplicate_student_and_subject_names_are_rejected(self):
        self.assertEqual(self.add_student("S1", "9").status_code, 409)
        response = self.c.post(
            "/api/subjects", json={"name": "maths"}, headers=self.headers
        )
        self.assertEqual(response.status_code, 409)

    def test_subject_crud_and_delete_cascade(self):
        created = self.c.post(
            "/api/subjects", json={"name": "History", "code": "H1"}, headers=self.headers
        )
        self.assertEqual(created.status_code, 201)
        subject_id = created.json["id"]
        response = self.c.put(
            f"/api/subjects/{subject_id}",
            json={"name": "Modern History", "code": "H2"},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.mark("2026-03-01", "Present", subject=subject_id)
        response = self.c.delete(f"/api/subjects/{subject_id}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.c.get("/api/attendance").json, [])

    def test_student_delete_cascades_attendance(self):
        self.mark("2026-03-01", "Present")
        response = self.c.delete("/api/students/1", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.c.get("/api/attendance").json, [])

    def test_demo_loader_never_replaces_existing_records(self):
        response = self.c.post(
            "/api/seed", json={"reset": True}, headers=self.headers
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.c.get("/api/students").json), 1)
        self.assertEqual(len(self.c.get("/api/subjects").json), 2)

    def test_setup_creates_hashed_admin_and_redirects_outside_loopback(self):
        db = sqlite3.connect(self.path)
        db.execute("DELETE FROM admins")
        db.commit()
        db.close()
        client = A.app.test_client()
        remote = client.get("/setup", environ_base={"REMOTE_ADDR": "192.0.2.10"})
        self.assertEqual(remote.status_code, 403)
        page = client.get("/setup")
        self.assertEqual(page.status_code, 200)
        token = page.get_data(as_text=True).split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
        response = client.post(
            "/setup",
            data={"csrf_token": token, "username": "newadmin", "password": "long-secure-test-password"},
        )
        self.assertEqual(response.status_code, 302)
        db = sqlite3.connect(self.path)
        password_hash = db.execute("SELECT password_hash FROM admins WHERE username='newadmin'").fetchone()[0]
        db.close()
        self.assertTrue(check_password_hash(password_hash, "long-secure-test-password"))

    def test_application_pages_render_and_login_works(self):
        for path in ("/", "/students", "/attendance", "/subjects", "/analytics", "/reports", "/settings"):
            self.assertEqual(self.c.get(path).status_code, 200, path)
        client = A.app.test_client()
        page = client.get("/login")
        self.assertEqual(page.status_code, 200)
        token = page.get_data(as_text=True).split('name="csrf_token" value="', 1)[1].split('"', 1)[0]
        response = client.post(
            "/login",
            data={"csrf_token": token, "username": "teacher", "password": "secure-test-password"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(client.get("/").status_code, 200)

    def test_invalid_attendance_date_and_foreign_keys_are_rejected(self):
        for student_id, subject_id, day in ((1, 1, "2026-02-30"), (999, 1, "2026-03-01"), (1, 999, "2026-03-01")):
            response = self.c.post(
                "/api/attendance",
                json={"student_id": student_id, "subject_id": subject_id, "date": day, "status": "Present"},
                headers=self.headers,
            )
            self.assertEqual(response.status_code, 400)

    def test_schema_upgrade_preserves_existing_database_records(self):
        legacy = self.path + ".legacy"
        db = sqlite3.connect(legacy)
        db.executescript("""
            CREATE TABLE students(id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL UNIQUE,
                roll_no TEXT NOT NULL UNIQUE, name TEXT NOT NULL, course TEXT NOT NULL, section TEXT NOT NULL);
            CREATE TABLE subjects(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                code TEXT NOT NULL DEFAULT '');
            CREATE TABLE attendance(id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
                date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('Present','Absent','Leave')),
                UNIQUE(student_id, subject_id, date));
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO students(student_id,roll_no,name,course,section) VALUES('KEEP','1','Keep Me','BCA','A');
            INSERT INTO subjects(name,code) VALUES('Kept Subject','K1');
            INSERT INTO attendance(student_id,subject_id,date,status) VALUES(1,1,'2026-03-01','Present');
            INSERT INTO settings VALUES('threshold','80');
        """)
        db.commit()
        db.close()
        A.app.config["DATABASE"] = legacy
        try:
            A.init_db()
            db = sqlite3.connect(legacy)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM attendance").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='threshold'").fetchone()[0], "80")
            columns = {row[1] for row in db.execute("PRAGMA table_info(students)")}
            self.assertTrue({"semester", "email"}.issubset(columns))
            db.close()
        finally:
            A.app.config["DATABASE"] = self.path
            os.remove(legacy)


if __name__ == "__main__":
    unittest.main()
