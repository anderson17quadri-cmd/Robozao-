// robozão dashboard — polling do /api/state + ações (toggle, venda manual, meta)
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const MODO = window.MODO || {};
  const SIM = MODO.moeda_simbolo || "€";   // símbolo da carteira (saldo/P&L)

  // modo atual (simulado/real) — atualizado a cada poll via state.modo, porque
  // agora pode mudar em runtime (botão) sem recarregar a página.
  let modoAtual = Object.assign({}, MODO);
  function isReal() { return !!modoAtual.envio_real_armado; }

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

  function fmtCompact(v) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    const n = Number(v);
    if (n >= 1e6) return "$" + (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return "$" + (n / 1e3).toFixed(1) + "k";
    return "$" + n.toFixed(0);
  }

  // "hype" da moeda à compra: nº de compradores + volume (1h). Chama mais fogo quanto
  // mais compradores. Vazio se não houver dados (trades antigos).
  function hypeBadge(o) {
    const b = o.buyers_h1, v = o.volume_h1;
    if ((b === null || b === undefined) && (v === null || v === undefined)) return "";
    const nb = Number(b || 0);
    const fogo = nb >= 100 ? "🔥🔥🔥" : nb >= 40 ? "🔥🔥" : nb >= 10 ? "🔥" : "•";
    return `<span class="hype" title="compradores e volume na 1ª hora">${fogo} ${nb} compradores · ${fmtCompact(v)} vol</span>`;
  }

  // linha com o mint abreviado + botão para copiar o endereço COMPLETO do contrato
  // (para colares noutro sítio: DexScreener, Birdeye, carteira, etc.)
  function mintRow(mint) {
    if (!mint) return "";
    return `<div class="mint-row">
      <span class="mint">${shortMint(mint)}</span>
      <button class="btn-copy" data-act="copy" data-mint="${escapeHtml(mint)}" title="Copiar endereço do contrato">📋 copiar</button>
    </div>`;
  }

  async function copiarContrato(mint, btn) {
    const original = btn.textContent;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(mint);
      } else {
        // fallback para navegadores/contextos sem Clipboard API
        const ta = document.createElement("textarea");
        ta.value = mint; ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      btn.textContent = "✓ copiado";
    } catch (e) {
      btn.textContent = "erro";
    }
    setTimeout(() => { btn.textContent = original; }, 1500);
  }

  // ---------- cards ----------
  function posicaoCard(p) {
    const cls = signClass(p.pl_pct);
    const meta = (p.meta_lucro_pct !== null && p.meta_lucro_pct !== undefined) ? p.meta_lucro_pct : "";
    const alvoNum = meta !== "" ? Number(meta) : Number(MODO.take_profit_pct || 0);
    // trailing ESCALONADO: qual % está ativo AGORA para esta posição (depende
    // do ganho do pico desde a entrada — espelha a lógica do trader.py)
    const picoPct = p.entry_price ? ((p.preco_pico || p.entry_price) / p.entry_price - 1) * 100 : 0;
    const apertoAcima = Number(MODO.trailing_aperto_acima_pct || 100);
    const trailingAtivo = picoPct >= apertoAcima
      ? Number(MODO.trailing_stop_apertado_pct || 15)
      : Number(MODO.trailing_stop_pct || 30);
    const alvoTxt = alvoNum > 0
      ? `meta: +${alvoNum.toFixed(0)}%`
      : `só trailing −${trailingAtivo.toFixed(0)}% do pico${picoPct >= apertoAcima ? " (apertado)" : ""}`;
    return `
      <div class="card ${cls}" data-id="${p.id}">
        <div>
          <div class="name">${pumpLink(p.mint, p.name || "?")}${p.canal === "hype" ? ' <span class="tag-hype">HYPE</span>' : ""}</div>
          ${mintRow(p.mint)}
          ${hypeBadge(p)}
        </div>
        <div class="pl ${cls}">${fmtPct(p.pl_pct)}<span class="pl-money">${fmtUsd(p.pl_usd)}</span></div>
        <div class="meta">
          <span>entrada ${fmtPrice(p.entry_price)}</span>
          <span>agora ${fmtPrice(p.current_price)}</span>
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
          ${mintRow(h.mint)}
          ${hypeBadge(h)}
        </div>
        <div class="pl ${cls}">${fmtPct(h.pl_pct)}<span class="pl-money">${fmtUsd(h.pl_usd)}</span></div>
        <div class="meta">
          <span>entrada ${fmtPrice(h.entry_price)}</span>
          <span>saída ${fmtPrice(h.exit_price)}</span>
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
    if (state.modo) modoAtual = state.modo;

    // badge de modo + botão (atualizam ao vivo, já não só no carregamento da página)
    const badge = $("modeBadge");
    const real = isReal();
    if (badge) {
      badge.classList.toggle("badge-real", real);
      badge.classList.toggle("badge-dry", !real);
      badge.textContent = real ? "🔴 modo REAL" : "🧪 modo DEMO";
    }
    const mb = $("modeBtn");
    if (mb) {
      mb.classList.toggle("on", real);
      mb.classList.toggle("off", !real);
      mb.textContent = real ? "⚠️ REAL" : "🧪 DEMO";
    }

    // saldo real da wallet (só aparece quando o modo real está armado)
    const kpiWalletCard = $("kpiWalletCard");
    if (kpiWalletCard) {
      kpiWalletCard.classList.toggle("hidden", !real);
      if (real) {
        const sol = state.saldo_real_sol;
        const usd = state.saldo_real_usd;
        const txt = (sol === null || sol === undefined)
          ? "—"
          : `${Number(sol).toFixed(4)} SOL` + (usd !== null && usd !== undefined ? ` (~$${Number(usd).toFixed(2)})` : "");
        $("kpiWalletSaldo").textContent = txt;
      }
    }

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

    // botão HYPE (on/off)
    const hb = $("hypeBtn");
    if (hb) {
      const on = !!state.hype_ativo;
      hb.classList.toggle("on", on); hb.classList.toggle("off", !on);
      hb.textContent = "🔥 HYPE: " + (on ? "on" : "off");
    }

    // valor por entrada — não sobrescreve enquanto o utilizador escreve
    $("cfgCur").textContent = SIM;
    const ti = $("tradeInput");
    if (document.activeElement !== ti && state.max_trade_usd !== undefined) {
      ti.value = state.max_trade_usd;
    }
    // rodapé "trade máx" ao vivo (reflete o valor guardado, não o do .env)
    const ft = $("footTrade");
    if (ft && state.max_trade_usd !== undefined) ft.textContent = SIM + Number(state.max_trade_usd).toFixed(0);

    // filtros editáveis — não sobrescreve enquanto escreves
    setInputSeNaoFocado("liqInput", state.liquidez_minima_usd);
    setInputSeNaoFocado("mcapInput", state.marketcap_minimo_usd);
  }

  function setInputSeNaoFocado(id, valor) {
    const el = $(id);
    if (el && document.activeElement !== el && valor !== undefined && valor !== null) {
      el.value = valor;
    }
  }

  async function salvarConfig(campo, valorRaw, btnId) {
    const v = String(valorRaw).trim().replace(",", ".");
    const n = Number(v);
    if (v === "" || isNaN(n) || n < 0) return;
    const btn = btnId ? $(btnId) : null;
    try {
      const r = await fetch("/api/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [campo]: v }),
      });
      if (btn) { btn.textContent = r.ok ? "✓" : "erro"; setTimeout(() => { btn.textContent = "ok"; }, 1200); }
      await poll();
    } catch (e) { if (btn) btn.textContent = "erro"; }
  }

  async function poll() {
    try {
      const r = await fetch("/api/state");
      if (r.ok) render(await r.json());
    } catch (e) { /* tenta outra vez */ }
  }

  // ---------- ações ----------
  async function toggle(confirmarReal) {
    const btn = $("toggleBtn");
    const eraLigado = btn.classList.contains("on");   // estávamos a desligar?
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
      if (eraLigado) {
        // desligar pode demorar 1 volta do loop a terminar as chamadas de rede
        // em curso — dá feedback imediato e confirma o estado real depressa.
        $("statusLine").textContent = "a desligar…";
        btn.disabled = true;
        for (let i = 0; i < 10; i++) {
          await new Promise((res) => setTimeout(res, 700));
          await poll();
          if (!btn.classList.contains("on")) break;   // já desligou
        }
        btn.disabled = false;
      }
    } catch (e) { btn.disabled = false; }
  }

  async function venderPosicao(id, nome) {
    const real = isReal();
    const titulo = real ? "⚠️ Vender em MODO REAL" : "Confirmar venda";
    const msg = `Vender 100% de "${nome}" agora?` +
      (real ? " Isto envia uma transação real." : " (simulado, DRY_RUN)");
    showConfirm(titulo, msg, real, async () => {
      try {
        const r = await fetch(`/api/posicao/${id}/vender`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirmar_real: real }),
        });
        await r.json().catch(() => ({}));
        await poll();
      } catch (e) { /* ignora */ }
    });
  }

  // ---------- alternar SIMULADO <-> REAL ----------
  async function toggleModo(confirmado) {
    const querReal = !isReal();   // direção fixa entre a 1ª chamada e a confirmação
    try {
      const r = await fetch("/api/modo", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ real: querReal, confirmar_real: !!confirmado }),
      });
      const d = await r.json().catch(() => ({}));
      if (r.status === 409 && d.precisa_confirmacao) {
        showConfirm("⚠️ Ligar MODO REAL", d.aviso, true, () => toggleModo(true));
        return;
      }
      if (!r.ok) {
        showConfirm("Não foi possível mudar de modo", d.motivo || "erro desconhecido", false, null);
        return;
      }
      await poll();
    } catch (e) { /* ignora */ }
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
    // fn === null => é só um aviso (sem ação): esconde o "confirmar" e o
    // "cancelar" passa a "ok". Evita botões que parecem fazer algo e não fazem.
    const okBtn = $("modalOk");
    const cancelBtn = $("modalCancel");
    if (fn) {
      okBtn.style.display = "";
      cancelBtn.textContent = "cancelar";
    } else {
      okBtn.style.display = "none";
      cancelBtn.textContent = "ok";
    }
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

  async function toggleHype() {
    try { await fetch("/api/hype", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); await poll(); }
    catch (e) { /* ignora */ }
  }

  // ---------- eventos ----------
  $("toggleBtn").addEventListener("click", () => toggle(false));
  $("modeBtn").addEventListener("click", () => toggleModo(false));
  $("resetBtn").addEventListener("click", reiniciar);
  $("hypeBtn").addEventListener("click", toggleHype);
  $("tradeSave").addEventListener("click", salvarValorEntrada);
  // grava também ao sair do campo (não precisas de carregar no "ok")
  $("tradeInput").addEventListener("change", salvarValorEntrada);

  // filtros: liquidez mínima e market cap mínimo
  const bindFiltro = (inputId, campo, btnId) => {
    const save = () => salvarConfig(campo, $(inputId).value, btnId);
    $(btnId).addEventListener("click", save);
    $(inputId).addEventListener("change", save);
    $(inputId).addEventListener("keydown", (e) => { if (e.key === "Enter") save(); });
  };
  bindFiltro("liqInput", "liquidez_minima_usd", "liqSave");
  bindFiltro("mcapInput", "marketcap_minimo_usd", "mcapSave");

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
    if (b.getAttribute("data-act") === "copy") {
      copiarContrato(b.getAttribute("data-mint"), b);
      return;
    }
    const id = b.getAttribute("data-id");
    if (b.getAttribute("data-act") === "sell") {
      venderPosicao(id, b.getAttribute("data-name") || "?");
    } else if (b.getAttribute("data-act") === "meta") {
      const card = b.closest(".card");
      const input = card ? card.querySelector(".meta-input") : null;
      salvarMeta(id, input ? input.value.trim() : "");
    }
  });

  // links pump.fun + copiar contrato no histórico
  $("historico").addEventListener("click", (ev) => {
    const link = ev.target.closest(".tok-link");
    if (link) { openPump(link.getAttribute("data-mint")); return; }
    const b = ev.target.closest("button");
    if (b && b.getAttribute("data-act") === "copy") {
      copiarContrato(b.getAttribute("data-mint"), b);
    }
  });

  poll();
  setInterval(poll, 2500);
})();
