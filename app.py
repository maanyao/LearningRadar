# app.py
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import hashlib
import models
import os
from datetime import datetime
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'
app.config['JSON_AS_ASCII'] = False

# 确保 instance 文件夹存在
os.makedirs(os.path.join(app.root_path, 'instance'), exist_ok=True)

# 初始化数据库
models.init_db()

# ---------- 页面路由 ----------
@app.route('/')
def home():
    return redirect('/login')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/student')
def student_page():
    return render_template('student.html')

@app.route('/teacher')
def teacher_page():
    return render_template('teacher.html')

# ---------- 认证 API ----------
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    name = data.get('name')
    phone = data.get('phone')
    password = data.get('password')
    role = data.get('role', 'student')
    
    if not name or not phone or not password:
        return jsonify({'error': '请填写完整信息'}), 400

    conn = models.get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM schools LIMIT 1")
    school_row = c.fetchone()
    conn.close()
    
    if not school_row:
        return jsonify({'error': '学校不存在，请联系管理员'}), 400
    school_id = school_row[0]

    if role == 'teacher':
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        user_id = models.create_user_with_school(name, phone, password_hash, 'teacher', school_id)
        if user_id is None:
            return jsonify({'error': '手机号已注册'}), 400
        return jsonify({'success': True, 'message': '注册成功'})
    else:
        class_id = data.get('class_id')
        if not class_id:
            return jsonify({'error': '请选择班级'}), 400
        result = models.add_student(name, phone, password, class_id)
        if 'error' in result:
            return jsonify({'error': result['error']}), 400
        return jsonify({'success': True, 'message': '注册成功'})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    phone = data.get('phone')
    password = data.get('password')
    
    if not phone or not password:
        return jsonify({'error': '请填写手机号和密码'}), 400
    
    user = models.get_user_by_phone(phone)
    if not user or user['password_hash'] != hashlib.sha256(password.encode()).hexdigest():
        return jsonify({'error': '手机号或密码错误'}), 401
    
    session['user_id'] = user['id']
    session['user_name'] = user['name']
    session['user_role'] = user['role']
    return jsonify({'success': True, 'user_id': user['id'], 'name': user['name'], 'role': user['role']})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'success': True})

@app.route('/api/current_user', methods=['GET'])
def current_user():
    if 'user_id' in session:
        return jsonify({'user_id': session['user_id'], 'name': session['user_name'], 'role': session['user_role']})
    return jsonify({'error': '未登录'}), 401

# ---------- 学生端 API ----------
@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    
    conn = models.get_db()
    c = conn.cursor()
    c.execute("UPDATE students SET last_active = ? WHERE user_id = ?", (datetime.now(), session['user_id']))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

@app.route('/api/current_task', methods=['GET'])
def current_task():
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    
    task = models.get_current_task_for_student(session['user_id'])
    if not task:
        return jsonify({'task': None, 'message': '暂无任务，请联系教师分配任务'})
    
    return jsonify({'task': task})

@app.route('/api/complete_step', methods=['POST'])
def complete_step():
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    result = models.complete_step(session['user_id'], data.get('task_id'), data.get('step_index'), data.get('proof', ''))
    if 'error' in result:
        return jsonify({'error': result['error']}), 400
    return jsonify(result)

@app.route('/api/accept_advanced_task', methods=['POST'])
def accept_advanced_task():
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    task_id = data.get('task_id')
    if not task_id:
        return jsonify({'error': '缺少任务ID'}), 400
    
    models.assign_advanced_task(session['user_id'], task_id)
    return jsonify({'success': True})

@app.route('/api/reminders/unread', methods=['GET'])
def unread_reminders():
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    
    reminders = models.get_unread_reminders(session['user_id'])
    return jsonify(reminders)

@app.route('/api/reminders/<int:reminder_id>/read', methods=['POST'])
def mark_reminder_read(reminder_id):
    if 'user_id' not in session:
        return jsonify({'error': '未登录'}), 401
    
    models.mark_reminder_read(reminder_id)
    return jsonify({'success': True})

# ---------- 教师端 API ----------
@app.route('/api/teacher/classes', methods=['GET'])
def teacher_classes():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    classes = models.get_teacher_classes(session['user_id'])
    return jsonify(classes)

@app.route('/api/students_progress', methods=['GET'])
def students_progress():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    class_id = request.args.get('class_id', type=int)
    students = models.get_students_progress(class_id)
    return jsonify(students)

@app.route('/api/update_student_status', methods=['POST'])
def update_student_status():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    data = request.json
    new_status = data.get('status')
    if new_status not in ['normal', 'stuck', 'ahead']:
        return jsonify({'error': '无效状态'}), 400
    
    models.update_student_status(data.get('student_id'), new_status)
    return jsonify({'success': True})

@app.route('/api/assign_task', methods=['POST'])
def assign_task():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    data = request.json
    result = models.assign_task_to_student_with_check(data.get('student_id'), data.get('task_id'))
    if 'error' in result:
        return jsonify({'error': result['error']}), 400
    return jsonify({'success': True})

@app.route('/api/tasks/available', methods=['GET'])
def available_tasks():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    student_id = request.args.get('student_id', type=int)
    if not student_id:
        return jsonify({'error': '缺少学生ID'}), 400
    
    tasks = models.get_available_tasks_for_student(student_id)
    return jsonify(tasks)

@app.route('/api/send_reminder', methods=['POST'])
def send_reminder():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    data = request.json
    class_id = data.get('class_id')
    stuck_students = models.get_stuck_students_by_class(class_id) if class_id else []
    
    for student_id in stuck_students:
        task = models.get_current_task_for_student(student_id)
        if task:
            step_index = task['current_step']
            steps_config = task.get('steps_config', [])
            help_text = steps_config[step_index].get('help_text', '') if step_index < len(steps_config) else ''
            message = f"⚠️ 提醒：你当前任务 '{task['name']}' 的步骤 {step_index+1} 已停留较长时间，请尽快完成。\n"
            if help_text:
                message += f"📖 提示：{help_text}"
            models.create_reminder(student_id, message)
    
    return jsonify({'success': True, 'count': len(stuck_students)})

@app.route('/api/send_reminder_to_student', methods=['POST'])
def send_reminder_to_student():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    data = request.json
    student_id = data.get('student_id')
    task = models.get_current_task_for_student(student_id)
    
    if task:
        step_index = task['current_step']
        steps_config = task.get('steps_config', [])
        help_text = steps_config[step_index].get('help_text', '') if step_index < len(steps_config) else ''
        message = f"⚠️ 教师提醒：你当前任务 '{task['name']}' 的步骤 {step_index+1} 已停留较长时间，请尽快完成。\n"
        if help_text:
            message += f"📖 提示：{help_text}"
    else:
        message = "⚠️ 教师提醒：请关注当前任务进度，如有困难请向老师求助。"
    
    models.create_reminder(student_id, message)
    return jsonify({'success': True})

# ---------- 班级管理 API ----------
@app.route('/api/classes', methods=['POST'])
def create_class():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    data = request.json
    name = data.get('name')
    if not name:
        return jsonify({'error': '班级名称不能为空'}), 400
    
    conn = models.get_db()
    c = conn.cursor()
    c.execute("SELECT school_id FROM users WHERE id = ?", (session['user_id'],))
    school_row = c.fetchone()
    conn.close()
    
    if not school_row:
        return jsonify({'error': '教师信息异常'}), 500
    
    result = models.create_class(name, school_row[0], session['user_id'])
    if result is None:
        return jsonify({'error': '班级已存在'}), 400
    return jsonify({'success': True, 'class_id': result})

@app.route('/api/classes/<int:class_id>/students', methods=['GET'])
def class_students(class_id):
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    students = models.get_class_students(class_id)
    return jsonify(students)

@app.route('/api/students', methods=['POST'])
def add_student():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    data = request.json
    result = models.add_student(data.get('name'), data.get('phone'), data.get('password', '123456'), data.get('class_id'))
    if 'error' in result:
        return jsonify({'error': result['error']}), 400
    return jsonify({'success': True})

@app.route('/api/students/<int:student_id>', methods=['PUT', 'DELETE'])
def manage_student(student_id):
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    if request.method == 'PUT':
        data = request.json
        result = models.update_student_info(student_id, data.get('name'), data.get('phone'))
        if 'error' in result:
            return jsonify({'error': result['error']}), 400
        return jsonify({'success': True})
    else:
        result = models.delete_student(student_id)
        if 'error' in result:
            return jsonify({'error': result['error']}), 400
        return jsonify({'success': True})

# ---------- 任务管理 API ----------
@app.route('/api/tasks', methods=['GET', 'POST'])
def manage_tasks():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    if request.method == 'GET':
        tasks = models.get_all_tasks()
        return jsonify(tasks)
    else:
        data = request.json
        models.create_task(data.get('name'), data.get('type'), data.get('knowledge_point', ''), 
                          data.get('steps'), data.get('steps_config', []), session['user_id'])
        return jsonify({'success': True})

@app.route('/api/tasks/<int:task_id>', methods=['PUT', 'DELETE'])
def modify_task(task_id):
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    if request.method == 'PUT':
        data = request.json
        models.update_task(task_id, data.get('name'), data.get('type'), data.get('knowledge_point', ''),
                          data.get('steps'), data.get('steps_config', []))
        return jsonify({'success': True})
    else:
        models.delete_task(task_id)
        return jsonify({'success': True})

@app.route('/api/task_steps/<int:task_id>', methods=['GET'])
def get_task_steps(task_id):
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    tasks = models.get_all_tasks()
    task = next((t for t in tasks if t['id'] == task_id), None)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    return jsonify({'steps': task['steps'], 'steps_config': task['steps_config']})

@app.route('/api/tasks/batch_import', methods=['POST'])
def batch_import_tasks():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    file = request.files.get('file')
    if not file:
        return jsonify({'error': '未上传文件'}), 400
    
    data = json.load(file)
    models.batch_import_tasks(data)
    return jsonify({'success': True, 'count': len(data)})

# ---------- 班级报告 API ----------
@app.route('/api/class_detailed_report/<int:class_id>', methods=['GET'])
def class_detailed_report(class_id):
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    report = models.get_class_detailed_report(class_id)
    return jsonify(report)

@app.route('/api/class_activity/<int:class_id>', methods=['GET'])
def class_activity(class_id):
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    data = models.get_class_activity(class_id)
    return jsonify(data)

@app.route('/api/students/batch_import', methods=['POST'])
def batch_import_students():
    if 'user_role' not in session or session['user_role'] != 'teacher':
        return jsonify({'error': '无权限'}), 403
    
    file = request.files.get('file')
    if not file:
        return jsonify({'error': '未上传文件'}), 400
    
    import csv
    content = file.read().decode('utf-8-sig')
    reader = csv.DictReader(content.splitlines())
    students = []
    for row in reader:
        students.append({
            'name': row.get('姓名', ''),
            'phone': row.get('手机号', ''),
            'password': row.get('密码', '123456'),
            'class_name': row.get('班级名称', '')
        })
    
    conn = models.get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM schools LIMIT 1")
    school_id = c.fetchone()[0]
    conn.close()
    
    models.batch_import_students(students, school_id, '默认班级')
    return jsonify({'success': True, 'count': len(students)})

@app.route('/api/public/classes', methods=['GET'])
def public_classes():
    conn = models.get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM classes ORDER BY name")
    rows = c.fetchall()
    classes = [{'id': r[0], 'name': r[1]} for r in rows]
    conn.close()
    return jsonify(classes)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)