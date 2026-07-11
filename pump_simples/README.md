# 🤖 robozão — bot pump.fun minimalista

Bot de trading **novo, independente e isolado** — código do zero, focado só em
tokens **pump.fun (Solana)**. Filosofia: *comprar e vender rápido, regras
simples, sem enrolação*. Nada de camadas de IA, scores ou checklists.

> ⚠️ **Bot de teste / educativo.** Arranca sempre em **DRY_RUN (simulado)**.
> Trades minúsculas por default (`MAX_TRADE_USD=$2`). Usa por tua conta e risco.

---

## O que faz

- **Deteta** tokens novos pump.fun via [GeckoTerminal](https://www.geckoterminal.com/) (`/networks/solana/new_pools`, filtrando `dex=pump-fun`). API pública, gratuita, sem chave.
- **Verifica segurança** via RPC Solana (Helius): `getAccountInfo` (`jsonParsed`) para confirmar que `mintAuthority` **e** `freezeAuthority` estão **ambos revogados (None)**.
- **Compra/vende** (simulado por default; real via [Jupiter](https://station.jup.ag/docs/apis/swap-api) quando ativado).
- **Dashboard web** com estética pump.fun (saldo, posições em tempo real, histórico, toggle liga/desliga).

### Regras de entrada (só 3, todas obrigatórias)
1. Token é pump.fun.
2. `mint_authority` **e** `freeze_authority` ambos `None` — **único critério de segurança, fail-closed** (se não confirmar via RPC, **não compra**).
3. Liquidez ≥ `LIQUIDEZ_MINIMA_USD` (default $1000).

### Regras de saída (o que disparar primeiro, vence)
- **Take-profit:** vende tudo a `+TAKE_PROFIT_PCT%` (default +50%).
- **Stop-loss:** vende tudo a `-STOP_LOSS_PCT%` (default −25%).
- **Timeout:** vende tudo passados `TIMEOUT_MINUTOS` (default 10 min).
- Verificação a cada `INTERVALO_VERIFICACAO_SEGUNDOS` (default 15s).

---

## ⚠️ Aviso importante — wallet partilhada

Este bot usa a **MESMA wallet Solana do bot anterior** (lê `WALLET_PRIVATE_KEY`
do `.env` **deste** projeto).

> **Em modo REAL, os dois bots gastam do MESMO saldo on-chain.**
> **Não corras os dois em modo real ao mesmo tempo** — vão competir pelo mesmo
> SOL e podem colidir em transações. Corre um de cada vez em real.

A chave privada:
- **Nunca** é hardcoded no código.
- **Nunca** é impressa, logada ou escrita em ficheiro em lado nenhum.
- Só é lida em memória para assinar transações no modo real.

---

## Instalação

```bash
cd pump_simples

# (opcional mas recomendado) ambiente virtual
python3 -m venv .venv && source .venv/bin/activate

# dependências (dashboard + DRY_RUN precisam só de requests+flask;
# 'solders' só é preciso para modo real)
pip install -r requirements.txt
```

## Configuração

```bash
cp .env.example .env
```

Edita o `.env`:
- Cola a tua `WALLET_PRIVATE_KEY` (base58 / formato Phantom) — **tu mesmo**.
- Cola a `SOLANA_RPC_URL` (a mesma Helius do bot anterior).
- Ajusta regras/valores se quiseres. Deixa `DRY_RUN=true` para começar.

O `.env` está no `.gitignore` e **nunca** é commitado.

## Correr

**Dashboard (recomendado)** — corre o bot numa thread e dá-te o toggle:
```bash
python dashboard.py
# abre http://localhost:5000  e carrega em "LIGAR BOT"
```

**Headless (só bot, sem UI):**
```bash
python bot.py     # Ctrl+C para parar
```

---

## Ativar modo REAL (duas travas)

Por segurança são precisas **duas** confirmações no `.env`:

```env
DRY_RUN=false
PERMITIR_ENVIO_REAL=true
```

Só quando **ambas** estão assim é que alguma transação real acontece. E mesmo
assim, no dashboard ainda tens de **confirmar no popup** antes de o bot arrancar
em real. Instala também `solders` (`pip install solders`) para assinar as
transações.

---

## Ficheiros

| Ficheiro | Função |
|---|---|
| `config.py` | Lê o `.env` (parser próprio, sem dependências) |
| `gecko.py` | GeckoTerminal — deteção de tokens e preços |
| `solana_rpc.py` | Check de autoridades do mint (fail-closed, rate-limited) |
| `ratelimit.py` | Rate limiter (N pedidos/seg) — evita rate limit do RPC |
| `wallet.py` | Carrega a wallet (nunca loga a chave) |
| `jupiter.py` | Swaps reais (quote + swap) — só modo real |
| `state.py` | Saldo, posições, histórico (thread-safe, persistido) |
| `trader.py` | Regras de entrada e saída |
| `bot.py` | Loop principal + controlador start/stop |
| `dashboard.py` | Dashboard Flask + API |
| `web/` | Templates e estáticos do dashboard |
| `decisions.jsonl` | Log de todas as decisões (gerado em runtime) |

## Log de decisões

Todas as decisões (compra / rejeição / venda / erros) são escritas em
`decisions.jsonl` — uma linha JSON por evento, fácil de analisar depois:

```bash
cat decisions.jsonl | python3 -m json.tool   # ou jq
```

---

## Segurança & robustez

- **Fail-closed** em qualquer verificação de segurança: dados que falharam
  **nunca** são assumidos como "seguros".
- **Rate limiting** central nas chamadas RPC (`RPC_MAX_REQ_POR_SEGUNDO`).
- Toda chamada de rede em `try/except` — uma falha **nunca** derruba o loop.
- Estado persistido em `state.json` (sem segredos).
