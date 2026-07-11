# 🤖 robozão — bot pump.fun minimalista

Bot de trading **novo, independente e isolado** — código do zero, focado só em
tokens **pump.fun (Solana)**. Filosofia: *comprar e vender rápido, regras
simples, sem enrolação*. Nada de camadas de IA, scores ou checklists.

> ⚠️ **Bot de teste / educativo.** Arranca sempre em **DRY_RUN (simulado)**.
> Trades minúsculas por default (`MAX_TRADE_USD=$2`). Usa por tua conta e risco.

---

## O que faz

- **Deteta** tokens novos pump.fun. Fonte **alternável** por config `FONTE_DETECCAO` (só uma ativa de cada vez), todas com o mesmo formato de saída — ver [Fontes de deteção](#fontes-de-deteção).
- **Verifica segurança** via RPC Solana (Helius): `getAccountInfo` (`jsonParsed`) para confirmar que `mintAuthority` **e** `freezeAuthority` estão **ambos revogados (None)**.
- **Compra/vende** (simulado por default; real via [Jupiter](https://station.jup.ag/docs/apis/swap-api) quando ativado).
- **Dashboard web** com estética pump.fun: saldo, posições em tempo real, histórico, toggle liga/desliga, **venda manual** por posição, **meta de lucro editável por posição**, **links para o pump.fun** e **acompanhamento pós-venda** (ver [Dashboard](#dashboard--ações)).

### Regras de entrada (só 3, todas obrigatórias)
1. Token é pump.fun.
2. `mint_authority` **e** `freeze_authority` ambos `None` — **único critério de segurança, fail-closed** (se não confirmar via RPC, **não compra**).
3. Liquidez ≥ `LIQUIDEZ_MINIMA_USD` (default $1000).

### Regras de saída (o que disparar primeiro, vence)
- **Colapso de liquidez (prioridade máxima):** se a liquidez cair
  `LIQUIDEZ_QUEDA_VENDA_PCT%` (default 70%) desde a compra, vende **já**,
  ignorando todas as regras abaixo. Quando um pool graduado (ex: PumpSwap) tem
  a liquidez removida, o preço da AMM deixa de ser fiável — pode não haver
  ninguém do outro lado para negociar a sério. Motivo no log:
  `liquidez_colapsou`. `0` = desligado.
- **Trailing stop (saída principal):** deixa o **pico** correr (só sobe) e vende
  tudo se cair `TRAILING_STOP_PCT%` (default 30%) desde esse pico — não desde a
  compra. Quando o token nunca sobe acima da entrada, age como stop-loss.
  **Escalonado:** acima de `TRAILING_APERTO_ACIMA_PCT` de ganho no pico (default
  +100%), passa a usar `TRAILING_STOP_APERTADO_PCT` (default 15%) — protege mais
  de um ganho grande, já que devolver 30% de um pico de +500% dói muito mais em
  valor absoluto do que 30% de um pico de +20%. O log de venda regista
  `trailing_pct_usado` e `pico_pct` para veres qual dos dois disparou.
- **Take-profit:** **desligado por default** (`TAKE_PROFIT_PCT=0`) — não há teto
  de lucro; o pico corre livre e o trailing gere a subida. Podes definir uma meta
  por posição no dashboard, ou pôr um `TAKE_PROFIT_PCT` global se quiseres um teto.
- **Timeout:** vende tudo passados `TIMEOUT_MINUTOS` (default 10 min; `0` = sem timeout).
- `STOP_LOSS_PCT` ficou **legado** (substituído pelo trailing).
- Verificação a cada `INTERVALO_VERIFICACAO_SEGUNDOS` (default 5s) — cada
  verificação já lê preço E liquidez na mesma chamada (sem custo extra de rede).

### Slippage simulado (só DRY_RUN)
Para o P/L simulado ser mais realista, cada compra/venda em DRY_RUN sofre um
slippage estimado (`SLIPPAGE_SIMULADO_PCT`, default 3% por lado) + um impacto pelo
tamanho da trade face à liquidez. Enches a compra mais caro e a venda mais barato.
Em modo REAL isto não se aplica (o slippage é o real da Jupiter, `SLIPPAGE_BPS`).
**Nota:** mesmo assim o DRY_RUN é otimista — assume que consegues sempre executar.

---

## Fontes de deteção

Escolhes de onde vêm os tokens novos com `FONTE_DETECCAO` no `.env` — **só uma
ativa de cada vez**. Todas devolvem o mesmo formato, por isso o resto do bot
(`trader.py`, monitorização, regras) **funciona igual, sem saber qual fonte está a usar**.

| `FONTE_DETECCAO` | Fonte | Chave? | Notas |
|---|---|---|---|
| `gecko` *(default)* | GeckoTerminal `/new_pools` | não | grátis, dados completos |
| `pumpfun_nao_oficial` | API não-oficial do pump.fun | não | grátis; engenharia reversa (à la [BankkRoll/pumpfun-apis](https://github.com/BankkRoll/pumpfun-apis)); pode partir se o pump.fun mudar a API |
| `bitquery` | [Bitquery](https://docs.bitquery.io/) GraphQL | **sim** (`BITQUERY_API_KEY`) | plano grátis 100k pontos/mês, sem streaming |

**Como funciona por dentro:** as fontes alternativas fazem só a *descoberta* (que
mints considerar). O `pool_address`, preço e liquidez são padronizados via
GeckoTerminal (o oráculo de preço gratuito e uniforme) — assim a monitorização de
posições funciona igual em qualquer fonte, e trocar de fonte nunca altera o
pipeline. Um token ainda sem pool indexado no oráculo é ignorado (fail-safe).

Para `bitquery`, mete no `.env`:
```env
FONTE_DETECCAO=bitquery
BITQUERY_API_KEY=a-tua-key   # cadastro grátis em bitquery.io
```

## Dashboard — ações

Além de mostrar saldo/posições/histórico, o dashboard permite:

- **Vender 100% (manual)** — botão por posição aberta. Usa o mesmo caminho da
  venda automática (Jupiter em real, simulado em DRY_RUN). Pede confirmação antes
  de executar; em modo REAL a confirmação é reforçada.
- **Meta de lucro por posição** — campo "meta venda %" editável em cada posição.
  Se definida, aquela posição vende ao atingir essa % em vez do `TAKE_PROFIT_PCT`
  global. Vazio/0 => volta ao global. O stop-loss e o timeout continuam globais.
- **Link para o pump.fun** — o nome de cada token (posições e histórico) abre
  `https://pump.fun/coin/{mint}` numa nova aba.
- **Acompanhamento pós-venda** — depois de vender, o token continua no histórico
  marcado como **"já vendido"** e o bot continua a ler o preço dele (só leitura,
  sem trades) mostrando a variação **desde a venda**. Segue os últimos
  `ACOMPANHAR_VENDIDOS_MAX` (default 20), a cada
  `INTERVALO_ACOMPANHAR_VENDIDOS_SEGUNDOS` (default 60s). Não afeta saldo.

## Moeda

A carteira simulada usa o símbolo `MOEDA_SIMBOLO` (default **€**) no saldo e no
P&L. A matemática do saldo é feita com **rácios de preço** (só a variação % conta),
por isso a carteira virtual pode estar em € sem qualquer conversão — `SALDO_VIRTUAL_INICIAL`
e `MAX_TRADE_USD` são a tua unidade (€).

Os **preços dos tokens** (entrada/agora) continuam a ser mostrados em **$**, porque é
assim que o mercado (GeckoTerminal/Jupiter) os cota — não são convertidos. Ou seja:
*a tua carteira é em €, as cotações de mercado são em $*. Em modo REAL, as transações
são sempre em SOL on-chain, independentemente do símbolo mostrado.

## Reiniciar a simulação

O saldo/posições ficam guardados em `state.json` entre reinícios. Para **recomeçar
do zero** (repor `SALDO_VIRTUAL_INICIAL` e limpar posições/histórico), usa o botão
**↺ Reiniciar** no dashboard (só DRY_RUN, com o bot desligado). É por isso que, se já
tinhas corrido antes, o saldo não aparecia nos 1000 — carregava o estado antigo.

## Quantos tokens o bot compra

- **`MAX_POSICOES_ABERTAS`** (default **0 = sem limite**) — nº de posições abertas
  em simultâneo. Com 0, o bot compra toda a oportunidade que passe as regras,
  ficando limitado só pelo saldo / `MAX_TRADE_USD`.
- **`MAX_TRADE_USD`** (default 2) — quanto entra em cada posição (editável no dashboard).
- **`MARKETCAP_MINIMO_USD`** (default **10000**, 0 = desligado) — market cap mínimo à
  entrada (`≈ preço × 1e9`). Regra extra baseada nos dados reais: tokens comprados
  a mcap baixo (~$3k) tendiam a *rugar*; os que subiam entravam a ~$20k.
- O bot também só compra tokens que passem as regras de segurança (pump.fun +
  autoridades revogadas + liquidez mínima), por isso nem todos os detetados viram compra.

> ⚠️ Com `MAX_POSICOES_ABERTAS=0` e muitas posições abertas, a monitorização de
> preços faz muitas chamadas à GeckoTerminal (free-tier). O `GECKO_MAX_REQ_POR_SEGUNDO`
> trava-as para não haver 429, mas com dezenas de posições os preços podem atualizar
> mais devagar que o `INTERVALO_VERIFICACAO_SEGUNDOS`.

### Lista de vigia (watchlist)

Tokens pump.fun nascem com liquidez/mcap quase zero. O feed de deteção só mostra
os muito recentes (~minutos) — sem mais nada, um token rejeitado por liquidez/mcap
baixos no minuto 1 nunca mais seria reavaliado, mesmo que crescesse o suficiente
no minuto 15 (já teria saído do feed).

Para resolver isto sem baixar os filtros: tokens rejeitados **só** por liquidez ou
market cap ficam numa **lista de vigia** e são reavaliados com dados frescos
periodicamente, comprados assim que qualificarem. Configurável:
- `VIGIA_TTL_MINUTOS` (default 60) — por quanto tempo um token fica em vigia.
- `VIGIA_MAX_POR_CICLO` (default 15) — quantos são reavaliados por ciclo (poupa
  chamadas à GeckoTerminal).

A liquidez mínima e a segurança **nunca** são saltadas — só dá tempo ao token de
crescer até lá. Compras vindas da vigia aparecem no log com `origem: "vigia"`.

### Bloqueio de moedas que já rugaram

Se um mint já fechou com prejuízo ≥ `BLACKLIST_PREJUIZO_PCT` (default 50%) ou por
`liquidez_colapsou` (sempre bloqueia, qualquer que seja o P/L), o bot **não volta
a comprá-lo**. Evita repetir a mesma perda na mesma moeda — o mint fica de fora
antes até de entrar na lista de vigia.

- `BLACKLIST_COOLDOWN_HORAS` (default **0 = bloqueio permanente**). Um valor > 0
  define um cooldown temporário em horas, após o qual volta a poder ser comprado.
- Usa `STATE.historico` como fonte da verdade — por isso, carregar em
  **↺ Reiniciar** limpa o histórico e, com ele, o bloqueio também (faz sentido:
  é uma simulação nova, do zero).
- Motivo no log de rejeição: `mint_bloqueado`.

### Canal HYPE (opcional)

Botão **🔥 HYPE** no dashboard (default desligado). Quando ligado, tokens com
tração real (`HYPE_MIN_COMPRADORES` ou `HYPE_MIN_VOLUME_USD`) saltam **só** o
filtro de market cap — nunca a liquidez nem a segurança. Os limites (40
compradores / $10k volume) foram escolhidos com base nos dados: tokens com
100+ compradores tendiam a **perder** (comprar o topo do pump), por isso o
canal mira tração moderada, não extrema. Entradas por este canal ficam
marcadas com o badge `HYPE` no card.

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

### RPCs públicas grátis (sem chave)

Se a Helius ficar sem créditos (limite mensal), troca a `SOLANA_RPC_URL` por uma
destas — não precisam de registo nem chave:

| RPC | Nota |
|---|---|
| `https://solana-rpc.publicnode.com` | **recomendada** — limites mais folgados |
| `https://api.mainnet-beta.solana.com` | oficial, mais lenta / rate-limit apertado |

São mais limitadas que a Helius, mas o rate limiter do bot
(`RPC_MAX_REQ_POR_SEGUNDO`) ajuda a não bater nos limites. Chegam para testar em
DRY_RUN.

## Correr

**Arranque rápido (sem configurar nada)** — cria o `.env` para DRY_RUN, instala
o que falta e arranca. Ideal para o Termux:
```bash
bash start_dryrun.sh
# abre http://localhost:5000  e carrega em "LIGAR BOT"
```

**Dashboard (manual)** — corre o bot numa thread e dá-te o toggle:
```bash
python dashboard.py
# abre http://localhost:5000  e carrega em "LIGAR BOT"
```

**Headless (só bot, sem UI):**
```bash
python bot.py     # Ctrl+C para parar
```

---

## Correr no Termux (Android)

Dá para correr no telemóvel. Para **DRY_RUN não precisas da chave privada** —
só de `requests` + `flask`.

```bash
# 1. atualizar e instalar o básico
pkg update && pkg upgrade -y
pkg install -y python git

# 2. obter o código
git clone https://github.com/anderson17quadri-cmd/Robozao-.git
cd Robozao-/pump_simples

# 3. dependências (DRY_RUN só precisa destas duas)
pip install flask requests

# 4. configurar
cp .env.example .env
nano .env      # deixa DRY_RUN=true. Cola a SOLANA_RPC_URL (p/ o check de segurança).

# 5. correr
python dashboard.py
```

Depois abre no browser do telemóvel: **http://localhost:5000** e carrega em
"LIGAR BOT".

**Notas Termux:**
- Em DRY_RUN, `WALLET_PRIVATE_KEY` pode ficar vazia. Só a `SOLANA_RPC_URL` é
  útil (para o bot confirmar as autoridades dos mints); sem ela, o bot rejeita
  tudo por fail-closed — seguro, mas não simula compras.
- O modo **REAL** precisa de `solders`, que é compilado em Rust e pode ser
  chato de instalar no Termux (`pkg install rust binutils` e depois
  `pip install solders`, pode demorar). Para testes, fica-te pelo DRY_RUN.
- Se `localhost` não abrir, confirma a porta no `.env` (`DASHBOARD_PORT`).

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
