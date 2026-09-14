"""Imposto de Renda — modelo, leitura de informes e apuração.

Sem interface aqui: este módulo lê PDFs/planilhas, reconhece o tipo de
informe, extrai os valores que consegue (sempre para o usuário REVISAR),
guarda tudo por ano-calendário nas fichas da declaração e calcula o
imposto pela tabela progressiva, comparando Completa × Simplificada.

Nada substitui o programa da Receita: o resultado é uma prévia e um
roteiro de digitação, ficha por ficha.
"""
from __future__ import annotations

import io
import json
import re
import unicodedata
from datetime import date

import pandas as pd

import db

# ── Fichas da declaração ────────────────────────────────────────────────────
FICHAS = {
    "tributaveis": "Rendimentos tributáveis (PJ)",
    "isentos": "Rendimentos isentos e não tributáveis",
    "exclusiva": "Tributação exclusiva / definitiva",
    "pagamentos": "Pagamentos efetuados (deduções)",
    "dependentes": "Dependentes",
    "bens": "Bens e direitos",
    "dividas": "Dívidas e ônus reais",
    "renda_variavel": "Renda variável (resultado mensal)",
}

# código -> descrição, por ficha. Os códigos seguem o programa da Receita;
# confira sempre no próprio programa, que pode mudar de um ano para outro.
CODIGOS = {
    "tributaveis": {
        "PJ": "Rendimentos recebidos de pessoa jurídica (salário, pró-labore, aposentadoria)",
        "PF": "Rendimentos recebidos de pessoa física / exterior (carnê-leão)",
        "ALUG": "Aluguéis recebidos de PJ",
    },
    "isentos": {
        "01": "Bolsas de estudo e pesquisa",
        "03": "Indenizações por rescisão de contrato de trabalho e FGTS",
        "09": "Lucros e dividendos recebidos",
        "10": "Parcela isenta de proventos de aposentadoria (65 anos ou mais)",
        "12": "Rendimentos de caderneta de poupança, LCI, LCA, CRI, CRA e letras hipotecárias",
        "13": "Rendimento de sócio ou titular de microempresa / empresa de pequeno porte (Simples)",
        "20": "Ganhos líquidos em ações (vendas até R$ 20 mil/mês) e ouro",
        "26": "Outros (incentivo à demissão, restituição de IR, transferências patrimoniais...)",
        "99": "Outros rendimentos isentos",
    },
    "exclusiva": {
        "06": "Rendimentos de aplicações financeiras (CDB, Tesouro, fundos...)",
        "10": "13º salário",
        "12": "Outros (PLR, juros sobre capital próprio...)",
        "11": "Participação nos lucros e resultados (PLR)",
        "03": "Ganhos líquidos em renda variável",
    },
    "pagamentos": {
        "01": "Instrução no Brasil (escola, faculdade, pós, técnico)",
        "10": "Médicos no Brasil",
        "11": "Dentistas no Brasil",
        "12": "Psicólogos no Brasil",
        "15": "Fisioterapeutas no Brasil",
        "21": "Hospitais, clínicas e laboratórios no Brasil",
        "26": "Planos de saúde no Brasil",
        "30": "Pensão alimentícia judicial",
        "36": "Previdência complementar (PGBL)",
        "37": "FAPI / previdência do servidor",
        "99": "Outros pagamentos (informativos, não dedutíveis)",
    },
    "bens": {
        "01-01": "Prédio residencial", "01-11": "Apartamento", "01-12": "Casa", "01-13": "Terreno",
        "02-01": "Veículo automotor terrestre",
        "03-01": "Participação societária (quotas / ações não negociadas)",
        "04-01": "Depósito em conta poupança",
        "04-02": "Títulos públicos e privados sujeitos à tributação (Tesouro Direto, CDB, RDB)",
        "04-03": "Títulos isentos (LCI, LCA, CRI, CRA, debêntures incentivadas)",
        "04-04": "Ações (inclusive listadas em bolsa)",
        "04-99": "Outras aplicações e investimentos",
        "06-01": "Depósito em conta corrente ou conta pagamento no Brasil",
        "06-10": "Depósito em conta no exterior",
        "07-01": "Fundos sujeitos à tributação periódica (come-cotas)",
        "07-02": "Fundos de investimento em ações",
        "07-03": "Fundos de investimento imobiliário (FII)",
        "07-09": "Demais fundos (previdência PGBL/VGBL: ver 99-?)",
        "08-01": "Criptoativo Bitcoin (BTC)",
        "08-02": "Outras criptomoedas (altcoins)",
        "08-03": "Stablecoins (USDT, USDC...)",
        "08-99": "Outros criptoativos",
        "09-01": "VGBL (previdência)",
        "09-99": "Moeda estrangeira em espécie / outros",
        "99-99": "Outros bens e direitos",
    },
    "dividas": {
        "11": "Estabelecimento bancário comercial",
        "12": "Sociedades de crédito, financiamento e investimento",
        "14": "Pessoas jurídicas",
        "15": "Pessoas físicas",
        "16": "Outras dívidas e ônus reais",
    },
    "dependentes": {
        "11": "Cônjuge / companheiro(a)",
        "21": "Filho(a) / enteado(a) até 21 anos",
        "22": "Filho(a) / enteado(a) universitário até 24 anos",
        "31": "Pais, avós, bisavós",
        "41": "Menor pobre sob guarda",
        "51": "Incapaz (tutela/curatela)",
    },
    "renda_variavel": {
        "ACOES": "Operações comuns em ações (swing trade)",
        "DAY": "Day trade",
        "FII": "Fundos imobiliários / Fiagro",
    },
}

TIPOS_INFORME = {
    "rendimentos_pj": "Comprovante de rendimentos (empregador / INSS / fonte pagadora)",
    "financeiro": "Informe de rendimentos financeiros (banco / corretora)",
    "saude": "Informe de plano de saúde / despesas médicas",
    "educacao": "Informe de instituição de ensino",
    "previdencia": "Informe de previdência privada (PGBL / VGBL)",
    "imovel_veiculo": "Bem: imóvel, veículo, financiamento",
    "outro": "Outro",
}

# ── Tabela progressiva e limites, por ano-calendário ───────────────────────
# Editável na tela (fica gravada em config como JSON). Os valores abaixo são
# os padrões; confira sempre com a tabela oficial da Receita do ano.
TABELAS_PADRAO = {
    2024: {  # DIRPF 2025
        "faixas": [[26963.20, 0.0, 0.0], [33919.80, 7.5, 2022.24], [45012.60, 15.0, 4566.23],
                   [55976.16, 22.5, 7942.17], [None, 27.5, 10740.98]],
        "dependente": 2275.08, "educacao": 3561.50, "simplificado_pct": 20.0, "simplificado_max": 16754.34,
        "pgbl_pct": 12.0, "reducao_baixa_renda": False, "obs": "Tabela anual do ano-calendário 2024 (DIRPF 2025)."},
    2025: {  # DIRPF 2026
        "faixas": [[27110.40, 0.0, 0.0], [33919.80, 7.5, 2033.28], [45012.60, 15.0, 4577.27],
                   [55976.16, 22.5, 7953.21], [None, 27.5, 10752.02]],
        "dependente": 2275.08, "educacao": 3561.50, "simplificado_pct": 20.0, "simplificado_max": 16754.34,
        "pgbl_pct": 12.0, "reducao_baixa_renda": False,
        "obs": "Ano-calendário 2025 (DIRPF 2026). Faixa isenta composta (jan-abr tabela antiga, mai-dez nova) — "
               "confira o valor oficial e ajuste aqui se precisar."},
    2026: {  # DIRPF 2027 — Lei 15.270/2025
        "faixas": [[27110.40, 0.0, 0.0], [33919.80, 7.5, 2033.28], [45012.60, 15.0, 4577.27],
                   [55976.16, 22.5, 7953.21], [None, 27.5, 10752.02]],
        "dependente": 2275.08, "educacao": 3561.50, "simplificado_pct": 20.0, "simplificado_max": 16754.34,
        "pgbl_pct": 12.0,
        "reducao_baixa_renda": True, "reducao_isento_ate": 60000.00, "reducao_zera_ate": 88200.00,
        "reducao_a": 11743.44, "reducao_b": 0.133145,
        "obs": "Ano-calendário 2026 (DIRPF 2027): isenção até R$ 5 mil/mês e redução decrescente até R$ 7.350/mês "
               "(Lei 15.270/2025), aplicada aqui em base anual (×12). Confira os parâmetros oficiais."},
}


def tabela(ano: int) -> dict:
    raw = db.get_config(f"ir_tabela_{ano}")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    base = TABELAS_PADRAO.get(ano) or TABELAS_PADRAO[max(TABELAS_PADRAO)]
    return json.loads(json.dumps(base))


def salvar_tabela(ano: int, t: dict):
    db.set_config(f"ir_tabela_{ano}", json.dumps(t))


# ── Schema ──────────────────────────────────────────────────────────────────
SCHEMA_IR = """
CREATE TABLE IF NOT EXISTS ir_informes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ano INTEGER NOT NULL, tipo TEXT NOT NULL,
    fonte TEXT, cnpj TEXT, arquivo_nome TEXT, arquivo BLOB, texto TEXT, dados_json TEXT, criado_em TEXT);
CREATE TABLE IF NOT EXISTS ir_lancamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ano INTEGER NOT NULL, ficha TEXT NOT NULL, codigo TEXT,
    descricao TEXT NOT NULL, cnpj_cpf TEXT, fonte TEXT, valor REAL DEFAULT 0, valor_ant REAL DEFAULT 0,
    mes INTEGER, informe_id INTEGER REFERENCES ir_informes(id) ON DELETE SET NULL, obs TEXT, criado_em TEXT);
CREATE INDEX IF NOT EXISTS idx_ir_lanc ON ir_lancamentos(ano, ficha);
"""


def iniciar():
    with db.conn() as c:
        c.executescript(SCHEMA_IR)


# ── CRUD ────────────────────────────────────────────────────────────────────
def add_informe(ano, tipo, fonte, cnpj, arquivo_nome, arquivo_bytes, texto, dados):
    return db.execute("INSERT INTO ir_informes (ano, tipo, fonte, cnpj, arquivo_nome, arquivo, texto, dados_json, criado_em) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (int(ano), tipo, fonte, cnpj, arquivo_nome, arquivo_bytes, texto, json.dumps(dados or {}),
                       db.agora()))


def informes(ano):
    return db.query("SELECT id, ano, tipo, fonte, cnpj, arquivo_nome, criado_em FROM ir_informes WHERE ano=? ORDER BY id DESC",
                    (int(ano),))


def arquivo_informe(id_):
    df = db.query("SELECT arquivo_nome, arquivo FROM ir_informes WHERE id=?", (int(id_),))
    return (df.iloc[0]["arquivo_nome"], df.iloc[0]["arquivo"]) if not df.empty else (None, None)


def del_informe(id_):
    db.execute("DELETE FROM ir_lancamentos WHERE informe_id=?", (int(id_),))
    db.execute("DELETE FROM ir_informes WHERE id=?", (int(id_),))


def add_lancamento(ano, ficha, codigo, descricao, valor, valor_ant=0, cnpj_cpf=None, fonte=None, mes=None,
                   informe_id=None, obs=None):
    return db.execute("""INSERT INTO ir_lancamentos (ano, ficha, codigo, descricao, cnpj_cpf, fonte, valor, valor_ant,
                         mes, informe_id, obs, criado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (int(ano), ficha, codigo, str(descricao).strip(), cnpj_cpf, fonte, float(valor or 0),
                       float(valor_ant or 0), mes, informe_id, obs, db.agora()))


def lancamentos(ano, ficha=None):
    sql = "SELECT * FROM ir_lancamentos WHERE ano=?"
    p = [int(ano)]
    if ficha:
        sql += " AND ficha=?"; p.append(ficha)
    return db.query(sql + " ORDER BY ficha, codigo, id", p)


def atualizar_lancamento(id_, codigo, descricao, cnpj_cpf, valor, valor_ant, obs):
    db.execute("UPDATE ir_lancamentos SET codigo=?, descricao=?, cnpj_cpf=?, valor=?, valor_ant=?, obs=? WHERE id=?",
               (codigo, str(descricao).strip(), cnpj_cpf, float(valor or 0), float(valor_ant or 0), obs, int(id_)))


def del_lancamento(id_):
    db.execute("DELETE FROM ir_lancamentos WHERE id=?", (int(id_),))


def anos_com_dados():
    df = db.query("SELECT DISTINCT ano FROM ir_lancamentos UNION SELECT DISTINCT ano FROM ir_informes ORDER BY ano DESC")
    return [int(a) for a in df["ano"].tolist()]


# ── Leitura de arquivos ─────────────────────────────────────────────────────
def texto_do_arquivo(nome: str, dados: bytes) -> str:
    n = nome.lower()
    if n.endswith(".pdf"):
        try:
            import pdfplumber
            partes = []
            with pdfplumber.open(io.BytesIO(dados)) as pdf:
                for pg in pdf.pages:
                    partes.append(pg.extract_text() or "")
            txt = "\n".join(partes)
            if txt.strip():
                return txt
        except Exception:
            pass
        return ""   # PDF só imagem: precisa digitar
    if n.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(dados), header=None)
        return "\n".join(" ".join(str(x) for x in r if pd.notna(x)) for r in df.values.tolist())
    if n.endswith((".csv", ".txt")):
        for enc in ("utf-8-sig", "latin-1"):
            try:
                return dados.decode(enc)
            except Exception:
                continue
    return ""


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[ \t]+", " ", t)


_VALOR = r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})"


def _num(txt) -> float | None:
    if txt is None:
        return None
    t = str(txt).replace(".", "").replace(",", ".").replace("R$", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _valor_apos(texto_norm: str, rotulos: list[str]) -> float | None:
    """Primeiro valor monetário na mesma linha (ou na seguinte) de um rótulo."""
    linhas = texto_norm.split("\n")
    for i, ln in enumerate(linhas):
        for r in rotulos:
            if r in ln:
                m = re.findall(_VALOR, ln)
                if m:
                    return _num(m[-1])
                if i + 1 < len(linhas):
                    m = re.findall(_VALOR, linhas[i + 1])
                    if m:
                        return _num(m[0])
    return None


def _cnpj(texto: str):
    m = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", texto)
    return m.group(0) if m else None


def _ano_no_texto(texto: str):
    m = re.search(r"ano[- ]calend[aá]rio[^\d]{0,20}(20\d{2})", _norm(texto))
    if m:
        return int(m.group(1))
    m = re.search(r"exerc[ií]cio[^\d]{0,20}(20\d{2})", _norm(texto))
    if m:
        return int(m.group(1)) - 1
    anos = re.findall(r"31/12/(20\d{2})", texto)
    if anos:
        return max(int(a) for a in anos)
    return None


def detectar_tipo(texto: str) -> str:
    t = _norm(texto)
    if "comprovante de rendimentos" in t or "rendimentos pagos e de imposto" in t or "fonte pagadora" in t:
        return "rendimentos_pj"
    if "plano de sa" in t or "operadora" in t or "mensalidade" in t and "sa" in t:
        return "saude"
    if "pgbl" in t or "vgbl" in t or "previd" in t and "complementar" in t:
        return "previdencia"
    if "informe de rendimentos" in t or "saldo em 31/12" in t or "saldos em 31/12" in t or "aplica" in t:
        return "financeiro"
    if "matr" in t and ("mensalidade" in t or "anuidade" in t) or "instituicao de ensino" in t:
        return "educacao"
    return "outro"


def extrair(texto: str, tipo: str, ano: int) -> list[dict]:
    """Candidatos a lançamento a partir do texto do informe. Sempre revisar."""
    t = _norm(texto)
    cnpj = _cnpj(texto)
    fonte = None
    m = re.search(r"(?:fonte pagadora|raz[aã]o social|nome empresarial)[:\s]*([^\n]{3,80})", t)
    if m:
        fonte = re.split(r"\s+cnpj|\s+cpf|\d{2}\.\d{3}\.", m.group(1))[0].strip(" :-").title()
    out = []

    def add(ficha, codigo, descricao, valor, valor_ant=0.0):
        if valor is not None and abs(valor) > 0:
            out.append({"ficha": ficha, "codigo": codigo, "descricao": descricao, "valor": float(valor),
                        "valor_ant": float(valor_ant or 0), "cnpj_cpf": cnpj, "fonte": fonte})

    if tipo == "rendimentos_pj":
        add("tributaveis", "PJ", "Total dos rendimentos (inclusive férias)",
            _valor_apos(t, ["total dos rendimentos"]))
        add("tributaveis", "PREV", "Contribuição previdenciária oficial (INSS)",
            _valor_apos(t, ["contribuicao previdenciaria oficial"]))
        add("tributaveis", "PREVC", "Contribuição a entidade de previdência complementar",
            _valor_apos(t, ["previdencia complementar", "previdencia privada"]))
        add("tributaveis", "PENSAO", "Pensão alimentícia",
            _valor_apos(t, ["pensao alimenticia"]))
        add("tributaveis", "IRRF", "Imposto sobre a renda retido na fonte",
            _valor_apos(t, ["imposto sobre a renda retido na fonte", "imposto de renda retido na fonte",
                            "irrf"]))
        add("exclusiva", "10", "13º salário", _valor_apos(t, ["13o salario", "13 salario", "decimo terceiro"]))
        add("exclusiva", "10-IR", "IRRF sobre 13º salário",
            _valor_apos(t, ["imposto sobre a renda retido na fonte sobre 13", "irrf sobre 13", "sobre o 13"]))
        add("exclusiva", "11", "PLR — participação nos lucros", _valor_apos(t, ["participacao nos lucros", "plr"]))
        add("isentos", "03", "Indenizações / FGTS", _valor_apos(t, ["indenizacoes", "fgts"]))
        add("isentos", "26", "Diárias e ajuda de custo", _valor_apos(t, ["diarias", "ajuda de custo"]))
        add("isentos", "10", "Parcela isenta de aposentadoria (65+)", _valor_apos(t, ["parcela isenta"]))
    elif tipo == "financeiro":
        # linhas "descricao ... saldo 31/12/ano-1 ... saldo 31/12/ano"
        atu = f"31/12/{ano}"
        for ln in texto.split("\n"):
            vals = re.findall(_VALOR, ln)
            nl = _norm(ln)
            if not vals:
                continue
            desc = re.split(_VALOR, ln)[0].strip(" -:") or "Aplicação"
            codigo = "04-02"
            if "poupan" in nl:
                codigo = "04-01"
            elif "conta corrente" in nl or "conta pagamento" in nl or "conta corrente" in nl:
                codigo = "06-01"
            elif "lci" in nl or "lca" in nl or "cri" in nl or "cra" in nl:
                codigo = "04-03"
            elif "acoes" in nl or "ações" in ln.lower():
                codigo = "04-04"
            elif "fii" in nl or "imobiliario" in nl:
                codigo = "07-03"
            elif "fundo" in nl:
                codigo = "07-01"
            elif "bitcoin" in nl or "btc" in nl:
                codigo = "08-01"
            elif "cripto" in nl:
                codigo = "08-02"
            if "rendiment" in nl and "saldo" not in nl:
                cod_r = "12" if codigo in ("04-01", "04-03") else "06"
                add("isentos" if cod_r == "12" else "exclusiva", cod_r, desc[:80], _num(vals[-1]))
                continue
            if len(vals) >= 2:
                add("bens", codigo, desc[:80], _num(vals[-1]), _num(vals[-2]))
            elif atu in ln or "31/12" in ln:
                add("bens", codigo, desc[:80], _num(vals[-1]))
    elif tipo == "saude":
        add("pagamentos", "26", f"Plano de saúde — {fonte or 'operadora'}",
            _valor_apos(t, ["total", "valor pago", "mensalidades"]))
    elif tipo == "educacao":
        add("pagamentos", "01", f"Instrução — {fonte or 'instituição'}", _valor_apos(t, ["total", "valor pago"]))
    elif tipo == "previdencia":
        add("pagamentos", "36", f"PGBL — {fonte or 'previdência'}",
            _valor_apos(t, ["contribuicoes", "total das contribuicoes", "valor pago"]))
        add("bens", "09-01", f"VGBL — {fonte or 'previdência'}", _valor_apos(t, ["saldo em 31/12", "saldo"]))
    return out


# ── Sugestões a partir do próprio sistema ───────────────────────────────────
def sugestoes_do_sistema(ano: int) -> list[dict]:
    """Lançamentos que o sistema consegue propor com o que já está cadastrado."""
    out = []
    # investimentos: saldo em 31/12 do ano e do anterior -> bens e direitos
    comp_fim, comp_ant = f"{ano}-12", f"{ano - 1}-12"
    mov = db.movimentos()
    if not mov.empty:
        for iid, g in mov.groupby("investimento_id"):
            g = g.sort_values("competencia")
            atual = g[g["competencia"] <= comp_fim]
            ant = g[g["competencia"] <= comp_ant]
            if atual.empty:
                continue
            s_atual = float(atual["saldo_final"].iloc[-1])
            s_ant = float(ant["saldo_final"].iloc[-1]) if not ant.empty else 0.0
            tipo = str(g["tipo"].iloc[0]); nome = str(g["nome"].iloc[0])
            cod = {"Poupança": "04-01", "CDB / RDB": "04-02", "Tesouro Direto": "04-02", "LCI / LCA": "04-03",
                   "Fundo": "07-01", "Ações": "04-04", "FII": "07-03", "Previdência": "09-01",
                   "Criptomoeda": "08-01" if "BTC" in (str(g["ativo_codigo"].iloc[0]) or "") else "08-02",
                   "Dólar": "09-99", "Euro": "09-99"}.get(tipo, "04-99")
            out.append({"ficha": "bens", "codigo": cod, "descricao": f"{nome} ({tipo})", "valor": s_atual,
                        "valor_ant": s_ant, "cnpj_cpf": None, "fonte": "Investimentos do sistema"})
            rend = float(g[(g["competencia"] > comp_ant) & (g["competencia"] <= comp_fim)]["rendimento"].sum()) \
                if "rendimento" in g.columns else 0.0
            if rend > 0:
                if tipo in ("Poupança", "LCI / LCA"):
                    out.append({"ficha": "isentos", "codigo": "12", "descricao": f"Rendimentos {nome}",
                                "valor": rend, "valor_ant": 0, "cnpj_cpf": None, "fonte": "Investimentos do sistema"})
                elif tipo in ("CDB / RDB", "Tesouro Direto", "Fundo"):
                    out.append({"ficha": "exclusiva", "codigo": "06", "descricao": f"Rendimentos {nome}",
                                "valor": rend, "valor_ant": 0, "cnpj_cpf": None, "fonte": "Investimentos do sistema"})
    # créditos: salário do ano (estimativa) -> tributáveis
    cred = db.query("SELECT t.nome tipo, SUM(c.valor) v FROM creditos c LEFT JOIN tipos_credito t ON t.id=c.tipo_id "
                    "WHERE substr(c.competencia,1,4)=? GROUP BY t.nome", (str(ano),))
    for _, r in cred.iterrows():
        if r["tipo"] in ("Salário", "Horas extras", "Férias"):
            out.append({"ficha": "tributaveis", "codigo": "PJ", "descricao": f"{r['tipo']} lançado no sistema (bruto?)",
                        "valor": float(r["v"]), "valor_ant": 0, "cnpj_cpf": None, "fonte": "Créditos do sistema"})
        elif r["tipo"] == "13º salário":
            out.append({"ficha": "exclusiva", "codigo": "10", "descricao": "13º salário lançado no sistema",
                        "valor": float(r["v"]), "valor_ant": 0, "cnpj_cpf": None, "fonte": "Créditos do sistema"})
    # gastos dedutíveis: saúde e educação
    g = db.query("""SELECT c.grupo, c.nome, SUM(l.valor) v FROM lancamentos l JOIN categorias c ON c.id=l.categoria_id
                    WHERE substr(l.data,1,4)=? AND (c.grupo IN ('Saúde','Educação')) GROUP BY c.grupo, c.nome""",
                 (str(ano),))
    for _, r in g.iterrows():
        cod = "01" if r["grupo"] == "Educação" else ("26" if "plano" in r["nome"].lower() else "21")
        out.append({"ficha": "pagamentos", "codigo": cod, "descricao": f"{r['nome']} (gastos do sistema — só se tiver recibo/NF)",
                    "valor": float(r["v"]), "valor_ant": 0, "cnpj_cpf": None, "fonte": "Gastos do sistema"})
    fx = db.query("""SELECT t.nome, SUM(l.valor) v FROM fixos_lancamentos l JOIN fixos_tipos t ON t.id=l.tipo_id
                     WHERE substr(l.competencia,1,4)=? AND l.pago=1 GROUP BY t.nome""", (str(ano),))
    for _, r in fx.iterrows():
        n = r["nome"].upper()
        if "PÓS" in n or "POS-GRAD" in n or "FACULDADE" in n or "ESCOLA" in n or "CURSO" in n:
            out.append({"ficha": "pagamentos", "codigo": "01", "descricao": f"{r['nome']} (fixos do sistema)",
                        "valor": float(r["v"]), "valor_ant": 0, "cnpj_cpf": None, "fonte": "Fixos do sistema"})
        if "PLANO" in n and "SA" in n:
            out.append({"ficha": "pagamentos", "codigo": "26", "descricao": f"{r['nome']} (fixos do sistema)",
                        "valor": float(r["v"]), "valor_ant": 0, "cnpj_cpf": None, "fonte": "Fixos do sistema"})
    return out


# ── Apuração ────────────────────────────────────────────────────────────────
def _imposto_tabela(base: float, faixas) -> float:
    if base <= 0:
        return 0.0
    for lim, aliq, ded in faixas:
        if lim is None or base <= lim:
            return max(0.0, base * aliq / 100 - ded)
    return 0.0


def apurar(ano: int) -> dict:
    t = tabela(ano)
    df = lancamentos(ano)

    def soma(ficha, codigos=None, excluir=None):
        d = df[df["ficha"] == ficha]
        if codigos:
            d = d[d["codigo"].isin(codigos)]
        if excluir:
            d = d[~d["codigo"].isin(excluir)]
        return float(d["valor"].sum()) if not d.empty else 0.0

    trib = soma("tributaveis", excluir=["PREV", "PREVC", "PENSAO", "IRRF"])
    inss = soma("tributaveis", ["PREV"])
    prev_comp = soma("tributaveis", ["PREVC"]) + soma("pagamentos", ["36", "37"])
    pensao = soma("tributaveis", ["PENSAO"]) + soma("pagamentos", ["30"])
    irrf = soma("tributaveis", ["IRRF"])
    n_dep = int(len(df[df["ficha"] == "dependentes"]))
    saude = soma("pagamentos", ["10", "11", "12", "15", "21", "26"])
    educ_bruta = soma("pagamentos", ["01"])
    educ = min(educ_bruta, t["educacao"] * (1 + n_dep))  # limite por pessoa (titular + dependentes)
    pgbl = min(prev_comp, trib * t["pgbl_pct"] / 100)
    deducoes = inss + pgbl + pensao + saude + educ + n_dep * t["dependente"]

    base_completa = max(0.0, trib - deducoes)
    imp_completa = _imposto_tabela(base_completa, t["faixas"])
    desc_simpl = min(trib * t["simplificado_pct"] / 100, t["simplificado_max"])
    base_simpl = max(0.0, trib - desc_simpl)
    imp_simpl = _imposto_tabela(base_simpl, t["faixas"])

    # Redução para renda baixa (2026+): zera até X e reduz linearmente até Y
    red_c = red_s = 0.0
    if t.get("reducao_baixa_renda"):
        if trib <= t["reducao_isento_ate"]:
            red_c, red_s = imp_completa, imp_simpl
        elif trib <= t["reducao_zera_ate"]:
            r = max(0.0, t["reducao_a"] - t["reducao_b"] * trib)
            red_c, red_s = min(imp_completa, r), min(imp_simpl, r)
    imp_completa -= red_c
    imp_simpl -= red_s

    melhor = "completa" if imp_completa < imp_simpl else "simplificada"
    imp = min(imp_completa, imp_simpl)
    saldo = imp - irrf  # >0 a pagar, <0 restituir

    isentos = soma("isentos")
    exclus = soma("exclusiva", excluir=["10-IR"])
    ir13 = soma("exclusiva", ["10-IR"])
    bens = df[df["ficha"] == "bens"]
    patrimonio = float(bens["valor"].sum()) if not bens.empty else 0.0
    patrimonio_ant = float(bens["valor_ant"].sum()) if not bens.empty else 0.0
    dividas = soma("dividas")
    rv = df[df["ficha"] == "renda_variavel"]
    rv_ganho = float(rv["valor"].sum()) if not rv.empty else 0.0

    # variação patrimonial x renda: sinal de inconsistência que a Receita olha
    renda_total = trib + isentos + exclus
    var_patrim = patrimonio - patrimonio_ant
    return {
        "tributaveis": trib, "inss": inss, "pgbl": pgbl, "pensao": pensao, "saude": saude, "educacao": educ,
        "educacao_bruta": educ_bruta, "dependentes": n_dep, "ded_dependentes": n_dep * t["dependente"],
        "deducoes": deducoes, "base_completa": base_completa, "imposto_completa": imp_completa,
        "desconto_simplificado": desc_simpl, "base_simplificada": base_simpl, "imposto_simplificada": imp_simpl,
        "reducao_aplicada": max(red_c, red_s), "melhor": melhor, "imposto": imp, "irrf": irrf, "saldo": saldo,
        "isentos": isentos, "exclusiva": exclus, "ir_13": ir13, "patrimonio": patrimonio,
        "patrimonio_ant": patrimonio_ant, "dividas": dividas, "renda_total": renda_total,
        "variacao_patrimonial": var_patrim, "renda_variavel": rv_ganho, "tabela": t,
        "aliquota_efetiva": (imp / trib * 100) if trib else 0.0,
        "obrigatoria": (trib > 33888.0) or (isentos + exclus > 200000.0) or (patrimonio > 800000.0) or rv_ganho != 0,
    }


def alertas(ano: int, ap: dict) -> list[tuple[str, str]]:
    a = []
    if ap["tributaveis"] == 0:
        a.append(("atencao", "Nenhum rendimento tributável lançado — importe o comprovante do empregador/INSS."))
    if ap["irrf"] == 0 and ap["tributaveis"] > 30000:
        a.append(("atencao", "Rendimentos tributáveis sem IRRF informado: confira o comprovante (linha 5)."))
    if ap["variacao_patrimonial"] > ap["renda_total"] and ap["renda_total"] > 0:
        a.append(("serio", f"Patrimônio cresceu {ap['variacao_patrimonial']:,.0f} com renda declarada de "
                           f"{ap['renda_total']:,.0f}: a Receita cruza isso. Falta algum rendimento ou saldo anterior?"))
    if ap["educacao_bruta"] > ap["educacao"]:
        a.append(("atencao", f"Educação acima do limite por pessoa: só {ap['educacao']:,.2f} serão deduzidos."))
    if ap["melhor"] == "simplificada" and ap["deducoes"] > 0:
        a.append(("bom", "A simplificada sai melhor: não precisa juntar recibos de saúde/educação (mas guarde-os)."))
    if ap["melhor"] == "completa":
        a.append(("bom", f"A completa economiza {ap['imposto_simplificada'] - ap['imposto_completa']:,.2f} "
                         "em relação à simplificada — tenha os comprovantes das deduções."))
    if ap["obrigatoria"]:
        a.append(("atencao", "Pelos valores lançados, a entrega da declaração é obrigatória."))
    return a


# ── Exportação ──────────────────────────────────────────────────────────────
def roteiro_excel(ano: int) -> bytes:
    df = lancamentos(ano)
    ap = apurar(ano)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        res = pd.DataFrame([{"Item": k, "Valor": v} for k, v in ap.items() if k != "tabela"])
        res.to_excel(w, index=False, sheet_name="Apuração")
        for ficha, rot in FICHAS.items():
            d = df[df["ficha"] == ficha]
            if d.empty:
                continue
            d = d[["codigo", "descricao", "cnpj_cpf", "fonte", "valor_ant", "valor", "mes", "obs"]].rename(columns={
                "codigo": "Código", "descricao": "Descrição", "cnpj_cpf": "CNPJ/CPF", "fonte": "Fonte",
                "valor_ant": f"Situação 31/12/{ano - 1}", "valor": f"Valor / 31/12/{ano}", "mes": "Mês", "obs": "Obs"})
            d.to_excel(w, index=False, sheet_name=re.sub(r"[\/\\?*\[\]:]", "-", rot)[:28])
    return buf.getvalue()
