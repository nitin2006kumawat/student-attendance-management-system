# BCA Project Submission Guide

## 1. Project objectives

- Replace scattered paper attendance registers with a local, searchable system.
- Maintain student and subject records and record attendance by subject and date.
- Prevent accidental duplicate records and validate data before it is saved.
- Calculate student and overall attendance consistently and identify students below a configurable threshold.
- Produce filtered summaries, CSV files, and print-friendly reports while preserving existing records.
- Protect administrative operations with login, hashed passwords, sessions, and CSRF checks.

## 2. Problem statement

Manual attendance registers make it difficult to find student records, calculate subject-wise percentages, detect attendance shortages early, and prepare accurate reports. This system provides a small-college solution that operates locally without a paid service.

## 3. System architecture

```text
Browser (HTML/CSS/JavaScript, Chart.js)
        │ HTTP requests, JSON, CSV
        ▼
Flask application (routes, validation, sessions, calculations)
        │ parameterized SQLite queries
        ▼
SQLite database (students, subjects, attendance, settings, admins)
        │
        └── Pandas groups attendance rows for analytics and reports
```

The application is intended for a local demonstration and binds to `127.0.0.1`. Chart.js is fetched from a CDN; application data and calculations are stored and processed locally.

## 4. Database design

| Table | Purpose | Important constraints |
|---|---|---|
| `students` | Student ID, roll number, name, course, section, semester, optional email | Unique student ID and roll number |
| `subjects` | Subject name and code | Subject name unique without case sensitivity |
| `attendance` | Student, subject, date, and Present/Absent/Leave status | Foreign keys with cascade delete; unique student/subject/date; status `CHECK` |
| `settings` | Attendance threshold and Leave handling mode | Key/value primary key |
| `admins` | Administrator username and password hash | Case-insensitive unique username; password hash only |

The startup migration adds missing student fields and the administrators table without dropping or recreating application tables.

## 5. Main algorithm

For the default Leave-excluded policy:

```text
counted_sessions = Present + Absent
attendance_percentage = Present / counted_sessions × 100
```

If `counted_sessions` is zero, the result is 0%. The default shortage threshold is 75%. Leave can optionally count as Present or Absent in Settings; the selected policy is used by analytics, dashboard metrics, student profiles, and reports.

Bulk attendance selects all students for an exact course and section and writes their records in one database operation. A matching student/subject/date row is updated, using the database unique constraint to prevent duplicates.

## 6. Test cases

Tests use a separate temporary SQLite file for each test. The project's saved database is not used as a test database.

| Test | Expected result | Actual result |
|---|---|---|
| Eight Present and two Absent | 80% attendance | Pass |
| Eight Present and two Leave, default setting | 100%; Leave excluded from denominator | Pass |
| Same student, subject, and date twice | Second request rejected with conflict | Pass |
| Edit an existing attendance entry | Existing row changes to the new status | Pass |
| Student with six Present and four Absent | Listed below 75% with 60% | Pass |
| Filter by one subject | Only matching attendance returned | Pass |
| Empty/invalid attendance status | Validation error; no record written | Pass |
| Create then edit student | Updated fields are returned | Pass |
| CSV with subject filter | Only matching records exported | Pass |
| Spreadsheet formula in exported data | Cell is escaped before export | Pass |
| Unauthenticated analytics request | 401 response | Pass |
| Missing/invalid CSRF token | Change request rejected | Pass |
| Empty attendance table | Analytics returns empty arrays and 0%, no crash | Pass |
| Bulk mark class with existing record | Existing row updated; missing rows created | Pass |
| First administrator setup | Password stored as a verified hash; remote setup denied | Pass |
| Duplicate student ID/subject name | Duplicate rejected | Pass |
| Subject create/edit/delete | Subject updated and its attendance cascades on delete | Pass |
| Student delete | Related attendance cascades on delete | Pass |
| Demo loader invoked with existing records | Conflict; existing roster and subjects stay intact | Pass |
| Legacy SQLite schema upgrade | Existing attendance/settings retained; new student fields added | Pass |
| Application page rendering and login | All seven pages render; valid admin login succeeds | Pass |
| Invalid date or foreign-key IDs | Invalid attendance request rejected | Pass |

Run the cases with:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 7. Screenshot checklist

- [ ] First-run administrator setup page (do not include the password in the screenshot).
- [ ] Dashboard showing database-backed totals, charts, and attendance rule.
- [ ] Student list and create/edit form, with optional email.
- [ ] Subject list.
- [ ] Attendance list with filters and the bulk class attendance form.
- [ ] Analytics showing a shortage below the configured threshold.
- [ ] Filtered report and CSV download; print preview if required.
- [ ] Settings showing threshold and Leave policy.
- [ ] Responsive layout at a narrow/mobile viewport.

Use fictional/demo student records in submitted screenshots. Do not expose real student contact information or credentials.

## 8. BCA viva questions and answers

1. **Why use Flask?** Flask is a small Python web framework with routing and template support that is suitable for a local academic project.
2. **Why use SQLite?** SQLite is serverless, file-based, and included with Python, making it easy to run and demonstrate locally.
3. **How is a duplicate attendance record prevented?** A database `UNIQUE(student_id, subject_id, date)` constraint is the final safeguard; Flask returns a useful validation response.
4. **How is SQL injection prevented?** Database values are passed through parameterized SQLite queries rather than concatenated into SQL.
5. **How is attendance percentage calculated?** By default, Present is divided by Present plus Absent, then multiplied by 100. Leave is excluded.
6. **What happens when there are no counted sessions?** The percentage is defined as 0%, avoiding division by zero.
7. **How are passwords stored?** Werkzeug's password-hashing functions store a salted hash; the submitted password is not stored as plaintext.
8. **What is CSRF protection?** A session token is checked on every state-changing request so another site cannot silently submit an authenticated change.
9. **How does bulk marking work?** The teacher chooses a course, section, subject, date, and status; one record per student is inserted or the matching record is updated.
10. **What are the current limitations?** The app is designed for local single-admin demonstrations; Chart.js needs internet access, and password recovery/roles are not provided.
