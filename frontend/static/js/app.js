/**
 * app.js — Global WebSocket manager + monitoring toggle for ServiceMonitor.
 *
 * - Connects a native WebSocket to /ws
 * - Handles the monitoring ON/OFF toggle in the navbar
 * - Broadcasts connection state to all registered handlers
 */

(function () {
  'use strict';

  let ws = null;
  let reconnectTimer = null;
  const RECONNECT_MS = 4000;

  // ── WebSocket lifecycle ───────────────────────────────────────────────────

  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const url = `${proto}://${location.host}/ws`;

    ws = new WebSocket(url);

    ws.addEventListener('open', () => {
      console.debug('[ServiceMonitor WS] Connected');
      clearTimeout(reconnectTimer);
      // Notify any page-level handlers that the WS is ready
      if (window._servicemonitorReady) {
        window._servicemonitorReady.forEach(fn => fn(ws));
      }
    });

    ws.addEventListener('close', () => {
      console.debug('[ServiceMonitor WS] Disconnected — reconnecting in', RECONNECT_MS, 'ms');
      reconnectTimer = setTimeout(connect, RECONNECT_MS);
    });

    ws.addEventListener('error', err => {
      console.warn('[ServiceMonitor WS] Error:', err);
    });

    ws.addEventListener('message', e => {
      try {
        const msg = JSON.parse(e.data);
        handleGlobalEvent(msg);
      } catch (_) {}
    });
  }

  // ── Global event handler ──────────────────────────────────────────────────

  function handleGlobalEvent(msg) {
    const { event, data } = msg;

    if (event === 'host-service-status-changed') {
      showToast(
        data.new_status === 'healthy'
          ? `✅ ${data.host_name} / ${data.service_type.toUpperCase()} — Recovered`
          : data.new_status === 'warning'
          ? `⚠️ ${data.host_name} / ${data.service_type.toUpperCase()} — Warning`
          : `🔴 ${data.host_name} / ${data.service_type.toUpperCase()} — Problem`,
        data.new_status
      );
    }

    if (event === 'monitoring-toggled') {
      updateMonitoringToggle(data.enabled);
    }

    if (event === 'app-starting') {
      console.info('[ServiceMonitor] App starting');
    }
  }

  // ── Toast notifications ───────────────────────────────────────────────────

  function showToast(message, status) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const colorMap = {
      healthy: '#3fb950',
      warning: '#d29922',
      problem: '#f85149',
    };
    const color = colorMap[status] || '#8b949e';

    const toast = document.createElement('div');
    toast.className = 'g-toast';
    toast.style.borderLeft = `3px solid ${color}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.transition = 'opacity .4s';
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 400);
    }, 4000);
  }

  // ── Monitoring toggle ─────────────────────────────────────────────────────

  function updateMonitoringToggle(enabled) {
    const dot = document.getElementById('monitor-dot');
    const label = document.getElementById('monitor-label');
    if (!dot || !label) return;
    if (enabled) {
      dot.classList.remove('off');
      label.textContent = 'Monitoring ON';
    } else {
      dot.classList.add('off');
      label.textContent = 'Monitoring OFF';
    }
  }

  async function initMonitoringToggle() {
    // Fetch current state
    try {
      const r = await fetch('/api/monitoring/status');
      const d = await r.json();
      updateMonitoringToggle(d.monitoring_enabled);
    } catch (_) {}

    const toggleEl = document.getElementById('monitoring-toggle');
    if (toggleEl) {
      toggleEl.addEventListener('click', async () => {
        try {
          const r = await fetch('/settings/monitoring/toggle', { method: 'POST' });
          const d = await r.json();
          updateMonitoringToggle(d.monitoring_enabled);
        } catch (e) {
          console.warn('Toggle failed:', e);
        }
      });
    }
  }

  // ── Sidebar mobile toggle ─────────────────────────────────────────────────

  function initSidebarToggle() {
    const btn = document.getElementById('sidebar-toggle');
    const sidebar = document.getElementById('sidebar');
    if (btn && sidebar) {
      btn.addEventListener('click', () => sidebar.classList.toggle('open'));
    }
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', () => {
    connect();
    initMonitoringToggle();
    initSidebarToggle();
  });

  // Expose helpers globally for page scripts
  window.servicemonitorShowToast = showToast;
})();

class LocalTime extends HTMLElement {
  connectedCallback() {
    const utcVal = this.getAttribute('datetime');
    if (!utcVal) return;
    
    const showSeconds = this.hasAttribute('seconds');
    const date = new Date(utcVal);
    this.textContent = date.toLocaleString(undefined, {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: showSeconds ? '2-digit' : undefined,
      hour12: false
    });
  }
}
customElements.define('local-time', LocalTime);
