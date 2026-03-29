# db_operations.py
import sqlite3
import json
from datetime import datetime, timedelta
from utils import get_db, format_datetime, hash_password, STUCK_TIMEOUT_MINUTES, log_action

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

# ========== 任务相关 ==========
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
    
    c.execute("SELECT steps, steps_config FROM tasks WHERE id = ?", (task_id,))
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
            completed_task = {'knowledge_point': task_row['knowledge_point']}
            adv = get_available_advanced_task(user_id, completed_task['knowledge_point'])
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
    c.execute("SELECT id, message, created_at FROM reminders WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC",
              (user_id,))
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

# ========== 班级相关 ==========
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
        c.execute("INSERT INTO classes (name, school_id, teacher_id) VALUES (?,?,?)",
                  (name, school_id, teacher_id))
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
    students = [{'id': r['id'], 'name': r['name'], 'phone': r['phone'], 
                 'status': r['status'], 'last_active': format_datetime(r['last_active']), 
                 'class_id': r['class_id']} for r in rows]
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
    
    # 活跃度趋势
    from models import get_class_activity
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
    
    conn.close()
    return {
        'class_name': class_name,
        'student_count': student_count,
        'activity_trend': activity_data,
        'stuck_records': stuck_records,
        'task_stuck_summary': list(stuck_summary.values()),
        'student_learning_paths': [],
        'task_completion_stats': []
    }