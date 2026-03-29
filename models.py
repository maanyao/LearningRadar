# models.py
import sqlite3
import json
from datetime import datetime, timedelta
import hashlib
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'instance', 'student_data.db')
STUCK_TIMEOUT_MINUTES = 1  # 卡住超时阈值（分钟）

# ========== 辅助函数 ==========
def format_datetime(dt):
    if dt is None:
        return ''
    if isinstance(dt, datetime):
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    return str(dt)[:19]

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def log_action(user_id, action_type):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO actions (user_id, action_type, timestamp) VALUES (?,?,?)",
              (user_id, action_type, datetime.now()))
    conn.commit()
    conn.close()

# ========== 数据库初始化 ==========
def init_db():
    conn = get_db()
    c = conn.cursor()

    # 删除所有表（按依赖顺序）
    c.execute("DROP TABLE IF EXISTS reminders")
    c.execute("DROP TABLE IF EXISTS student_task_progress")
    c.execute("DROP TABLE IF EXISTS tasks")
    c.execute("DROP TABLE IF EXISTS students")
    c.execute("DROP TABLE IF EXISTS users")
    c.execute("DROP TABLE IF EXISTS classes")
    c.execute("DROP TABLE IF EXISTS schools")
    c.execute("DROP TABLE IF EXISTS actions")

    # 创建表
    c.execute('''CREATE TABLE schools (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE
    )''')

    c.execute('''CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT DEFAULT 'student',
        school_id INTEGER,
        created_at TIMESTAMP,
        FOREIGN KEY (school_id) REFERENCES schools(id)
    )''')

    c.execute('''CREATE TABLE students (
        user_id INTEGER PRIMARY KEY,
        status TEXT DEFAULT 'normal',
        last_active TIMESTAMP,
        class_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (class_id) REFERENCES classes(id)
    )''')

    c.execute('''CREATE TABLE classes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        school_id INTEGER NOT NULL,
        teacher_id INTEGER NOT NULL,
        FOREIGN KEY (school_id) REFERENCES schools(id),
        FOREIGN KEY (teacher_id) REFERENCES users(id),
        UNIQUE(school_id, name)
    )''')

    c.execute('''CREATE TABLE tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        knowledge_point TEXT,
        steps TEXT NOT NULL,
        steps_config TEXT,
        created_by INTEGER,
        created_at TIMESTAMP
    )''')

    c.execute('''CREATE TABLE student_task_progress (
        user_id INTEGER,
        task_id INTEGER,
        current_step INTEGER DEFAULT 0,
        completed BOOLEAN DEFAULT 0,
        last_step_time TIMESTAMP,
        proof TEXT,
        PRIMARY KEY (user_id, task_id)
    )''')

    c.execute('''CREATE TABLE reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TIMESTAMP,
        is_read BOOLEAN DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )''')

    c.execute('''CREATE TABLE actions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action_type TEXT,
        timestamp TIMESTAMP
    )''')

    conn.commit()
    conn.close()

    insert_initial_data()
    insert_sample_data()

def insert_initial_data():
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM schools")
    if c.fetchone()[0] > 0:
        conn.close()
        return

    # 学校
    c.execute("INSERT INTO schools (name) VALUES (?)", ('智学中学',))
    school_id = c.lastrowid

    # 教师
    teacher_pwd = hash_password('teacher')
    c.execute('''INSERT INTO users (name, phone, password_hash, role, school_id, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              ('王老师', '13800000000', teacher_pwd, 'teacher', school_id, datetime.now()))
    teacher_id = c.lastrowid

    # 班级
    class_names = ['高一(1)班', '高一(2)班', '高二(1)班']
    class_ids = {}
    for name in class_names:
        c.execute('''INSERT INTO classes (name, school_id, teacher_id) VALUES (?, ?, ?)''',
                  (name, school_id, teacher_id))
        class_ids[name] = c.lastrowid

    # 学生
    students_data = [
        ('李明', '13811111111', class_ids['高一(1)班']),
        ('王芳', '13822222222', class_ids['高一(1)班']),
        ('张伟', '13833333333', class_ids['高一(2)班']),
        ('赵雷', '13844444444', class_ids['高一(2)班']),
        ('陈晨', '13855555555', class_ids['高二(1)班']),
    ]
    for name, phone, class_id in students_data:
        pwd_hash = hash_password('123456')
        c.execute('''INSERT INTO users (name, phone, password_hash, role, school_id, created_at)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (name, phone, pwd_hash, 'student', school_id, datetime.now()))
        user_id = c.lastrowid
        c.execute('''INSERT INTO students (user_id, status, last_active, class_id)
                     VALUES (?, ?, ?, ?)''',
                  (user_id, 'normal', datetime.now(), class_id))

    conn.commit()
    conn.close()

def insert_sample_data():
    """从 knowledge_base.json 加载预设任务"""
    try:
        with open('knowledge_base.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM tasks")
    if c.fetchone()[0] == 0:
        c.execute("SELECT id FROM users WHERE role='teacher' LIMIT 1")
        teacher_row = c.fetchone()
        teacher_id = teacher_row[0] if teacher_row else 1

        for kp in data['knowledge_points']:
            for task in kp['basic_tasks']:
                steps_config = task.get('steps_config', [{"need_proof": False}]*len(task['steps']))
                for cfg in steps_config:
                    if 'help_text' not in cfg:
                        cfg['help_text'] = ''
                c.execute('''INSERT INTO tasks (name, type, knowledge_point, steps, steps_config, created_by, created_at)
                             VALUES (?,?,?,?,?,?,?)''',
                          (task['name'], 'basic', kp['name'], json.dumps(task['steps']),
                           json.dumps(steps_config), teacher_id, datetime.now()))
            for task in kp['advanced_tasks']:
                steps_config = task.get('steps_config', [{"need_proof": False}]*len(task['steps']))
                for cfg in steps_config:
                    if 'help_text' not in cfg:
                        cfg['help_text'] = ''
                c.execute('''INSERT INTO tasks (name, type, knowledge_point, steps, steps_config, created_by, created_at)
                             VALUES (?,?,?,?,?,?,?)''',
                          (task['name'], 'advanced', kp['name'], json.dumps(task['steps']),
                           json.dumps(steps_config), teacher_id, datetime.now()))
    conn.commit()
    conn.close()

# ========== 用户相关 ==========
def create_user_with_school(name, phone, password_hash, role, school_id):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (name, phone, password_hash, role, school_id, created_at) VALUES (?,?,?,?,?,?)",
                  (name, phone, password_hash, role, school_id, datetime.now()))
        user_id = c.lastrowid
        if role == 'student':
            c.execute("INSERT INTO students (user_id, status, last_active) VALUES (?,?,?)",
                      (user_id, 'normal', datetime.now()))
        conn.commit()
        return user_id
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def get_user_by_phone(phone):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, role, password_hash FROM users WHERE phone = ?", (phone,))
    user = c.fetchone()
    conn.close()
    return user

def update_student_status(student_id, new_status):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE students SET status = ? WHERE user_id = ?", (new_status, student_id))
    conn.commit()
    conn.close()

# ========== 任务与进度相关 ==========
def get_current_task_for_student(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT t.id, t.name, t.type, t.knowledge_point, t.steps, t.steps_config, p.current_step, p.last_step_time
                 FROM tasks t
                 JOIN student_task_progress p ON t.id = p.task_id
                 WHERE p.user_id = ? AND p.completed = 0
                 LIMIT 1''', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            'task_id': row['id'],
            'name': row['name'],
            'type': row['type'],
            'knowledge_point': row['knowledge_point'],
            'steps': json.loads(row['steps']),
            'steps_config': json.loads(row['steps_config']) if row['steps_config'] else [],
            'current_step': row['current_step'] or 0,
            'last_step_time': row['last_step_time']
        }
    return None

def complete_step(user_id, task_id, step_index, proof):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT current_step, completed FROM student_task_progress WHERE user_id = ? AND task_id = ?", (user_id, task_id))
    row = c.fetchone()
    if not row:
        current_step = 0
        completed = False
    else:
        current_step = row['current_step']
        completed = row['completed']

    if completed:
        conn.close()
        return {'error': '任务已完成，不能重复完成'}

    c.execute("SELECT steps, steps_config, knowledge_point FROM tasks WHERE id = ?", (task_id,))
    task_row = c.fetchone()
    steps = json.loads(task_row['steps'])
    configs = json.loads(task_row['steps_config']) if task_row['steps_config'] else []

    if step_index < current_step:
        conn.close()
        return {'error': '步骤顺序错误'}

    if step_index == current_step:
        if configs and configs[step_index].get('need_proof', False) and not proof:
            conn.close()
            return {'error': '该步骤需要上传证明，请填写完成过程'}

        new_step = current_step + 1
        if new_step == len(steps):
            completed = True

        c.execute("INSERT OR REPLACE INTO student_task_progress (user_id, task_id, current_step, completed, last_step_time, proof) VALUES (?,?,?,?,?,?)",
                  (user_id, task_id, new_step, completed, datetime.now(), proof))
        conn.commit()
        c.execute("UPDATE students SET last_active = ? WHERE user_id = ?", (datetime.now(), user_id))
        conn.commit()
        conn.close()

        log_action(user_id, f'complete_step_{new_step}')

        if completed:
            update_student_status(user_id, 'ahead')
            knowledge_point = task_row['knowledge_point']
            adv = get_available_advanced_task(user_id, knowledge_point)
            if adv:
                return {'success': True, 'completed': True, 'advanced_available': adv}
            return {'success': True, 'completed': True}
        return {'success': True, 'completed': completed}
    else:
        conn.close()
        return {'error': '请按顺序完成步骤'}

def get_available_advanced_task(user_id, knowledge_point):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, name FROM tasks 
                 WHERE knowledge_point = ? AND type = 'advanced'
                 AND id NOT IN (SELECT task_id FROM student_task_progress WHERE user_id = ? AND completed = 1)''',
              (knowledge_point, user_id))
    task = c.fetchone()
    conn.close()
    return {'task_id': task['id'], 'name': task['name']} if task else None

def assign_advanced_task(user_id, task_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM student_task_progress WHERE user_id = ? AND completed = 0", (user_id,))
    c.execute("INSERT INTO student_task_progress (user_id, task_id, current_step, completed, last_step_time) VALUES (?,?,?,?,?)",
              (user_id, task_id, 0, 0, datetime.now()))
    conn.commit()
    conn.close()
    update_student_status(user_id, 'normal')

def get_all_tasks():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, type, knowledge_point, steps, steps_config, created_at FROM tasks")
    rows = c.fetchall()
    tasks = []
    for r in rows:
        tasks.append({
            'id': r['id'],
            'name': r['name'],
            'type': r['type'],
            'knowledge_point': r['knowledge_point'],
            'steps': json.loads(r['steps']),
            'steps_config': json.loads(r['steps_config']) if r['steps_config'] else [],
            'created_at': r['created_at']
        })
    conn.close()
    return tasks

def create_task(name, task_type, knowledge_point, steps, steps_config, created_by):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO tasks (name, type, knowledge_point, steps, steps_config, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
              (name, task_type, knowledge_point, json.dumps(steps), json.dumps(steps_config), created_by, datetime.now()))
    conn.commit()
    conn.close()

def update_task(task_id, name, task_type, knowledge_point, steps, steps_config):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE tasks SET name=?, type=?, knowledge_point=?, steps=?, steps_config=? WHERE id=?",
              (name, task_type, knowledge_point, json.dumps(steps), json.dumps(steps_config), task_id))
    conn.commit()
    conn.close()

def delete_task(task_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM student_task_progress WHERE task_id=?", (task_id,))
    c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()
    conn.close()

def assign_task_to_student_with_check(student_id, task_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT completed FROM student_task_progress WHERE user_id = ? AND task_id = ?", (student_id, task_id))
    row = c.fetchone()
    if row and row['completed'] == 1:
        conn.close()
        return {'error': '学生已完成该任务，不能重复分配'}
    c.execute("SELECT task_id FROM student_task_progress WHERE user_id = ? AND completed = 0", (student_id,))
    if c.fetchone():
        conn.close()
        return {'error': '学生已有未完成任务，请先完成当前任务'}
    c.execute("INSERT INTO student_task_progress (user_id, task_id, current_step, completed, last_step_time) VALUES (?,?,?,?,?)",
              (student_id, task_id, 0, 0, datetime.now()))
    conn.commit()
    conn.close()
    return {'success': True}

def get_available_tasks_for_student(student_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT task_id FROM student_task_progress WHERE user_id = ? AND completed = 1", (student_id,))
    completed_task_ids = [r[0] for r in c.fetchall()]
    c.execute("SELECT task_id FROM student_task_progress WHERE user_id = ? AND completed = 0", (student_id,))
    ongoing_task_ids = [r[0] for r in c.fetchall()]
    if ongoing_task_ids:
        conn.close()
        return []
    if completed_task_ids:
        placeholders = ','.join(['?'] * len(completed_task_ids))
        sql = f"SELECT id, name, type, knowledge_point FROM tasks WHERE id NOT IN ({placeholders})"
        c.execute(sql, completed_task_ids)
    else:
        c.execute("SELECT id, name, type, knowledge_point FROM tasks")
    tasks = [{'id': r['id'], 'name': r['name'], 'type': r['type'], 'knowledge_point': r['knowledge_point']} for r in c.fetchall()]
    conn.close()
    return tasks

# ========== 班级与学生管理 ==========
def get_teacher_classes(teacher_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name, school_id FROM classes WHERE teacher_id = ?", (teacher_id,))
    rows = c.fetchall()
    classes = [{'id': r['id'], 'name': r['name'], 'school_id': r['school_id']} for r in rows]
    conn.close()
    return classes

def create_class(name, school_id, teacher_id):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO classes (name, school_id, teacher_id) VALUES (?,?,?)", (name, school_id, teacher_id))
        conn.commit()
        return c.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()

def get_class_students(class_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT u.id, u.name, u.phone, s.status, s.last_active, s.class_id
                 FROM users u
                 JOIN students s ON u.id = s.user_id
                 WHERE s.class_id = ? AND u.role='student'
                 ORDER BY u.name''', (class_id,))
    rows = c.fetchall()
    students = []
    for r in rows:
        students.append({
            'id': r['id'],
            'name': r['name'],
            'phone': r['phone'],
            'status': r['status'],
            'last_active': format_datetime(r['last_active']),
            'class_id': r['class_id']
        })
    conn.close()
    return students

def add_student(name, phone, password, class_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE phone = ?", (phone,))
    if c.fetchone():
        conn.close()
        return {'error': '手机号已注册'}
    pwd_hash = hash_password(password)
    c.execute("SELECT school_id FROM classes WHERE id = ?", (class_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {'error': '班级不存在'}
    school_id = row[0]
    now = datetime.now()
    try:
        c.execute('''INSERT INTO users (name, phone, password_hash, role, school_id, created_at)
                     VALUES (?,?,?,?,?,?)''',
                  (name, phone, pwd_hash, 'student', school_id, now))
        user_id = c.lastrowid
        c.execute('''INSERT INTO students (user_id, status, last_active, class_id)
                     VALUES (?,?,?,?)''',
                  (user_id, 'normal', now, class_id))
        conn.commit()
        return {'success': True, 'user_id': user_id}
    except Exception as e:
        conn.rollback()
        return {'error': str(e)}
    finally:
        conn.close()

def update_student_info(student_id, name=None, phone=None):
    conn = get_db()
    c = conn.cursor()
    updates = []
    params = []
    if name:
        updates.append("name = ?")
        params.append(name)
    if phone:
        updates.append("phone = ?")
        params.append(phone)
    if not updates:
        conn.close()
        return {'error': '无更新字段'}
    params.append(student_id)
    sql = f"UPDATE users SET {', '.join(updates)} WHERE id = ? AND role='student'"
    c.execute(sql, params)
    conn.commit()
    conn.close()
    return {'success': True}

def delete_student(student_id):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM student_task_progress WHERE user_id = ?", (student_id,))
        c.execute("DELETE FROM students WHERE user_id = ?", (student_id,))
        c.execute("DELETE FROM users WHERE id = ? AND role='student'", (student_id,))
        conn.commit()
        return {'success': True}
    except Exception as e:
        conn.rollback()
        return {'error': str(e)}
    finally:
        conn.close()

def get_students_progress(class_id=None):
    conn = get_db()
    c = conn.cursor()
    if class_id:
        c.execute("SELECT id, name FROM users WHERE role='student' AND id IN (SELECT user_id FROM students WHERE class_id=?)", (class_id,))
    else:
        c.execute("SELECT id, name FROM users WHERE role='student'")
    students = c.fetchall()
    result = []
    now = datetime.now()
    for student in students:
        student_id = student['id']
        name = student['name']
        c.execute('''SELECT t.id, t.name, p.current_step, p.last_step_time, t.steps
                     FROM tasks t
                     JOIN student_task_progress p ON t.id = p.task_id
                     WHERE p.user_id = ? AND p.completed = 0
                     LIMIT 1''', (student_id,))
        task_row = c.fetchone()
        if task_row:
            task_name = task_row['name']
            current_step = task_row['current_step'] or 0
            last_step_time = task_row['last_step_time']
            steps = json.loads(task_row['steps']) if task_row['steps'] else []
            total_steps = len(steps)
        else:
            task_name = '无任务'
            current_step = 0
            total_steps = 0
            last_step_time = None
        c.execute("SELECT status FROM students WHERE user_id = ?", (student_id,))
        status_row = c.fetchone()
        manual_status = status_row['status'] if status_row else 'normal'
        if task_name != '无任务' and last_step_time:
            if isinstance(last_step_time, str):
                try:
                    last_step_time = datetime.strptime(last_step_time, '%Y-%m-%d %H:%M:%S.%f')
                except:
                    last_step_time = datetime.now()
            if (now - last_step_time) > timedelta(minutes=STUCK_TIMEOUT_MINUTES):
                status = 'stuck'
            else:
                status = 'normal'
            if manual_status == 'ahead':
                status = 'ahead'
        else:
            status = 'normal'
        result.append({
            'id': student_id,
            'name': name,
            'status': status,
            'last_step_time': format_datetime(last_step_time) or '暂无',
            'task_name': task_name,
            'current_step': current_step,
            'total_steps': total_steps
        })
    conn.close()
    return result

def get_stuck_students_by_class(class_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM students WHERE class_id = ?", (class_id,))
    student_ids = [r[0] for r in c.fetchall()]
    if not student_ids:
        return []
    placeholders = ','.join(['?'] * len(student_ids))
    sql = f'''SELECT user_id FROM student_task_progress
              WHERE user_id IN ({placeholders}) AND completed = 0
                AND last_step_time < ?'''
    params = student_ids + [(datetime.now() - timedelta(minutes=STUCK_TIMEOUT_MINUTES))]
    c.execute(sql, params)
    stuck_ids = [r[0] for r in c.fetchall()]
    conn.close()
    return stuck_ids

# ========== 提醒相关 ==========
def create_reminder(user_id, message):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO reminders (user_id, message, created_at, is_read) VALUES (?,?,?,?)",
              (user_id, message, datetime.now(), 0))
    conn.commit()
    conn.close()

def get_unread_reminders(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, message, created_at FROM reminders WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC", (user_id,))
    rows = c.fetchall()
    reminders = [{'id': r['id'], 'message': r['message'], 'created_at': format_datetime(r['created_at'])} for r in rows]
    conn.close()
    return reminders

def mark_reminder_read(reminder_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE reminders SET is_read = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    conn.close()

# ========== 班级活跃度与报告 ==========
def get_class_activity(class_id, days=7):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM students WHERE class_id = ?", (class_id,))
    student_ids = [r[0] for r in c.fetchall()]
    if not student_ids:
        conn.close()
        return {'dates': [], 'counts': []}
    end_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start_date = end_date - timedelta(days=days-1)
    dates = [(start_date + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(days)]
    counts = []
    for i in range(days):
        date_start = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
        date_end = (start_date + timedelta(days=i+1)).strftime('%Y-%m-%d')
        placeholders = ','.join(['?'] * len(student_ids))
        sql = f'''SELECT COUNT(DISTINCT user_id) FROM student_task_progress
                  WHERE user_id IN ({placeholders})
                    AND last_step_time >= ? AND last_step_time < ?'''
        c.execute(sql, student_ids + [date_start, date_end])
        counts.append(c.fetchone()[0])
    conn.close()
    return {'dates': dates, 'counts': counts}

def get_class_detailed_report(class_id):
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT name FROM classes WHERE id = ?", (class_id,))
    class_row = c.fetchone()
    class_name = class_row['name'] if class_row else '未知班级'
    c.execute("SELECT COUNT(*) FROM students WHERE class_id = ?", (class_id,))
    student_count = c.fetchone()[0]

    c.execute("SELECT user_id FROM students WHERE class_id = ?", (class_id,))
    student_ids = [r[0] for r in c.fetchall()]

    activity_data = get_class_activity(class_id)

    # 卡点分析
    now = datetime.now()
    stuck_records = []
    stuck_summary = {}
    for uid in student_ids:
        c.execute('''SELECT t.id as task_id, t.name as task_name, p.current_step, t.steps, t.steps_config, p.last_step_time
                     FROM tasks t
                     JOIN student_task_progress p ON t.id = p.task_id
                     WHERE p.user_id = ? AND p.completed = 0''', (uid,))
        row = c.fetchone()
        if row and row['last_step_time']:
            last_time = row['last_step_time']
            if isinstance(last_time, str):
                try:
                    last_time = datetime.strptime(last_time, '%Y-%m-%d %H:%M:%S.%f')
                except:
                    last_time = datetime.now()
            if (now - last_time) > timedelta(minutes=STUCK_TIMEOUT_MINUTES):
                task_id = row['task_id']
                task_name = row['task_name']
                step_index = row['current_step']
                steps = json.loads(row['steps'])
                steps_config = json.loads(row['steps_config']) if row['steps_config'] else []
                step_desc = steps[step_index] if step_index < len(steps) else '未知步骤'
                help_text = steps_config[step_index].get('help_text', '') if step_index < len(steps_config) else ''
                c.execute("SELECT name FROM users WHERE id = ?", (uid,))
                student_name = c.fetchone()[0]
                stuck_records.append({
                    'student_id': uid,
                    'student_name': student_name,
                    'task_name': task_name,
                    'step_index': step_index,
                    'step_desc': step_desc,
                    'help_text': help_text,
                    'stuck_since': format_datetime(last_time)
                })
                key = f"{task_id}_{step_index}"
                if key not in stuck_summary:
                    stuck_summary[key] = {'task_name': task_name, 'step_index': step_index,
                                          'step_desc': step_desc, 'count': 0}
                stuck_summary[key]['count'] += 1

    # 任务完成统计
    task_completion_stats = []
    c.execute("SELECT id, name, steps FROM tasks")
    all_tasks = c.fetchall()
    for task in all_tasks:
        task_id = task['id']
        task_name = task['name']
        steps = json.loads(task['steps'])
        total_steps = len(steps)
        if student_ids:
            placeholders = ','.join(['?'] * len(student_ids))
            c.execute(f'''SELECT COUNT(DISTINCT user_id) FROM student_task_progress
                         WHERE task_id = ? AND completed = 1 AND user_id IN ({placeholders})''',
                      (task_id,) + tuple(student_ids))
            completed_count = c.fetchone()[0]
            completed_percent = round(completed_count / student_count * 100, 1) if student_count > 0 else 0
            c.execute(f'''SELECT AVG(current_step) FROM student_task_progress
                         WHERE task_id = ? AND user_id IN ({placeholders})''',
                      (task_id,) + tuple(student_ids))
            avg_step = c.fetchone()[0] or 0
            avg_progress = round(avg_step / total_steps * 100, 1) if total_steps > 0 else 0
        else:
            completed_count = 0
            completed_percent = 0
            avg_progress = 0
        task_completion_stats.append({
            'task_id': task_id,
            'task_name': task_name,
            'total_steps': total_steps,
            'completed_count': completed_count,
            'completed_percent': completed_percent,
            'avg_progress': avg_progress
        })

    # 学生学习路径（简化版，仅返回任务列表）
    student_learning_paths = []
    for uid in student_ids:
        c.execute('''SELECT t.name as task_name, p.current_step, p.completed, p.last_step_time, t.steps
                     FROM tasks t
                     JOIN student_task_progress p ON t.id = p.task_id
                     WHERE p.user_id = ?
                     ORDER BY p.last_step_time ASC''', (uid,))
        progress_records = c.fetchall()
        if not progress_records:
            continue
        c.execute("SELECT name FROM users WHERE id = ?", (uid,))
        student_name = c.fetchone()[0]
        learning_path = []
        for record in progress_records:
            task_name = record[0]
            current_step = record[1]
            completed = record[2]
            last_step_time = record[3]
            steps = json.loads(record[4])
            total_steps = len(steps)
            status = '已完成' if completed else f'进行中（步骤 {current_step}/{total_steps}）'
            learning_path.append({
                'task_name': task_name,
                'status': status,
                'progress': f'{current_step}/{total_steps}',
                'time': format_datetime(last_step_time),
                'completed': completed
            })
        student_learning_paths.append({'student_name': student_name, 'learning_path': learning_path})

    conn.close()
    return {
        'class_name': class_name,
        'student_count': student_count,
        'activity_trend': activity_data,
        'stuck_records': stuck_records,
        'task_stuck_summary': list(stuck_summary.values()),
        'student_learning_paths': student_learning_paths,
        'task_completion_stats': task_completion_stats
    }

# ========== 批量导入 ==========
def batch_import_tasks(tasks_json):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE role='teacher' LIMIT 1")
    teacher_row = c.fetchone()
    teacher_id = teacher_row[0] if teacher_row else 1
    for task in tasks_json:
        c.execute('''INSERT INTO tasks (name, type, knowledge_point, steps, steps_config, created_by, created_at)
                     VALUES (?,?,?,?,?,?,?)''',
                  (task['name'], task['type'], task.get('knowledge_point', ''),
                   json.dumps(task['steps']), json.dumps(task.get('steps_config', [])),
                   teacher_id, datetime.now()))
    conn.commit()
    conn.close()

def batch_import_students(students_data, school_id, default_class_name):
    conn = get_db()
    try:
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE role='teacher' LIMIT 1")
        teacher_row = c.fetchone()
        if not teacher_row:
            raise Exception("未找到教师账号，请先创建教师")
        teacher_id = teacher_row[0]
        for stu in students_data:
            class_name = stu.get('class_name', default_class_name)
            c.execute("SELECT id FROM classes WHERE name = ? AND school_id = ?", (class_name, school_id))
            row = c.fetchone()
            if not row:
                c.execute("INSERT INTO classes (name, school_id, teacher_id) VALUES (?,?,?)",
                          (class_name, school_id, teacher_id))
                class_id = c.lastrowid
            else:
                class_id = row[0]
            c.execute("SELECT id FROM users WHERE phone = ?", (stu['phone'],))
            if c.fetchone():
                continue
            pwd_hash = hash_password(stu.get('password', '123456'))
            c.execute('''INSERT INTO users (name, phone, password_hash, role, school_id, created_at)
                         VALUES (?,?,?,?,?,?)''',
                      (stu['name'], stu['phone'], pwd_hash, 'student', school_id, datetime.now()))
            user_id = c.lastrowid
            c.execute('''INSERT INTO students (user_id, status, last_active, class_id)
                         VALUES (?,?,?,?)''',
                      (user_id, 'normal', datetime.now(), class_id))
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()