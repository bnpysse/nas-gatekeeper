// TokenGate Client JavaScript

let currentProvider = 'all';
let currentSearch = '';
let currentRecommendedId = 'qwen3.7-plus';

document.addEventListener('DOMContentLoaded', () => {
    updateRecommendation();
});

// 切换推荐策略与任务
async function updateRecommendation() {
    const task = document.getElementById('sel-task').value;
    const strategy = document.getElementById('sel-strategy').value;

    try {
        const res = await fetch(`/api/recommend?task=${task}&strategy=${strategy}`);
        if (res.ok) {
            const data = await res.json();
            const model = data.recommended_model;
            currentRecommendedId = model.id;

            document.getElementById('rec-name').textContent = model.name;
            document.getElementById('rec-provider').textContent = model.provider;
            document.getElementById('rec-reason').textContent = data.reason;
        }
    } catch (e) {
        console.error('Failed to fetch recommendation', e);
    }
}

// 平台 Tab 过滤
function filterProvider(providerId) {
    currentProvider = providerId;
    document.querySelectorAll('.tab-btn').forEach(btn => {
        if (btn.getAttribute('data-target') === providerId) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    applyFilters();
}

// 模糊搜索模型
function searchModels() {
    currentSearch = document.getElementById('model-search').value.toLowerCase().trim();
    applyFilters();
}

function applyFilters() {
    const cards = document.querySelectorAll('.model-card');
    cards.forEach(card => {
        const p = card.getAttribute('data-provider');
        const id = card.getAttribute('data-model-id').toLowerCase();
        const name = card.getAttribute('data-model-name').toLowerCase();

        const matchProvider = (currentProvider === 'all' || p === currentProvider);
        const matchSearch = (!currentSearch || id.includes(currentSearch) || name.includes(currentSearch));

        if (matchProvider && matchSearch) {
            card.style.display = 'flex';
        } else {
            card.style.display = 'none';
        }
    });
}

// 复制工具函数
function copyText(text) {
    navigator.clipboard.writeText(text).then(() => {
        showToast(`已复制: ${text}`);
    }).catch(() => {
        prompt('请手动复制:', text);
    });
}

function copyRecommendedModel() {
    copyText(currentRecommendedId);
}

function copyProxyCurl() {
    const curl = `curl http://localhost:8800/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model": "auto", "messages": [{"role": "user", "content": "你好"}]}'`;
    copyText(curl);
}

// 手动刷新探测
async function refreshData() {
    const icon = document.getElementById('icon-refresh');
    icon.classList.add('animate-spin');
    try {
        await fetch('/api/quotas?refresh=true');
        location.reload();
    } catch (e) {
        alert('刷新失败: ' + e);
    } finally {
        icon.classList.remove('animate-spin');
    }
}

// 轻量 Toast 提示
function showToast(msg) {
    const div = document.createElement('div');
    div.className = 'fixed bottom-6 right-6 px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-medium shadow-xl z-50 transition-all duration-300 transform translate-y-2 opacity-0';
    div.textContent = msg;
    document.body.appendChild(div);

    setTimeout(() => {
        div.classList.remove('translate-y-2', 'opacity-0');
    }, 10);

    setTimeout(() => {
        div.classList.add('translate-y-2', 'opacity-0');
        setTimeout(() => div.remove(), 300);
    }, 2000);
}
