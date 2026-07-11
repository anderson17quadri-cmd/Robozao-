// robozão dashboard — polling simples do /api/state + toggle do bot
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const modo = window.MODO || {};

  function fmtUsd(v) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    const s = (v < 0 ? "-" : "") + "$" + Math.abs(v).toFixed(2);
    return s;
  }
  function fmtPrice(v) {
    if (!v) return "—";
    if (v < 0.000001) return "$" + v.toExponential(2);
    if (v < 1) return "$" + v.toFixed(8);
    return "$" + v.toFixed(4);
  }
  function fmtPct(v) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return (v >= 0 ? "+" : "") + v.toFixed(1) + "%";
  }
  function ago(epoch) {
    if (!epoch) return "";
    const s = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
    return Math.floor(s / 3600) + "h";
  }
  function shortMint(m) {
    if (!m) return "";
    return m.slice(0, 4) + "…" + m.slice(-4);
  }
  function signClass(v) {
    return (v || 0) >= 0 ? "up" : "down";
  }

  function posicaoCard(p) {
    const cls = signClass(p.pl_pct);
    return `
      <div class="card ${cls}">
        <div>
          <div class="name">${escapeHtml(p.name || "?")}</div>
          <div class="mint">${shortMint(p.mint)}</div>
        </div>
        <div class="pl ${cls}">${fmtPct(p.pl_pct)}</div>
        <div class="meta">
          <span>entrada ${fmtPrice(p.entry_price)}</span>
          <span>agora ${fmtPrice(p.current_price)}</span>
          <span>${fmtUsd(p.pl_usd)}</span>
          <span>há ${ago(p.opened_at)}</span>
        </div>
      </div>`;
  }

  function histCard(h) {
    const cls = signClass(h.pl_pct);
    return `
      <div class="card ${cls}">
        <div>
          <div class="name">${escapeHtml(h.name || "?")}
            <span class="tag ${h.motivo_saida || ""}">${escapeHtml(h.motivo_saida || "")}</span>
          </div>
          <div class="mint">${shortMint(h.mint)}</div>
        </div>
        <div class="pl ${cls}">${fmtPct(h.pl_pct)}</div>
        <div class="meta">
          <span>entrada ${fmtPrice(h.entry_price)}</span>
          <span>saída ${fmtPrice(h.exit_price)}</span>
          <span>${fmtUsd(h.pl_usd)}</span>
        </div>
      </div>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function render(state) {
    $("kpiSaldo").textContent = fmtUsd(state.saldo_usd);
    $("kpiTotal").textContent = fmtUsd(state.valor_total_usd);

    const plA = $("kpiPlAberto");
    plA.textContent = fmtUsd(state.pl_aberto_usd);
    plA.className = "kpi-val " + signClass(state.pl_aberto_usd);
    const plR = $("kpiPlReal");
    plR.textContent = fmtUsd(state.pl_realizado_usd);
    plR.className = "kpi-val " + signClass(state.pl_realizado_usd);

    // posições
    const pos = state.posicoes || [];
    $("countPos").textContent = pos.length;
    $("posVazio").style.display = pos.length ? "none" : "block";
    $("posicoes").innerHTML = pos.map(posicaoCard).join("");

    // histórico
    const hist = state.historico || [];
    $("countHist").textContent = hist.length;
    $("histVazio").style.display = hist.length ? "none" : "block";
    $("historico").innerHTML = hist.map(histCard).join("");

    // toggle
    const btn = $("toggleBtn");
    if (state.bot_running) {
      btn.classList.add("on"); btn.classList.remove("off");
      btn.querySelector(".lbl").textContent = "DESLIGAR BOT";
    } else {
      btn.classList.add("off"); btn.classList.remove("on");
      btn.querySelector(".lbl").textContent = "LIGAR BOT";
    }
    $("statusLine").textContent = state.ultima_msg || (state.bot_running ? "a correr" : "bot parado");
  }

  async function poll() {
    try {
      const r = await fetch("/api/state");
      if (r.ok) render(await r.json());
    } catch (e) { /* ignora — tenta outra vez */ }
  }

  async function toggle(confirmarReal) {
    try {
      const r = await fetch("/api/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ acao: "toggle", confirmar_real: !!confirmarReal }),
      });
      if (r.status === 409) {
        const d = await r.json();
        showModal(d.aviso || "Confirmar modo real?");
        return;
      }
      await poll();
    } catch (e) { /* ignora */ }
  }

  function showModal(msg) {
    $("modalMsg").textContent = msg;
    $("modal").classList.remove("hidden");
  }
  function hideModal() { $("modal").classList.add("hidden"); }

  // eventos
  $("toggleBtn").addEventListener("click", () => toggle(false));
  $("modalCancel").addEventListener("click", hideModal);
  $("modalOk").addEventListener("click", () => { hideModal(); toggle(true); });

  poll();
  setInterval(poll, 2500);
})();
