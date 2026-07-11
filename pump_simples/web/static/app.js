// robozão dashboard — polling do /api/state + ações (toggle, venda manual, meta)
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const MODO = window.MODO || {};
  const REAL = !!MODO.envio_real_armado;
  const SIM = MODO.moeda_simbolo || "€";   // símbolo da carteira (saldo/P&L)

  // ---------- formatação ----------
  // valores da CARTEIRA (saldo, P/L, valor investido) — na moeda simulada
  function fmtUsd(v) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return (v < 0 ? "-" : "") + SIM + Math.abs(v).toFixed(2);
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
    if (s < 3600) return Math.floor(s / 60) + "m";
    return Math.floor(s / 3600) + "h";
  }
  function shortMint(m) { return m ? m.slice(0, 4) + "…" + m.slice(-4) : ""; }
  function signClass(v) { return (v || 0) >= 0 ? "up" : "down"; }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function pumpLink(mint, texto) {
    // nome/símbolo do token abre a página do pump.fun (via delegação — ver abaixo).
    // Usa span+data-mint em vez de <a>, para o re-render de 2.5s não "comer" o toque.
    if (!mint) return escapeHtml(texto);
    return `<span class="tok-link" data-mint="${escapeHtml(mint)}" role="link" tabindex="0">${escapeHtml(texto)} ↗</span>`;
  }

  function openPump(mint) {
    if (mint) window.open("https://pump.fun/coin/" + encodeURIComponent(mint), "_blank", "noopener");
  }

  // ---------- cards ----------
  function posicaoCard(p) {
    const cls = signClass(p.pl_pct);
    const meta = (p.meta_lucro_pct !== null && p.meta_lucro_pct !== undefined) ? p.meta_lucro_pct : "";
    const alvoNum = meta !== "" ? Number(meta) : Number(MODO.take_profit_pct || 0);
    const alvoTxt = alvoNum > 0
      ? `meta: +${alvoNum.toFixed(0)}%`
      : `só trailing −${Number(MODO.trailing_stop_pct || 30).toFixed(0)}% do pico`;
    return `
      <div class="card ${cls}" data-id="${p.id}">
        <div>
          <div class="name">${pumpLink(p.mint, p.name || "?")}</div>
          <div class="mint">${shortMint(p.mint)}</div>
        </div>
        <div class="pl ${cls}">${fmtPct(p.pl_pct)}</div>
        <div class="meta">
          <span>entrada ${fmtPrice(p.entry_price)}</span>
          <span>agora ${fmtPrice(p.current_price)}</span>
          <span>${fmtUsd(p.pl_usd)}</span>
          <span>há ${ago(p.opened_at)}</span>
        </div>
        <div class="actions">
          <div class="meta-edit">
            <label>meta venda %</label>
            <input type="number" class="meta-input" value="${meta}"
                   placeholder="${MODO.take_profit_pct}" step="1" min="0">
            <button class="btn-mini btn-save" data-act="meta" data-id="${p.id}">ok</button>
            <span class="meta-hint">${alvoTxt}</span>
          </div>
          <button class="btn-sell" data-act="sell" data-id="${p.id}"
                  data-name="${escapeHtml(p.name || "?")}">Vender 100%</button>
        </div>
      </div>`;
  }

  function histCard(h) {
    const cls = signClass(h.pl_pct);                 // resultado do trade (realizado)
    const posCls = signClass(h.var_pos_venda_pct);   // evolução DEPOIS da venda
    const temPos = h.var_pos_venda_pct !== null && h.var_pos_venda_pct !== undefined;
    return `
      <div class="card ${cls}">
        <div>
          <div class="name">
            ${pumpLink(h.mint, h.name || "?")}
            <span class="badge-sold">já vendido</span>
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
        ${temPos ? `
        <div class="postsale ${posCls}">
          <span class="ps-label">desde a venda</span>
          <span class="ps-val">${fmtPct(h.var_pos_venda_pct)}</span>
          <span class="ps-now">agora ${fmtPrice(h.preco_pos_venda)}</span>
          <span class="ps-ago">${ago(h.pos_venda_atualizado_em)}</span>
        </div>` : ""}
      </div>`;
  }

  // ---------- render ----------
  function editingPositions() {
    // não re-renderizar as posições enquanto o utilizador edita a meta (não perder o input)
    const a = document.activeElement;
    return a && a.classList && a.classList.contains("meta-input");
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

    const pos = state.posicoes || [];
    $("countPos").textContent = pos.length;
    $("posVazio").style.display = pos.length ? "none" : "block";
    if (!editingPositions()) {
      $("posicoes").innerHTML = pos.map(posicaoCard).join("");
    }

    const hist = state.historico || [];
    $("countHist").textContent = hist.length;
    $("histVazio").style.display = hist.length ? "none" : "block";
    $("historico").innerHTML = hist.map(histCard).join("");

    const btn = $("toggleBtn");
    if (state.bot_running) {
      btn.classList.add("on"); btn.classList.remove("off");
      btn.querySelector(".lbl").textContent = "DESLIGAR BOT";
    } else {
      btn.classList.add("off"); btn.classList.remove("on");
      btn.querySelector(".lbl").textContent = "LIGAR BOT";
    }
    $("statusLine").textContent = state.ultima_msg || (state.bot_running ? "a correr" : "bot parado");

    // valor por entrada — não sobrescreve enquanto o utilizador escreve
    $("cfgCur").textContent = SIM;
    const ti = $("tradeInput");
    if (document.activeElement !== ti && state.max_trade_usd !== undefined) {
      ti.value = state.max_trade_usd;
    }
    // rodapé "trade máx" ao vivo (reflete o valor guardado, não o do .env)
    const ft = $("footTrade");
    if (ft && state.max_trade_usd !== undefined) ft.textContent = SIM + Number(state.max_trade_usd).toFixed(0);
  }

  async function poll() {
    try {
      const r = await fetch("/api/state");
      if (r.ok) render(await r.json());
    } catch (e) { /* tenta outra vez */ }
  }

  // ---------- ações ----------
  async function toggle(confirmarReal) {
    try {
      const r = await fetch("/api/toggle", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ acao: "toggle", confirmar_real: !!confirmarReal }),
      });
      if (r.status === 409) {
        const d = await r.json();
        showConfirm("⚠️ Confirmar arranque em MODO REAL", d.aviso, true,
          () => toggle(true));
        return;
      }
      await poll();
    } catch (e) { /* ignora */ }
  }

  async function venderPosicao(id, nome) {
    const titulo = REAL ? "⚠️ Vender em MODO REAL" : "Confirmar venda";
    const msg = `Vender 100% de "${nome}" agora?` +
      (REAL ? " Isto envia uma transação real." : " (simulado, DRY_RUN)");
    showConfirm(titulo, msg, REAL, async () => {
      try {
        const r = await fetch(`/api/posicao/${id}/vender`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmar_real: REAL }),
        });
        await r.json().catch(() => ({}));
        await poll();
      } catch (e) { /* ignora */ }
    });
  }

  async function salvarMeta(id, valor) {
    try {
      await fetch(`/api/posicao/${id}/meta`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meta_lucro_pct: valor === "" ? null : valor }),
      });
      await poll();
    } catch (e) { /* ignora */ }
  }

  // ---------- modal de confirmação (genérico) ----------
  let pendingConfirm = null;
  function showConfirm(titulo, msg, mostrarWarn, fn) {
    $("modalTitle").textContent = titulo;
    $("modalMsg").textContent = msg;
    $("modalWarn").style.display = mostrarWarn ? "block" : "none";
    pendingConfirm = fn;
    $("modal").classList.remove("hidden");
  }
  function hideModal() { $("modal").classList.add("hidden"); pendingConfirm = null; }

  async function reiniciar() {
    showConfirm("Reiniciar simulação",
      `Repor o saldo a ${SIM}${Number(MODO.saldo_inicial || 1000).toFixed(0)} e limpar ` +
      `posições e histórico? (só afeta a simulação, nada on-chain)`, false,
      async () => {
        try {
          const r = await fetch("/api/reset", { method: "POST" });
          if (r.status === 409) {
            showConfirm("Bot ligado", "Desliga o bot antes de reiniciar.", false, null);
            return;
          }
          await poll();
        } catch (e) { /* ignora */ }
      });
  }

  async function salvarValorEntrada() {
    // aceita vírgula decimal (PT): "2,5" -> "2.5"
    const v = $("tradeInput").value.trim().replace(",", ".");
    const n = Number(v);
    if (v === "" || isNaN(n) || n <= 0) return;
    const btn = $("tradeSave");
    try {
      const r = await fetch("/api/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ max_trade_usd: v }),
      });
      if (btn) { btn.textContent = r.ok ? "✓" : "erro"; setTimeout(() => { btn.textContent = "ok"; }, 1200); }
      $("tradeInput").blur();
      await poll();
    } catch (e) { if (btn) btn.textContent = "erro"; }
  }

  // ---------- eventos ----------
  $("toggleBtn").addEventListener("click", () => toggle(false));
  $("resetBtn").addEventListener("click", reiniciar);
  $("tradeSave").addEventListener("click", salvarValorEntrada);
  // grava também ao sair do campo (não precisas de carregar no "ok")
  $("tradeInput").addEventListener("change", salvarValorEntrada);
  $("tradeInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") salvarValorEntrada();
  });
  $("modalCancel").addEventListener("click", hideModal);
  $("modalOk").addEventListener("click", () => {
    const fn = pendingConfirm; hideModal(); if (fn) fn();
  });

  // delegação de cliques dentro das posições (link pump.fun / vender / guardar meta).
  // Os contentores (#posicoes/#historico) não são substituídos no re-render — só o
  // seu innerHTML — por isso o listener sobrevive e o toque no link nunca se perde.
  $("posicoes").addEventListener("click", (ev) => {
    const link = ev.target.closest(".tok-link");
    if (link) { openPump(link.getAttribute("data-mint")); return; }
    const b = ev.target.closest("button");
    if (!b) return;
    const id = b.getAttribute("data-id");
    if (b.getAttribute("data-act") === "sell") {
      venderPosicao(id, b.getAttribute("data-name") || "?");
    } else if (b.getAttribute("data-act") === "meta") {
      const card = b.closest(".card");
      const input = card ? card.querySelector(".meta-input") : null;
      salvarMeta(id, input ? input.value.trim() : "");
    }
  });

  // links pump.fun no histórico
  $("historico").addEventListener("click", (ev) => {
    const link = ev.target.closest(".tok-link");
    if (link) openPump(link.getAttribute("data-mint"));
  });

  poll();
  setInterval(poll, 2500);
})();
