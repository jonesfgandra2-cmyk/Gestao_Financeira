"""Cotações e indicadores de mercado, com cache no SQLite e fallback manual.

Fontes (todas públicas, sem chave):
  - Banco Central (SGS): Selic meta (432), CDI acumulado no mês (4391),
    poupança mensal (195), dólar PTAX venda (1), euro PTAX venda (21619).
  - CoinGecko: criptomoedas em BRL.

Toda função devolve algo mesmo sem internet: usa o último valor guardado
no banco ou o valor manual das configurações. A origem vem junto para a
tela poder dizer de onde o número saiu.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import requests

import db

# Séries do SGS (Banco Central):
#   432  Meta Selic definida pelo Copom (% a.a.)      — diária
#   4389 CDI anualizada base 252 (% a.a.)             — diária
#   12   CDI diária (% a.d.)                          — diária (acumula o mês corrente)
#   4391 CDI acumulada no mês (% a.m.)                — mensal (só sai no fechamento do mês)
#   195  Poupança rendimento no mês (% a.m.)          — mensal
#   433  IPCA variação mensal (%)                     — mensal
#   1 / 21619  Dólar / Euro PTAX venda                — diária
SGS = {"selic": 432, "cdi_aa": 4389, "cdi_dia": 12, "cdi_mes": 4391, "poupanca_mes": 195,
       "ipca_mes": 433, "USD": 1, "EUR": 21619}

# Indicadores que o usuario pode escolher para o painel do dashboard
INDICES_DISPONIVEIS = {
    "selic": "Selic (meta, % a.a.)",
    "cdi_aa": "CDI (% a.a.)",
    "cdi_mes": "CDI do mês (acumulado até hoje)",
    "poupanca_mes": "Poupança no mês",
    "ipca_mes": "IPCA do mês",
}
MOEDAS_DISPONIVEIS = {"USD": "Dólar (PTAX)", "EUR": "Euro (PTAX)"}
CRYPTO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
              "XRP": "ripple", "ADA": "cardano", "USDT": "tether", "USDC": "usd-coin",
              "DOGE": "dogecoin", "DOT": "polkadot", "LTC": "litecoin", "MATIC": "matic-network"}
TIMEOUT = 4

# Sem internet, cada consulta esperaria o timeout inteiro — e o painel faz
# varias. Depois de uma falha de rede, as chamadas seguintes pulam direto
# para o cache/manual por 10 minutos.
_ULTIMA_FALHA = {"quando": None, "erro": None}
_PAUSA_APOS_FALHA = timedelta(minutes=10)
# A API do BCB recusa (403) alguns clientes sem User-Agent "de navegador".
HEADERS = {"User-Agent": "Mozilla/5.0 (ControleFinanceiro; +https://github.com) requests",
           "Accept": "application/json"}


class _SemRede(Exception):
    pass


def resetar_falha():
    """Zera a pausa apos falha (botao 'Atualizar cotacoes')."""
    _ULTIMA_FALHA["quando"] = None


def ultimo_erro():
    return _ULTIMA_FALHA["erro"]


def _get(url, **kw):
    q = _ULTIMA_FALHA["quando"]
    if q and datetime.now() - q < _PAUSA_APOS_FALHA:
        raise _SemRede(f"rede indisponivel recentemente ({_ULTIMA_FALHA['erro']})")
    try:
        r = requests.get(url, timeout=TIMEOUT, headers=HEADERS, **kw)
        r.raise_for_status()
        return r
    except requests.RequestException as e:
        _ULTIMA_FALHA["quando"] = datetime.now()
        _ULTIMA_FALHA["erro"] = f"{datetime.now():%d/%m %H:%M} · {type(e).__name__}: {str(e)[:160]}"
        raise


def _sgs_json(url):
    dados = _get(url).json()
    return [d for d in dados if d.get("valor") not in (None, "")]


def _sgs(serie: int, dias: int = 40):
    """Última observação de uma série do SGS: (valor, 'dd/mm/aaaa') ou None.

    Usa o endpoint /ultimos/1 — nao depende de janela de datas, entao
    devolve o valor VIGENTE mesmo para series que mudam raramente (a meta
    Selic so tem observacao nova a cada reuniao do Copom).
    """
    dados = _sgs_json(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados/ultimos/1?formato=json")
    if not dados:
        return None
    ult = dados[-1]
    return float(str(ult["valor"]).replace(",", ".")), ult["data"]


def _sgs_periodo(serie: int, ini: date, fim: date):
    url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{serie}/dados"
           f"?formato=json&dataInicial={ini:%d/%m/%Y}&dataFinal={fim:%d/%m/%Y}")
    return _sgs_json(url)


def _sgs_mes(serie: int, competencia: str):
    """Valor da série para um mês específico (séries mensais como CDI/poupança)."""
    y, m = int(competencia[:4]), int(competencia[5:7])
    ini = date(y, m, 1)
    fim = (date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1))
    dados = _sgs_periodo(serie, ini, fim)
    if not dados:
        return None
    return float(str(dados[-1]["valor"]).replace(",", "."))


# ── Indicadores ─────────────────────────────────────────────────────────────
def selic_atual():
    """Meta Selic vigente (% a.a.): (valor, origem)."""
    try:
        v, d = _sgs(SGS["selic"])
        db.set_cotacao("SELIC", v, origem=f"BCB {d}")
        return v, f"BCB · vigente desde {d}"
    except Exception:
        v, d = db.get_cotacao("SELIC")
        if v is not None:
            return v, f"cache · {d}"
        return db.get_config_float("selic_manual", db.get_config_float("cdi_anual_manual", 10.65)), "manual"


def cdi_anual():
    """CDI anualizado (% a.a., serie 4389): (valor, origem)."""
    try:
        v, d = _sgs(SGS["cdi_aa"])
        db.set_cotacao("CDI_AA", v, origem=f"BCB {d}")
        return v, f"BCB · {d}"
    except Exception:
        v, d = db.get_cotacao("CDI_AA")
        if v is not None:
            return v, f"cache · {d}"
        return db.get_config_float("cdi_anual_manual", 10.65), "manual"


def _mes_fechado(competencia: str) -> bool:
    return competencia < db.competencia_de(date.today())


def cdi_mensal(competencia: str):
    """CDI do mês em % a.m.: (valor, origem).

    - Mês FECHADO: serie 4391 (acumulado no mês), gravada em cache definitivo.
    - Mês CORRENTE: a 4391 ainda nao existe. Acumula a CDI diaria (serie 12)
      do dia 1 ate hoje — e' o que a carteira de fato rendeu ate agora.
      Se a diaria falhar, deriva do CDI anual (4389); por ultimo, do manual.
    """
    if _mes_fechado(competencia):
        v = db.get_benchmark(competencia, "CDI")
        if v is not None:
            return v, "BCB"
        try:
            v = _sgs_mes(SGS["cdi_mes"], competencia)
            if v is not None:
                db.set_benchmark(competencia, "CDI", v, "BCB")
                return v, "BCB"
        except Exception:
            pass
    else:
        y, m = int(competencia[:4]), int(competencia[5:7])
        try:
            dados = _sgs_periodo(SGS["cdi_dia"], date(y, m, 1), date.today())
            if dados:
                fator = 1.0
                for d in dados:
                    fator *= 1 + float(str(d["valor"]).replace(",", ".")) / 100
                return (fator - 1) * 100, f"BCB · acumulado até {dados[-1]['data']}"
        except Exception:
            pass
        try:
            aa, o = cdi_anual()
            if "manual" not in o:
                return ((1 + aa / 100) ** (1 / 12) - 1) * 100, f"≈ mensal do CDI {aa:.2f}% a.a."
        except Exception:
            pass
    anual = db.get_config_float("cdi_anual_manual", 10.65)
    return ((1 + anual / 100) ** (1 / 12) - 1) * 100, "manual"


def poupanca_mensal(competencia: str):
    v = db.get_benchmark(competencia, "POUPANCA")
    if v is not None:
        return v, "cache"
    try:
        v = _sgs_mes(SGS["poupanca_mes"], competencia)
        if v is not None:
            db.set_benchmark(competencia, "POUPANCA", v, "BCB")
            return v, "BCB"
    except Exception:
        pass
    return db.get_config_float("poupanca_mensal_manual", 0.6), "manual"


def ipca_mensal(competencia: str):
    v = db.get_benchmark(competencia, "IPCA")
    if v is not None:
        return v, "cache"
    try:
        v = _sgs_mes(SGS["ipca_mes"], competencia)
        if v is not None:
            db.set_benchmark(competencia, "IPCA", v, "IBGE/BCB")
            return v, "IBGE/BCB"
    except Exception:
        pass
    # IPCA do mes corrente so sai no mes seguinte: mostra o ultimo conhecido
    try:
        v, d = _sgs(SGS["ipca_mes"], 70)
        return v, f"último · {d}"
    except Exception:
        return None, "sem dado"


# ── Moedas e cripto ─────────────────────────────────────────────────────────
def cotacao_moeda(codigo: str):
    """USD ou EUR em BRL: (valor, origem)."""
    codigo = codigo.upper()
    try:
        v, d = _sgs(SGS[codigo], 15)
        db.set_cotacao(codigo, v, origem=f"BCB PTAX {d}")
        return v, f"PTAX · {d}"
    except Exception:
        v, d = db.get_cotacao(codigo)
        if v is not None:
            return v, f"cache · {d}"
        return db.get_config_float(f"{codigo.lower()}_manual", 5.0), "manual"


def cotacao_cripto(codigo: str):
    """Cripto em BRL via CoinGecko: (valor, origem)."""
    codigo = codigo.upper()
    cid = CRYPTO_IDS.get(codigo, codigo.lower())
    try:
        r = _get("https://api.coingecko.com/api/v3/simple/price",
                 params={"ids": cid, "vs_currencies": "brl"})
        v = float(r.json()[cid]["brl"])
        db.set_cotacao(codigo, v, origem="CoinGecko")
        return v, f"CoinGecko · {datetime.now():%d/%m %H:%M}"
    except Exception:
        v, d = db.get_cotacao(codigo)
        if v is not None:
            return v, f"cache · {d}"
        return None, "sem cotação"


def cotacao(codigo: str, moeda: str):
    if moeda in ("USD", "EUR"):
        return cotacao_moeda(moeda)
    if moeda == "CRYPTO":
        return cotacao_cripto(codigo or "BTC")
    return 1.0, "BRL"


def _lista_config(chave, padrao):
    v = db.get_config(chave, padrao) or ""
    return [x.strip().upper() if chave != "painel_indices" else x.strip().lower()
            for x in str(v).split(",") if x.strip()]


def painel_mercado(indices=None, moedas=None, criptos=None) -> list[dict]:
    """Lista de indicadores para o dashboard: [{nome, valor, fmt, origem}].

    Sem argumentos, usa a escolha feita em Configuracoes -> Cotacoes.
    """
    indices = _lista_config("painel_indices", "selic,cdi_mes") if indices is None else list(indices)
    moedas = _lista_config("painel_moedas", "USD,EUR") if moedas is None else list(moedas)
    criptos = _lista_config("painel_criptos", "BTC,ETH") if criptos is None else list(criptos)
    hoje = db.competencia_de(date.today())
    itens = []
    for ind in indices:
        if ind == "selic":
            v, o = selic_atual(); itens.append({"nome": "Selic (meta)", "valor": v, "fmt": "pct_aa", "origem": o})
        elif ind == "cdi_aa":
            v, o = cdi_anual(); itens.append({"nome": "CDI", "valor": v, "fmt": "pct_aa", "origem": o})
        elif ind == "cdi_mes":
            v, o = cdi_mensal(hoje); itens.append({"nome": "CDI do mês", "valor": v, "fmt": "pct_am", "origem": o})
        elif ind == "poupanca_mes":
            v, o = poupanca_mensal(hoje); itens.append({"nome": "Poupança", "valor": v, "fmt": "pct_am", "origem": o})
        elif ind == "ipca_mes":
            v, o = ipca_mensal(hoje)
            if v is not None:
                itens.append({"nome": "IPCA", "valor": v, "fmt": "pct_am", "origem": o})
    for m in moedas:
        if m in MOEDAS_DISPONIVEIS:
            v, o = cotacao_moeda(m)
            itens.append({"nome": "Dólar" if m == "USD" else "Euro", "valor": v, "fmt": "brl", "origem": o})
    for cr in criptos:
        v, o = cotacao_cripto(cr)
        if v is not None:
            itens.append({"nome": cr, "valor": v, "fmt": "brl0" if v >= 100 else "brl", "origem": o})
        else:
            itens.append({"nome": cr, "valor": None, "fmt": "brl", "origem": o})
    return itens
