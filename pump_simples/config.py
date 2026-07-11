"""
Configuração do robozão.

Lê todas as variáveis de um ficheiro .env (parser próprio, sem dependências)
e das variáveis de ambiente do sistema. Nada de segredos hardcoded aqui.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Diretório base do projeto (onde vive este ficheiro)
BASE_DIR = Path(__file__).resolve().parent

# Mint do SOL "wrapped" — usado como moeda de entrada nas trades reais.
SOL_MINT = "So11111111111111111111111111111111111111112"


def _load_dotenv(path: Path) -> None:
    """Carrega KEY=VALUE de um .env para os.environ (sem sobrepor o ambiente real)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # não sobrepõe algo já definido no ambiente do processo
        if key and key not in os.environ:
            os.environ[key] = value


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _get_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _get_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "y", "sim", "on")


@dataclass
class Config:
    # --- Modo de execução (segurança em primeiro lugar) ---
    dry_run: bool = True                     # simulado por default
    permitir_envio_real: bool = False        # 2ª confirmação obrigatória p/ real

    # --- Segredos / rede ---
    wallet_private_key: str = ""             # base58, lido do .env — NUNCA logado
    solana_rpc_url: str = ""                 # RPC Helius (mesma do bot anterior)

    # --- Fonte de deteção (só UMA ativa de cada vez) ---
    # "gecko" (default) | "pumpfun_nao_oficial" | "bitquery"
    fonte_deteccao: str = "gecko"
    bitquery_api_key: str = ""               # só para fonte="bitquery" (grátis em bitquery.io)

    # --- Regras de entrada ---
    liquidez_minima_usd: float = 1000.0
    marketcap_minimo_usd: float = 10000.0     # 0 = desligado (mcap ≈ preço * 1e9)

    # --- Regras de saída ---
    take_profit_pct: float = 50.0
    stop_loss_pct: float = 25.0   # dados (secção 7): stops apanham rugs reais que NÃO recuperam
    timeout_minutos: float = 10.0
    intervalo_verificacao_segundos: int = 5   # verifica posições mais depressa (era 15)

    # --- Tamanho / saldos --- (o saldo é uma unidade virtual; símbolo configurável)
    max_trade_usd: float = 2.0
    saldo_virtual_inicial: float = 1000.0
    max_posicoes_abertas: int = 0             # 0 = SEM limite (limitado só pelo saldo)
    moeda_simbolo: str = "€"                  # símbolo mostrado no saldo/P&L da carteira

    # --- Robustez ---
    rpc_max_req_por_segundo: float = 5.0
    gecko_max_req_por_segundo: float = 2.0    # limita chamadas ao Gecko (free-tier)
    intervalo_scan_segundos: int = 20        # frequência de procura de tokens novos
    slippage_bps: int = 500                  # 5% — só usado em modo real

    # --- Acompanhamento pós-venda (só leitura de preço, sem trades) ---
    acompanhar_vendidos_max: int = 20        # quantos tokens já vendidos seguir
    intervalo_acompanhar_vendidos_segundos: int = 60

    # --- Dashboard ---
    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 5000

    # --- Ficheiros ---
    log_file: str = str(BASE_DIR / "decisions.jsonl")
    state_file: str = str(BASE_DIR / "state.json")

    # Endpoints (deixados como config para facilitar testes)
    gecko_api_base: str = "https://api.geckoterminal.com/api/v2"
    jupiter_api_base: str = "https://quote-api.jup.ag/v6"
    pumpfun_api_base: str = "https://frontend-api.pump.fun"
    bitquery_api_url: str = "https://streaming.bitquery.io/eap"

    @property
    def wallet_configurada(self) -> bool:
        return bool(self.wallet_private_key)

    @property
    def envio_real_armado(self) -> bool:
        """Só True quando as DUAS travas de segurança estão desligadas."""
        return (not self.dry_run) and self.permitir_envio_real


_FONTES_VALIDAS = ("gecko", "pumpfun_nao_oficial", "bitquery")


def load_config() -> Config:
    _load_dotenv(BASE_DIR / ".env")

    fonte = _get("FONTE_DETECCAO", "gecko").strip().lower()
    if fonte not in _FONTES_VALIDAS:
        print(f"[config] FONTE_DETECCAO='{fonte}' inválida; a usar 'gecko'. "
              f"Válidas: {_FONTES_VALIDAS}")
        fonte = "gecko"

    return Config(
        dry_run=_get_bool("DRY_RUN", True),
        permitir_envio_real=_get_bool("PERMITIR_ENVIO_REAL", False),
        wallet_private_key=_get("WALLET_PRIVATE_KEY", ""),
        solana_rpc_url=_get("SOLANA_RPC_URL", ""),
        fonte_deteccao=fonte,
        bitquery_api_key=_get("BITQUERY_API_KEY", ""),
        liquidez_minima_usd=_get_float("LIQUIDEZ_MINIMA_USD", 1000.0),
        marketcap_minimo_usd=_get_float("MARKETCAP_MINIMO_USD", 10000.0),
        take_profit_pct=_get_float("TAKE_PROFIT_PCT", 50.0),
        stop_loss_pct=_get_float("STOP_LOSS_PCT", 25.0),
        timeout_minutos=_get_float("TIMEOUT_MINUTOS", 10.0),
        intervalo_verificacao_segundos=_get_int("INTERVALO_VERIFICACAO_SEGUNDOS", 5),
        max_trade_usd=_get_float("MAX_TRADE_USD", 2.0),
        saldo_virtual_inicial=_get_float("SALDO_VIRTUAL_INICIAL", 1000.0),
        max_posicoes_abertas=_get_int("MAX_POSICOES_ABERTAS", 0),
        moeda_simbolo=_get("MOEDA_SIMBOLO", "€"),
        rpc_max_req_por_segundo=_get_float("RPC_MAX_REQ_POR_SEGUNDO", 5.0),
        gecko_max_req_por_segundo=_get_float("GECKO_MAX_REQ_POR_SEGUNDO", 2.0),
        intervalo_scan_segundos=_get_int("INTERVALO_SCAN_SEGUNDOS", 20),
        slippage_bps=_get_int("SLIPPAGE_BPS", 500),
        acompanhar_vendidos_max=_get_int("ACOMPANHAR_VENDIDOS_MAX", 20),
        intervalo_acompanhar_vendidos_segundos=_get_int(
            "INTERVALO_ACOMPANHAR_VENDIDOS_SEGUNDOS", 60),
        dashboard_host=_get("DASHBOARD_HOST", "0.0.0.0"),
        dashboard_port=_get_int("DASHBOARD_PORT", 5000),
    )


# instância única partilhada por toda a app
CFG = load_config()
