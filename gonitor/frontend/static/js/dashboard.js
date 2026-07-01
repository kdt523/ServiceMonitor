/**
 * dashboard.js — Gonitor real-time dashboard
 *
 * Responsibilities:
 * - Initialize Pusher and subscribe to channels
 * - Handle "Add Resource" form submission via fetch
 * - Handle "Check Now" button clicks
 * - Handle "Delete" button clicks with confirmation
 * - Update DOM badge, response time, and last-checked cells live
 * - Show toast notifications on status changes
 */

/* ─────────────────────────────────────────────────────
   Pusher Setup
   ───────────────────────────────────────────────────── */

// Pusher key is injected by the template or fetched from the API
(async function initPusher() {
  let pusherKey = '';
  let pusherCluster = 'ap2';

  try {
    const resp = await fetch('/api/pusher-config');
    if (resp.ok) {
      const cfg = await resp.json();
      pusherKey = cfg.key;
      pusherCluster = cfg.cluster;
    }
  } catch (_) {
    // Pusher config endpoint not available (skip real-time)
  }

  if (!pusherKey) {
    console.warn('[Gonitor] Pusher key not configured — real-time updates disabled.');
    return;
  }

  Pusher.logToConsole = false;
  const pusher = new Pusher(pusherKey, { cluster: pusherCluster });

  // Global channel — receives every completed check
  const globalChannel = pusher.subscribe('gonitor-global');
  globalChannel.bind('check-completed', (data) => {
    updateResourceRow(data.resource_id, data.status, data.response_time_ms);
  });

  // Per-resource channels — receive status-change events
  document.querySelectorAll('[data-resource-id]').forEach((row) => {
    const id = row.dataset.resourceId;
    const channel = pusher.subscribe(`resource-${id}`);
    channel.bind('status-change', (data) => {
      showToast(data);
      updateStatusBadge(data.resource_id, data.new_status);
    });
  });
})();


/* ─────────────────────────────────────────────────────
   DOM Update Helpers
   ───────────────────────────────────────────────────── */

function updateResourceRow(resourceId, status, responseTimeMs) {
  updateStatusBadge(resourceId, status);

  const respCell = document.getElementById(`resp-${resourceId}`);
  if (respCell) {
    respCell.textContent = responseTimeMs != null ? `${responseTimeMs} ms` : '—';
  }

  const lastCell = document.getElementById(`last-${resourceId}`);
  if (lastCell) {
    const now = new Date();
    const timeStr = now.toTimeString().slice(0, 8);
    lastCell.innerHTML = `<span title="${now.toISOString()}">${timeStr}</span>`;
  }
}

function updateStatusBadge(resourceId, status) {
  const badge = document.getElementById(`badge-${resourceId}`);
  if (!badge) return;

  badge.className = `status-badge status-${status}`;

  const icons = { up: 'bi-check-circle-fill', down: 'bi-x-circle-fill', unknown: 'bi-question-circle' };
  const icon = icons[status] || 'bi-question-circle';
  badge.innerHTML = `<i class="bi ${icon}"></i> ${status.toUpperCase()}`;

  // Briefly highlight the row
  const row = document.getElementById(`row-${resourceId}`);
  if (row) {
    row.style.transition = 'background 0.4s ease';
    row.style.background = status === 'up'
      ? 'rgba(63,185,80,0.08)'
      : status === 'down'
        ? 'rgba(248,81,73,0.08)'
        : 'transparent';
    setTimeout(() => { row.style.background = ''; }, 1500);
  }
}


/* ─────────────────────────────────────────────────────
   Toast Notifications
   ───────────────────────────────────────────────────── */

function showToast(data) {
  const color   = data.new_status === 'up' ? 'success' : 'danger';
  const icon    = data.new_status === 'up' ? '✅' : '🔴';
  const toastId = `toast-${Date.now()}`;

  const el = document.createElement('div');
  el.id = toastId;
  el.className = `alert alert-${color} alert-dismissible fade show gonitor-toast`;
  el.role = 'alert';
  el.innerHTML = `
    ${icon} <strong>${escHtml(data.name)}</strong> is now
    <strong>${data.new_status.toUpperCase()}</strong>
    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="alert" aria-label="Close"></button>
  `;

  const container = document.getElementById('toast-container');
  container.appendChild(el);

  // Auto-remove after 5 seconds
  setTimeout(() => {
    el.classList.remove('show');
    setTimeout(() => el.remove(), 300);
  }, 5000);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}


/* ─────────────────────────────────────────────────────
   Add Resource (Modal Form via fetch)
   ───────────────────────────────────────────────────── */

const saveBtn = document.getElementById('save-resource-btn');
if (saveBtn) {
  saveBtn.addEventListener('click', async () => {
    const form    = document.getElementById('add-resource-form');
    const errDiv  = document.getElementById('form-error');
    errDiv.classList.add('d-none');

    const name             = form.querySelector('#res-name').value.trim();
    const resource_type    = form.querySelector('#res-type').value;
    const url              = form.querySelector('#res-url').value.trim();
    const interval_minutes = parseInt(form.querySelector('#res-interval').value, 10);

    if (!name || !url) {
      errDiv.textContent = 'Name and URL are required.';
      errDiv.classList.remove('d-none');
      return;
    }

    saveBtn.disabled = true;
    saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Adding…';

    try {
      const resp = await fetch('/resources', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ name, resource_type, url, interval_minutes }),
      });

      if (resp.ok) {
        // Reload to show the new resource row
        location.reload();
      } else {
        const data = await resp.json().catch(() => ({}));
        errDiv.textContent = data.detail || `Error ${resp.status}`;
        errDiv.classList.remove('d-none');
      }
    } catch (e) {
      errDiv.textContent = 'Network error. Please try again.';
      errDiv.classList.remove('d-none');
    } finally {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<i class="bi bi-plus-circle me-2"></i>Add Resource';
    }
  });
}


/* ─────────────────────────────────────────────────────
   Check Now Buttons
   ───────────────────────────────────────────────────── */

document.querySelectorAll('.check-now-btn').forEach((btn) => {
  btn.addEventListener('click', async () => {
    const resourceId = btn.dataset.resourceId;
    const origHtml   = btn.innerHTML;

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

    try {
      const resp = await fetch(`/resources/${resourceId}/check-now`, { method: 'POST' });
      if (resp.ok) {
        const data = await resp.json();
        updateResourceRow(resourceId, data.status, data.response_time_ms);
      }
    } catch (e) {
      console.error('[Gonitor] check-now error:', e);
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  });
});


/* ─────────────────────────────────────────────────────
   Delete Buttons
   ───────────────────────────────────────────────────── */

let pendingDeleteId = null;

document.querySelectorAll('.delete-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    pendingDeleteId = btn.dataset.resourceId;
    document.getElementById('delete-resource-name').textContent = btn.dataset.resourceName;
    new bootstrap.Modal(document.getElementById('deleteModal')).show();
  });
});

const confirmDeleteBtn = document.getElementById('confirm-delete-btn');
if (confirmDeleteBtn) {
  confirmDeleteBtn.addEventListener('click', async () => {
    if (!pendingDeleteId) return;

    confirmDeleteBtn.disabled = true;
    confirmDeleteBtn.textContent = 'Deleting…';

    try {
      const resp = await fetch(`/resources/${pendingDeleteId}`, { method: 'DELETE' });
      if (resp.ok || resp.status === 204) {
        // Remove the row immediately
        const row = document.getElementById(`row-${pendingDeleteId}`);
        if (row) {
          row.style.transition = 'opacity 0.3s ease';
          row.style.opacity = '0';
          setTimeout(() => row.remove(), 300);
        }
        bootstrap.Modal.getInstance(document.getElementById('deleteModal')).hide();
      }
    } catch (e) {
      console.error('[Gonitor] delete error:', e);
    } finally {
      confirmDeleteBtn.disabled = false;
      confirmDeleteBtn.textContent = 'Delete';
      pendingDeleteId = null;
    }
  });
}


/* ─────────────────────────────────────────────────────
   Type selector hint update
   ───────────────────────────────────────────────────── */

const typeSelect = document.getElementById('res-type');
const urlInput   = document.getElementById('res-url');
const urlHint    = document.getElementById('url-hint');

if (typeSelect) {
  typeSelect.addEventListener('change', () => {
    if (typeSelect.value === 'tcp') {
      urlInput.placeholder = 'tcp://hostname:5432';
      urlHint.textContent  = 'Format: tcp://hostname:port';
    } else {
      urlInput.placeholder = 'https://example.com';
      urlHint.textContent  = 'Include http:// or https://';
    }
  });
}
