#!/usr/bin/env bash
# ============================================================
#  robozão — arranque rápido em DRY_RUN (simulado)
#  Não precisas de editar nada à mão. Basta:  bash start_dryrun.sh
# ============================================================
set -e
cd "$(dirname "$0")"

# 1) cria o .env já configurado (só se ainda não existir — não apaga o teu)
if [ ! -f .env ]; then
  echo ">> a criar .env para DRY_RUN (simulado)..."
  cat > .env <<'ENV'
# Gerado por start_dryrun.sh — modo simulado, sem transações reais.
DRY_RUN=true
PERMITIR_ENVIO_REAL=false

# Em DRY_RUN não é preciso chave privada. Só a preenches para modo REAL.
WALLET_PRIVATE_KEY=

# RPC pública grátis (sem chave). Troca pela tua Helius quando tiver créditos.
SOLANA_RPC_URL=https://solana-rpc.publicnode.com

# Fonte de deteção: gecko | pumpfun_nao_oficial | bitquery
FONTE_DETECCAO=gecko
BITQUERY_API_KEY=

# Regras
LIQUIDEZ_MINIMA_USD=1000
TAKE_PROFIT_PCT=50
STOP_LOSS_PCT=25
TIMEOUT_MINUTOS=10
INTERVALO_VERIFICACAO_SEGUNDOS=15

# Tamanho / saldos
MAX_TRADE_USD=2
SALDO_VIRTUAL_INICIAL=1000
MAX_POSICOES_ABERTAS=3

# Robustez (rate baixo por ser RPC pública)
RPC_MAX_REQ_POR_SEGUNDO=3
INTERVALO_SCAN_SEGUNDOS=20

# Dashboard
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=5000
ENV
  echo ">> .env criado."
else
  echo ">> .env já existe — a usar o que tens."
fi

# 2) dependências mínimas do DRY_RUN (não precisa de solders/rust)
echo ">> a instalar flask e requests (se faltarem)..."
pip install -q flask requests || python -m pip install -q flask requests

# 3) arranca o dashboard
echo ">> a arrancar o dashboard em http://localhost:5000"
echo ">> (Ctrl+C para parar)"
exec python dashboard.py
