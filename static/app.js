/* Ki Ki Shop – frontend */

function showAlert(elOrId, msg, type) {
  const el = typeof elOrId === 'string' ? document.getElementById(elOrId) : elOrId;
  if (!el) return;
  el.className = 'alert ' + (type || 'info');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function hideAlert(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('hidden');
}

function toast(msg) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
  setTimeout(() => el.classList.add('hidden'), 2800);
}

function fmt(n) {
  return Number(n || 0).toLocaleString('en-US');
}

function setBalance(n) {
  if (window.SHOP_CFG) window.SHOP_CFG.balance = n;
  const chip = document.getElementById('balChip');
  if (chip) chip.textContent = '💰 ' + fmt(n) + ' Coins';
}

// ----- Tabs -----
document.querySelectorAll('.tab').forEach((tab) => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach((p) => p.classList.remove('active'));
    tab.classList.add('active');
    const panel = document.getElementById('panel-' + tab.dataset.tab);
    if (panel) panel.classList.add('active');
    if (tab.dataset.tab === 'history') loadHistory();
  });
});

// ----- Logout -----
const btnLogout = document.getElementById('btnLogout');
if (btnLogout) {
  btnLogout.addEventListener('click', async () => {
    await fetch('/api/logout', { method: 'POST' });
    window.location.href = '/login';
  });
}

// ----- Packages -----
let packages = [];
let selectedIdx = null;

async function loadPackages(refresh) {
  const grid = document.getElementById('pkgGrid');
  if (!grid) return;
  grid.innerHTML = '<div class="skeleton">Packages တင်နေသည်...</div>';
  try {
    const url = '/api/packages' + (refresh ? '?refresh=1' : '');
    const res = await fetch(url);
    const data = await res.json();
    if (!data.ok) {
      grid.innerHTML = '<div class="skeleton">' + (data.error || 'မရပါ') + '</div>';
      return;
    }
    packages = data.packages || [];
    if (!packages.length) {
      grid.innerHTML = '<div class="skeleton">Package မရှိပါ</div>';
      return;
    }
    grid.innerHTML = '';
    packages.forEach((p, i) => {
      const card = document.createElement('div');
      card.className = 'pkg-card';
      card.innerHTML =
        '<div class="name">' +
        escapeHtml(p.name) +
        '</div><div class="price">' +
        fmt(p.mmk_price) +
        ' Coins</div>';
      card.addEventListener('click', () => openBuyModal(i));
      grid.appendChild(card);
    });
  } catch (e) {
    grid.innerHTML = '<div class="skeleton">Network error</div>';
  }
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

const btnRefreshPkgs = document.getElementById('btnRefreshPkgs');
if (btnRefreshPkgs) {
  btnRefreshPkgs.addEventListener('click', () => loadPackages(true));
}

// ----- Buy Modal -----
function openBuyModal(idx) {
  selectedIdx = idx;
  const p = packages[idx];
  if (!p) return;
  document.getElementById('modalTitle').textContent = p.name;
  document.getElementById('modalPrice').textContent = fmt(p.mmk_price) + ' Coins';
  document.getElementById('gameUid').value = '';
  document.getElementById('zoneId').value = '';
  document.getElementById('idResult').classList.add('hidden');
  hideAlert('buyAlert');
  document.getElementById('buyModal').classList.remove('hidden');
}

const modalClose = document.getElementById('modalClose');
if (modalClose) {
  modalClose.addEventListener('click', () => {
    document.getElementById('buyModal').classList.add('hidden');
  });
}

const btnCheckId = document.getElementById('btnCheckId');
if (btnCheckId) {
  btnCheckId.addEventListener('click', async () => {
    const game_uid = document.getElementById('gameUid').value.trim();
    const zone_id = document.getElementById('zoneId').value.trim();
    const pid = packages[selectedIdx] && packages[selectedIdx].pid;
    btnCheckId.disabled = true;
    try {
      const res = await fetch('/api/check_id', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ game_uid, zone_id, pid }),
      });
      const data = await res.json();
      const box = document.getElementById('idResult');
      if (data.ok) {
        box.classList.remove('hidden');
        box.innerHTML =
          '✅ <b>' +
          escapeHtml(data.username) +
          '</b><br>🌍 ' +
          escapeHtml(data.region) +
          '<br>⭐ WP: ' +
          data.wp_bought +
          ' / 10 (ကျန် ' +
          data.wp_left +
          ')';
      } else {
        box.classList.remove('hidden');
        box.innerHTML = '❌ ' + escapeHtml(data.error || 'မမှန်ပါ');
      }
    } catch (e) {
      showAlert('buyAlert', 'Network error', 'error');
    } finally {
      btnCheckId.disabled = false;
    }
  });
}

const buyForm = document.getElementById('buyForm');
if (buyForm) {
  buyForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('btnBuy');
    btn.disabled = true;
    btn.textContent = 'လုပ်ဆောင်နေသည်...';
    hideAlert('buyAlert');
    try {
      const res = await fetch('/api/buy', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          package_index: selectedIdx,
          game_uid: document.getElementById('gameUid').value.trim(),
          zone_id: document.getElementById('zoneId').value.trim(),
        }),
      });
      const data = await res.json();
      if (data.ok) {
        setBalance(data.balance);
        showAlert('buyAlert', data.message || 'အောင်မြင်ပါသည်!', 'success');
        toast('✅ Top-up အောင်မြင်');
        setTimeout(() => {
          document.getElementById('buyModal').classList.add('hidden');
        }, 2000);
      } else {
        if (typeof data.balance === 'number') setBalance(data.balance);
        showAlert(
          'buyAlert',
          data.message || data.error || 'မအောင်မြင်ပါ',
          'error'
        );
      }
    } catch (err) {
      showAlert('buyAlert', 'Network error', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = '🛒 Coin ဖြင့် ဝယ်မည်';
    }
  });
}

// ----- Recharge -----
document.querySelectorAll('.copy-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    const t = btn.getAttribute('data-copy');
    navigator.clipboard.writeText(t).then(() => toast('Copied: ' + t));
  });
});

const rechargeForm = document.getElementById('rechargeForm');
if (rechargeForm) {
  rechargeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('btnRecharge');
    btn.disabled = true;
    hideAlert('rechargeAlert');
    try {
      const res = await fetch('/api/recharge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          method: document.getElementById('rMethod').value,
          amount: document.getElementById('rAmount').value,
          last5: document.getElementById('rLast5').value.trim(),
          note: document.getElementById('rNote').value.trim(),
        }),
      });
      const data = await res.json();
      if (data.ok) {
        showAlert(
          'rechargeAlert',
          data.message +
            (data.admin_notified ? ' (Admin notified)' : ' (Admin notify failed – check BOT_TOKEN)'),
          'success'
        );
        rechargeForm.reset();
      } else {
        showAlert('rechargeAlert', data.error || 'မအောင်မြင်ပါ', 'error');
      }
    } catch (err) {
      showAlert('rechargeAlert', 'Network error', 'error');
    } finally {
      btn.disabled = false;
    }
  });
}

// ----- History -----
async function loadHistory() {
  const oEl = document.getElementById('histOrders');
  const rEl = document.getElementById('histRecharges');
  if (!oEl) return;
  oEl.innerHTML = '<p class="hint">Loading...</p>';
  try {
    const res = await fetch('/api/history');
    const data = await res.json();
    if (!data.ok) {
      oEl.innerHTML = '<p class="hint">မရပါ</p>';
      return;
    }
    let oh = '<div class="hist-block"><h3>📦 Orders</h3>';
    if (!data.orders.length) oh += '<p class="hint">မရှိသေးပါ</p>';
    data.orders.forEach((o) => {
      oh +=
        '<div class="hist-item"><span class="badge ' +
        o.status +
        '">' +
        o.status +
        '</span> #' +
        o.id +
        ' · ' +
        escapeHtml(o.item_name) +
        '<br>💰 ' +
        fmt(o.amount) +
        ' · 🎮 ' +
        escapeHtml(o.game_id) +
        '<br><span class="muted">' +
        escapeHtml(o.created_at) +
        '</span></div>';
    });
    oh += '</div>';
    oEl.innerHTML = oh;

    let rh = '<div class="hist-block"><h3>💳 Recharges</h3>';
    if (!data.recharges.length) rh += '<p class="hint">မရှိသေးပါ</p>';
    data.recharges.forEach((r) => {
      rh +=
        '<div class="hist-item"><span class="badge ' +
        r.status +
        '">' +
        r.status +
        '</span> #' +
        r.id +
        ' · ' +
        fmt(r.amount) +
        ' MMK (' +
        escapeHtml(r.payment_method) +
        ')<br>Last5: ' +
        escapeHtml(r.last_5_digits) +
        '<br><span class="muted">' +
        escapeHtml(r.created_at) +
        '</span></div>';
    });
    rh += '</div>';
    rEl.innerHTML = rh;
  } catch (e) {
    oEl.innerHTML = '<p class="hint">Network error</p>';
  }
}

const btnRefreshHist = document.getElementById('btnRefreshHist');
if (btnRefreshHist) btnRefreshHist.addEventListener('click', loadHistory);

// ----- PIN -----
const pinForm = document.getElementById('pinForm');
if (pinForm) {
  pinForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideAlert('pinAlert');
    try {
      const res = await fetch('/api/set_pin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin: document.getElementById('newPin').value }),
      });
      const data = await res.json();
      if (data.ok) {
        showAlert('pinAlert', data.message || 'OK', 'success');
        pinForm.reset();
      } else {
        showAlert('pinAlert', data.error || 'Fail', 'error');
      }
    } catch (err) {
      showAlert('pinAlert', 'Network error', 'error');
    }
  });
}

// Init shop page
if (document.getElementById('pkgGrid')) {
  loadPackages(false);
}
