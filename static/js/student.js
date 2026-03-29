// student.js
let currentTask = null;
let heartbeatInterval = null;
let pendingStepIndex = null;
let stepNeedProof = false;
let reminderInterval = null;

async function loadUserInfo() {
    const res = await fetch('/api/current_user');
    if (res.status === 401) {
        window.location.href = '/login';
        return;
    }
    const user = await res.json();
    document.getElementById('studentNameDisplay').innerText = `欢迎，${user.name}`;
}

async function loadTask() {
    const res = await fetch('/api/current_task');
    if (res.status === 401) {
        window.location.href = '/login';
        return;
    }
    const data = await res.json();
    if (!data.task) {
        document.getElementById('taskContainer').innerHTML = `<div class="text-center py-10 text-gray-500">${data.message || '暂无任务，请联系教师分配任务'}</div>`;
        return;
    }
    currentTask = data.task;
    renderTask(currentTask);
    startHeartbeat();
}

function renderTask(task) {
    const steps = task.steps;
    const configs = task.steps_config || [];
    const currentStep = task.current_step;
    const completed = currentStep === steps.length;
    const html = `
        <h2 class="text-xl font-semibold mb-4">${escapeHtml(task.name)}</h2>
        <div class="mb-4 text-sm text-gray-600">任务类型：${task.type === 'basic' ? '基础' : '进阶'}</div>
        <div class="space-y-4">
            ${steps.map((step, idx) => {
                const needProof = configs[idx] && configs[idx].need_proof;
                const helpText = configs[idx] && configs[idx].help_text;
                return `
                <div class="border rounded-lg p-4 ${idx < currentStep ? 'bg-green-50 border-green-300' : idx === currentStep ? 'bg-blue-50 border-blue-300' : 'bg-gray-50'}" data-step="${idx}">
                    <div class="flex justify-between items-start">
                        <div class="flex-1">
                            <div class="font-medium text-lg">步骤 ${idx+1}</div>
                            <div class="text-gray-700 mt-2 whitespace-pre-line">${escapeHtml(step)}</div>
                            ${needProof ? '<div class="text-xs text-orange-600 mt-1"><i class="fa-solid fa-check-to-snap mr-1"></i>需要上传证明</div>' : ''}
                            ${helpText ? `<div class="text-xs text-blue-600 mt-1 cursor-pointer help-icon" data-help="${escapeHtml(helpText).replace(/"/g, '&quot;')}"><i class="fa-solid fa-circle-question mr-1"></i>提示</div>` : ''}
                        </div>
                        ${idx === currentStep && !completed ? `
                            <button class="complete-btn bg-blue-600 text-white px-4 py-2 rounded-lg hover:bg-blue-700 transition ml-4" data-step="${idx}" data-need-proof="${needProof}">完成这一步</button>
                        ` : idx < currentStep ? '<span class="text-green-600 text-sm">已完成</span>' : ''}
                    </div>
                </div>
            `}).join('')}
        </div>
        ${completed ? '<div class="mt-4 p-3 bg-green-100 text-green-800 rounded-lg text-center"><i class="fa-solid fa-circle-check mr-1"></i>恭喜！任务已完成！</div>' : ''}
    `;
    document.getElementById('taskContainer').innerHTML = html;
    document.querySelectorAll('.complete-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            pendingStepIndex = parseInt(btn.dataset.step);
            stepNeedProof = btn.dataset.needProof === 'true';
            if (stepNeedProof) {
                document.getElementById('proofModal').classList.remove('hidden');
            } else {
                submitStep('');
            }
        });
    });
    document.querySelectorAll('.help-icon').forEach(icon => {
        icon.addEventListener('click', (e) => {
            const helpText = icon.dataset.help;
            alert(helpText);
        });
    });
}

async function submitStep(proof) {
    if (!currentTask || pendingStepIndex === null) return;
    const res = await fetch('/api/complete_step', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ task_id: currentTask.task_id, step_index: pendingStepIndex, proof: proof })
    });
    const data = await res.json();
    if (res.ok && data.success) {
        if (data.completed && data.advanced_available) {
            if (confirm(`<i class="fa-solid fa-circle-check mr-1"></i>任务完成！是否接受进阶任务：${data.advanced_available.name}？`)) {
                const acceptRes = await fetch('/api/accept_advanced_task', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ task_id: data.advanced_available.task_id })
                });
                if (acceptRes.ok) {
                    alert('已分配进阶任务，请继续学习。');
                    loadTask();
                } else {
                    alert('分配失败，请联系教师。');
                }
            } else {
                alert('已跳过进阶任务，状态保持超前，可等待教师在任务列表中手动分配。');
                loadTask();
            }
        } else {
            loadTask();
        }
    } else {
        alert(data.error || '操作失败');
    }
    pendingStepIndex = null;
}

function startHeartbeat() {
    if (heartbeatInterval) clearInterval(heartbeatInterval);
    heartbeatInterval = setInterval(async () => {
        await fetch('/api/heartbeat', { method: 'POST' });
    }, 30000);
}

async function fetchReminders() {
    const res = await fetch('/api/reminders/unread');
    if (res.status === 401) return;
    const reminders = await res.json();
    if (reminders.length > 0) {
        const latest = reminders[0];
        showToast(latest.message, 'warning');
        await fetch(`/api/reminders/${latest.id}/read`, { method: 'POST' });
        if (reminders.length > 1) {
            setTimeout(() => fetchReminders(), 1000);
        }
    }
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('reminderToast');
    toast.className = `toast toast-${type}`;
    toast.innerText = message;
    toast.classList.remove('hidden');
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 5000);
}

function startReminderPolling() {
    if (reminderInterval) clearInterval(reminderInterval);
    reminderInterval = setInterval(fetchReminders, 30000);
    fetchReminders();
}

// 辅助函数：防止 XSS
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>]/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        return m;
    });
}

// 绑定事件
document.getElementById('refreshTaskBtn').onclick = () => loadTask();
document.getElementById('logoutBtn').onclick = async () => {
    await fetch('/api/logout', { method: 'POST' });
    window.location.href = '/login';
};
document.getElementById('cancelProof').onclick = () => {
    document.getElementById('proofModal').classList.add('hidden');
    pendingStepIndex = null;
};
document.getElementById('submitProof').onclick = () => {
    const proof = document.getElementById('proofContent').value;
    document.getElementById('proofModal').classList.add('hidden');
    submitStep(proof);
    document.getElementById('proofContent').value = '';
};

// 初始化
loadUserInfo();
loadTask();
startReminderPolling();