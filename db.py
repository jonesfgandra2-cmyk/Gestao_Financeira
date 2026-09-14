"""Camada de dados: SQLite local, schema, dados padrão e funções de acesso.

Tudo que toca o banco passa por aqui. As páginas nunca escrevem SQL.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime

import pandas as pd

DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_PATH = os.environ.get("FINANCEIRO_DB", os.path.join(DB_DIR, "financeiro.db"))

# ── Dados padrão ────────────────────────────────────────────────────────────
TIPOS_CREDITO_PADRAO = ["Salário", "Horas extras", "13º salário", "Férias",
                        "Bônus / PLR", "Reembolso", "Outros"]

# (nome, valor previsto, dia de vencimento)
FIXOS_PADRAO = [
    ("ALUGUEL", 0, 10), ("ENERGIA", 0, 15), ("GÁS", 0, 15), ("INTERNET", 0, 20),
    ("CARONA", 0, 5), ("FATURA VIVO", 0, 10), ("CROSSFIT", 0, 5),
    ("PÓS-GRADUAÇÃO", 0, 10), ("SEGURO AUTOMOTIVO", 0, 15),
]

# Modalidades (grupos) e categorias de gasto variável (cartão / débito)
CATEGORIAS_PADRAO = [
    ("Alimentação/Lazer", "Ifood / Delivery"), ("Alimentação/Lazer", "Restaurante / Bar"),
    ("Alimentação/Lazer", "Lazer / Passeios"), ("Alimentação/Lazer", "Streaming / Assinaturas"),
    ("Despesa Casa", "Supermercado (Coopercica)"), ("Despesa Casa", "Farmácia"),
    ("Despesa Casa", "Manutenção / Utensílios"), ("Despesa Casa", "Pet"),
    ("Transporte", "Combustível"), ("Transporte", "Estacionamento / Pedágio"),
    ("Transporte", "Uber / Transporte"), ("Transporte", "Manutenção do carro"),
    ("Compras Diversas", "Enjoei / Marketplace"), ("Compras Diversas", "Roupas / Calçados"),
    ("Compras Diversas", "Eletrônicos"), ("Compras Diversas", "Presentes"),
    ("Saúde", "Consultas / Exames"), ("Saúde", "Academia / Esporte"),
    ("Educação", "Cursos / Livros"),
    ("Outros", "Outros"),
]

TIPOS_PLANO = ["Viagem", "Troca de carro", "Compra de casa", "Celular novo",
               "Reserva de emergência", "Eletrodoméstico", "Reforma", "Outro"]

# tipo, moeda base, precisa de cotação?
TIPOS_INVESTIMENTO = {
    "Poupança": ("BRL", False), "CDB / RDB": ("BRL", False), "Tesouro Direto": ("BRL", False),
    "LCI / LCA": ("BRL", False), "Fundo": ("BRL", False), "Ações": ("BRL", False),
    "FII": ("BRL", False), "Previdência": ("BRL", False),
    "Criptomoeda": ("CRYPTO", True), "Dólar": ("USD", True), "Euro": ("EUR", True),
    "Outro": ("BRL", False),
}

CONFIG_PADRAO = {
    "cdi_anual_manual": "10.65",     # % a.a. — usado se a API do BCB falhar
    "poupanca_mensal_manual": "0.60",  # % a.m.
    "limite_baixo_rendimento": "70",   # % do CDI: abaixo disso = baixo rendimento
    "limite_oportunidade": "120",      # % do CDI: acima disso = destaque
    "meta_taxa_poupanca": "20",        # % da renda que deveria sobrar
    "alerta_cartao_pct_renda": "35",   # cartão acima disso da renda = alerta
    "usd_manual": "5.20", "eur_manual": "5.70",
    # painel de mercado do dashboard (o usuario escolhe em Configuracoes)
    "painel_indices": "selic,cdi_mes",
    "painel_moedas": "USD,EUR",
    "painel_criptos": "BTC,ETH",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT UNIQUE NOT NULL, nome TEXT, senha_hash TEXT NOT NULL, salt TEXT NOT NULL,
    admin INTEGER DEFAULT 0, criado_em TEXT
);
CREATE TABLE IF NOT EXISTS config (chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS tipos_credito (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL, ativo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS creditos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, competencia TEXT NOT NULL, data TEXT NOT NULL,
    tipo_id INTEGER REFERENCES tipos_credito(id), descricao TEXT, valor REAL NOT NULL,
    criado_em TEXT);
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT, grupo TEXT NOT NULL, nome TEXT NOT NULL,
    ativo INTEGER DEFAULT 1, UNIQUE(grupo, nome));
CREATE TABLE IF NOT EXISTS fixos_tipos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL,
    valor_previsto REAL DEFAULT 0, dia_vencimento INTEGER DEFAULT 10, ativo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS fixos_lancamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, competencia TEXT NOT NULL,
    tipo_id INTEGER NOT NULL REFERENCES fixos_tipos(id), valor REAL NOT NULL,
    pago INTEGER DEFAULT 0, data_pagamento TEXT, obs TEXT, UNIQUE(competencia, tipo_id));
CREATE TABLE IF NOT EXISTS cartoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE NOT NULL, bandeira TEXT,
    dia_fechamento INTEGER NOT NULL, dia_vencimento INTEGER NOT NULL, limite REAL DEFAULT 0,
    ativo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS lancamentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL,
    modalidade TEXT NOT NULL CHECK (modalidade IN ('CARTAO','DEBITO')),
    cartao_id INTEGER REFERENCES cartoes(id), estabelecimento TEXT NOT NULL,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id), valor REAL NOT NULL,
    parcela_num INTEGER DEFAULT 1, parcelas INTEGER DEFAULT 1, grupo_parcela TEXT,
    competencia TEXT NOT NULL, obs TEXT, criado_em TEXT);
CREATE INDEX IF NOT EXISTS idx_lanc_comp ON lancamentos(competencia, modalidade);
CREATE TABLE IF NOT EXISTS planos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, tipo TEXT NOT NULL,
    valor_alvo REAL NOT NULL, data_alvo TEXT, prioridade INTEGER DEFAULT 2,
    status TEXT DEFAULT 'Em andamento', obs TEXT, criado_em TEXT);
CREATE TABLE IF NOT EXISTS planos_aportes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, plano_id INTEGER NOT NULL REFERENCES planos(id) ON DELETE CASCADE,
    data TEXT NOT NULL, valor REAL NOT NULL, obs TEXT);
CREATE TABLE IF NOT EXISTS investimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, tipo TEXT NOT NULL,
    instituicao TEXT, moeda TEXT DEFAULT 'BRL', ativo_codigo TEXT, ativo INTEGER DEFAULT 1,
    criado_em TEXT);
CREATE TABLE IF NOT EXISTS inv_movimentos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investimento_id INTEGER NOT NULL REFERENCES investimentos(id) ON DELETE CASCADE,
    competencia TEXT NOT NULL, aporte REAL DEFAULT 0, resgate REAL DEFAULT 0,
    quantidade REAL, cotacao REAL, saldo_final REAL NOT NULL, obs TEXT,
    UNIQUE(investimento_id, competencia));
CREATE TABLE IF NOT EXISTS metas (
    id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL CHECK (tipo IN ('mensal','anual','prazo')),
    descricao TEXT, valor REAL NOT NULL, anos INTEGER, data_inicio TEXT, ativo INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS benchmark (
    competencia TEXT NOT NULL, indice TEXT NOT NULL, valor REAL NOT NULL, origem TEXT,
    PRIMARY KEY (competencia, indice));
CREATE TABLE IF NOT EXISTS mapa_import (
    chave TEXT PRIMARY KEY, categoria_id INTEGER REFERENCES categorias(id));
CREATE TABLE IF NOT EXISTS cotacoes (
    data TEXT NOT NULL, codigo TEXT NOT NULL, valor REAL NOT NULL, origem TEXT,
    PRIMARY KEY (data, codigo));
"""


# ── Conexão ─────────────────────────────────────────────────────────────────
@contextmanager
def conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def query(sql, params=()) -> pd.DataFrame:
    with conn() as c:
        return pd.read_sql_query(sql, c, params=params)


def execute(sql, params=()):
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def agora():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── Senhas ──────────────────────────────────────────────────────────────────
def _hash(senha: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", senha.encode(), salt.encode(), 120_000).hex()


def criar_usuario(usuario, nome, senha, admin=False):
    salt = secrets.token_hex(16)
    execute("INSERT INTO usuarios (usuario, nome, senha_hash, salt, admin, criado_em) "
            "VALUES (?,?,?,?,?,?)",
            (usuario.strip().lower(), nome.strip(), _hash(senha, salt), salt, int(admin), agora()))


def autenticar(usuario, senha):
    df = query("SELECT * FROM usuarios WHERE usuario = ?", (usuario.strip().lower(),))
    if df.empty:
        return None
    r = df.iloc[0]
    if _hash(senha, r["salt"]) == r["senha_hash"]:
        return {"id": int(r["id"]), "usuario": r["usuario"], "nome": r["nome"], "admin": bool(r["admin"])}
    return None


def trocar_senha(usuario_id, nova):
    salt = secrets.token_hex(16)
    execute("UPDATE usuarios SET senha_hash=?, salt=? WHERE id=?", (_hash(nova, salt), salt, usuario_id))


def tem_usuarios() -> bool:
    return int(query("SELECT COUNT(*) n FROM usuarios").iloc[0]["n"]) > 0


# ── Inicialização ───────────────────────────────────────────────────────────
def iniciar_banco():
    with conn() as c:
        c.executescript(SCHEMA)
        for nome in TIPOS_CREDITO_PADRAO:
            c.execute("INSERT OR IGNORE INTO tipos_credito (nome) VALUES (?)", (nome,))
        for nome, valor, dia in FIXOS_PADRAO:
            c.execute("INSERT OR IGNORE INTO fixos_tipos (nome, valor_previsto, dia_vencimento) "
                      "VALUES (?,?,?)", (nome, valor, dia))
        for grupo, nome in CATEGORIAS_PADRAO:
            c.execute("INSERT OR IGNORE INTO categorias (grupo, nome) VALUES (?,?)", (grupo, nome))
        for k, v in CONFIG_PADRAO.items():
            c.execute("INSERT OR IGNORE INTO config (chave, valor) VALUES (?,?)", (k, v))


# ── Config ──────────────────────────────────────────────────────────────────
def get_config(chave, default=None):
    df = query("SELECT valor FROM config WHERE chave=?", (chave,))
    return df.iloc[0]["valor"] if not df.empty else default


def get_config_float(chave, default=0.0):
    try:
        return float(str(get_config(chave, default)).replace(",", "."))
    except Exception:
        return float(default)


def set_config(chave, valor):
    execute("INSERT INTO config (chave, valor) VALUES (?,?) "
            "ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (chave, str(valor)))


# ── Competência ─────────────────────────────────────────────────────────────
def competencia_de(d: date) -> str:
    return d.strftime("%Y-%m")


def somar_meses(comp: str, n: int) -> str:
    y, m = int(comp[:4]), int(comp[5:7])
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def competencia_cartao(data_compra: date, dia_fechamento: int) -> str:
    """Compra depois do fechamento entra na fatura do mês seguinte."""
    comp = competencia_de(data_compra)
    return somar_meses(comp, 1) if data_compra.day > dia_fechamento else comp


# ── Créditos ────────────────────────────────────────────────────────────────
def tipos_credito(ativos=True):
    return query("SELECT * FROM tipos_credito" + (" WHERE ativo=1" if ativos else "") + " ORDER BY nome")


def add_credito(competencia, data, tipo_id, descricao, valor):
    return execute("INSERT INTO creditos (competencia, data, tipo_id, descricao, valor, criado_em) "
                   "VALUES (?,?,?,?,?,?)", (competencia, str(data), tipo_id, descricao, valor, agora()))


def creditos(competencia=None):
    sql = ("SELECT c.id, c.competencia, c.data, t.nome AS tipo, c.descricao, c.valor "
           "FROM creditos c LEFT JOIN tipos_credito t ON t.id=c.tipo_id")
    if competencia:
        return query(sql + " WHERE c.competencia=? ORDER BY c.data DESC", (competencia,))
    return query(sql + " ORDER BY c.data DESC")


def del_credito(id_):
    execute("DELETE FROM creditos WHERE id=?", (id_,))


# ── Categorias / fixos / cartões ───────────────────────────────────────────
def categorias(ativas=True):
    return query("SELECT * FROM categorias" + (" WHERE ativo=1" if ativas else "") + " ORDER BY grupo, nome")


def add_categoria(grupo, nome):
    execute("INSERT OR IGNORE INTO categorias (grupo, nome) VALUES (?,?)", (grupo.strip(), nome.strip()))


def set_categoria_ativa(id_, ativo):
    execute("UPDATE categorias SET ativo=? WHERE id=?", (int(ativo), id_))


def fixos_tipos(ativos=True):
    return query("SELECT * FROM fixos_tipos" + (" WHERE ativo=1" if ativos else "") + " ORDER BY nome")


def add_fixo_tipo(nome, valor_previsto, dia):
    execute("INSERT INTO fixos_tipos (nome, valor_previsto, dia_vencimento) VALUES (?,?,?) "
            "ON CONFLICT(nome) DO UPDATE SET valor_previsto=excluded.valor_previsto, "
            "dia_vencimento=excluded.dia_vencimento, ativo=1", (nome.strip().upper(), valor_previsto, dia))


def set_fixo_tipo_ativo(id_, ativo):
    execute("UPDATE fixos_tipos SET ativo=? WHERE id=?", (int(ativo), id_))


def atualizar_fixo_tipo(id_, nome, valor_previsto, dia, ativo):
    execute("UPDATE fixos_tipos SET nome=?, valor_previsto=?, dia_vencimento=?, ativo=? WHERE id=?",
            (str(nome).strip().upper(), float(valor_previsto or 0), int(dia or 1), int(bool(ativo)), int(id_)))


def add_lancamento_fatura(data, cartao_id, estabelecimento, categoria_id, valor, competencia,
                          parcela_num=1, parcelas=1, obs=None):
    """Linha de fatura importada: a competencia e' a da fatura (nao a data da
    compra) e a parcela vem como esta no extrato (2/5 = so esta parcela)."""
    return execute("""INSERT INTO lancamentos (data, modalidade, cartao_id, estabelecimento, categoria_id,
                      valor, parcela_num, parcelas, grupo_parcela, competencia, obs, criado_em)
                      VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                   (str(data), "CARTAO", cartao_id, str(estabelecimento).strip(), categoria_id, float(valor),
                    int(parcela_num or 1), int(parcelas or 1), None, competencia, obs, agora()))


def mapa_import_get() -> dict:
    df = query("SELECT m.chave, m.categoria_id FROM mapa_import m JOIN categorias c ON c.id=m.categoria_id")
    return {r["chave"]: int(r["categoria_id"]) for _, r in df.iterrows()}


def mapa_import_set(chave, categoria_id):
    execute("INSERT INTO mapa_import (chave, categoria_id) VALUES (?,?) "
            "ON CONFLICT(chave) DO UPDATE SET categoria_id=excluded.categoria_id", (chave, int(categoria_id)))


def existe_lancamento(data, estabelecimento, valor) -> bool:
    df = query("SELECT 1 FROM lancamentos WHERE data=? AND estabelecimento=? AND ABS(valor-?)<0.005 LIMIT 1",
               (str(data), str(estabelecimento).strip(), float(valor)))
    return not df.empty


def existe_fixo_lancado(competencia, tipo_id) -> bool:
    df = query("SELECT 1 FROM fixos_lancamentos WHERE competencia=? AND tipo_id=? LIMIT 1", (competencia, tipo_id))
    return not df.empty


def fixos_do_mes(competencia):
    """Todos os tipos ativos com o lançamento do mês (se houver)."""
    return query("""
        SELECT t.id AS tipo_id, t.nome, t.valor_previsto, t.dia_vencimento,
               l.id AS lanc_id, COALESCE(l.valor, t.valor_previsto) AS valor,
               COALESCE(l.pago, 0) AS pago, l.data_pagamento, l.obs
        FROM fixos_tipos t
        LEFT JOIN fixos_lancamentos l ON l.tipo_id = t.id AND l.competencia = ?
        WHERE t.ativo = 1 ORDER BY t.dia_vencimento, t.nome""", (competencia,))


def salvar_fixo(competencia, tipo_id, valor, pago, data_pagamento=None, obs=None):
    execute("""INSERT INTO fixos_lancamentos (competencia, tipo_id, valor, pago, data_pagamento, obs)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(competencia, tipo_id) DO UPDATE SET valor=excluded.valor,
               pago=excluded.pago, data_pagamento=excluded.data_pagamento, obs=excluded.obs""",
            (competencia, tipo_id, valor, int(pago), data_pagamento, obs))


def cartoes(ativos=True):
    return query("SELECT * FROM cartoes" + (" WHERE ativo=1" if ativos else "") + " ORDER BY nome")


def add_cartao(nome, bandeira, fechamento, vencimento, limite):
    execute("INSERT INTO cartoes (nome, bandeira, dia_fechamento, dia_vencimento, limite) VALUES (?,?,?,?,?) "
            "ON CONFLICT(nome) DO UPDATE SET bandeira=excluded.bandeira, dia_fechamento=excluded.dia_fechamento, "
            "dia_vencimento=excluded.dia_vencimento, limite=excluded.limite, ativo=1",
            (nome.strip(), bandeira, fechamento, vencimento, limite))


def set_cartao_ativo(id_, ativo):
    execute("UPDATE cartoes SET ativo=? WHERE id=?", (int(ativo), id_))


# ── Lançamentos (cartão / débito) ───────────────────────────────────────────
def add_lancamento(data: date, modalidade, cartao_id, estabelecimento, categoria_id, valor,
                   parcelas=1, obs=None):
    """Cartão parcelado gera uma linha por parcela, cada uma na sua fatura."""
    parcelas = max(1, int(parcelas or 1))
    grupo = str(uuid.uuid4()) if parcelas > 1 else None
    if modalidade == "CARTAO":
        fech = int(query("SELECT dia_fechamento FROM cartoes WHERE id=?", (cartao_id,)).iloc[0, 0])
        comp0 = competencia_cartao(data, fech)
    else:
        cartao_id = None
        comp0 = competencia_de(data)
    valor_parc = round(float(valor) / parcelas, 2)
    # ajuste de centavos na última parcela
    resto = round(float(valor) - valor_parc * parcelas, 2)
    with conn() as c:
        for n in range(1, parcelas + 1):
            v = valor_parc + (resto if n == parcelas else 0)
            c.execute("""INSERT INTO lancamentos (data, modalidade, cartao_id, estabelecimento, categoria_id,
                         valor, parcela_num, parcelas, grupo_parcela, competencia, obs, criado_em)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (str(data), modalidade, cartao_id, estabelecimento.strip(), categoria_id, v,
                       n, parcelas, grupo, somar_meses(comp0, n - 1), obs, agora()))


def lancamentos(competencia=None, modalidade=None, cartao_id=None, de=None, ate=None):
    sql = """SELECT l.id, l.data, l.modalidade, ca.nome AS cartao, l.estabelecimento,
                    c.grupo, c.nome AS categoria, l.valor, l.parcela_num, l.parcelas,
                    l.grupo_parcela, l.competencia, l.obs
             FROM lancamentos l JOIN categorias c ON c.id=l.categoria_id
             LEFT JOIN cartoes ca ON ca.id=l.cartao_id WHERE 1=1"""
    p = []
    if competencia:
        sql += " AND l.competencia=?"; p.append(competencia)
    if modalidade:
        sql += " AND l.modalidade=?"; p.append(modalidade)
    if cartao_id:
        sql += " AND l.cartao_id=?"; p.append(cartao_id)
    if de:
        sql += " AND l.competencia>=?"; p.append(de)
    if ate:
        sql += " AND l.competencia<=?"; p.append(ate)
    return query(sql + " ORDER BY l.data DESC, l.id DESC", p)


def del_lancamento(id_, todas_parcelas=False):
    if todas_parcelas:
        g = query("SELECT grupo_parcela FROM lancamentos WHERE id=?", (id_,))
        if not g.empty and g.iloc[0, 0]:
            execute("DELETE FROM lancamentos WHERE grupo_parcela=?", (g.iloc[0, 0],))
            return
    execute("DELETE FROM lancamentos WHERE id=?", (id_,))


# ── Resumo mensal ───────────────────────────────────────────────────────────
def resumo_mes(competencia) -> dict:
    cred = query("SELECT COALESCE(SUM(valor),0) v FROM creditos WHERE competencia=?", (competencia,)).iloc[0]["v"]
    fixos = fixos_do_mes(competencia)
    fixos_total = float(fixos["valor"].sum()) if not fixos.empty else 0.0
    fixos_pago = float(fixos.loc[fixos["pago"] == 1, "valor"].sum()) if not fixos.empty else 0.0
    l = query("SELECT modalidade, COALESCE(SUM(valor),0) v FROM lancamentos WHERE competencia=? GROUP BY modalidade",
              (competencia,))
    cartao = float(l.loc[l["modalidade"] == "CARTAO", "v"].sum()) if not l.empty else 0.0
    debito = float(l.loc[l["modalidade"] == "DEBITO", "v"].sum()) if not l.empty else 0.0
    inv = query("SELECT COALESCE(SUM(aporte),0) a, COALESCE(SUM(resgate),0) r FROM inv_movimentos WHERE competencia=?",
                (competencia,)).iloc[0]
    planos = query("SELECT COALESCE(SUM(valor),0) v FROM planos_aportes WHERE substr(data,1,7)=?",
                   (competencia,)).iloc[0]["v"]
    gastos = fixos_total + cartao + debito
    return {"creditos": float(cred), "fixos": fixos_total, "fixos_pago": fixos_pago, "cartao": cartao,
            "debito": debito, "gastos": gastos, "aportes": float(inv["a"]), "resgates": float(inv["r"]),
            "planos": float(planos), "saldo": float(cred) - gastos}


def serie_mensal(n_meses=12, ate=None) -> pd.DataFrame:
    ate = ate or competencia_de(date.today())
    comps = [somar_meses(ate, -i) for i in range(n_meses - 1, -1, -1)]
    linhas = []
    for c in comps:
        r = resumo_mes(c)
        r["competencia"] = c
        linhas.append(r)
    return pd.DataFrame(linhas)


def gastos_por_categoria(competencia) -> pd.DataFrame:
    return query("""SELECT c.grupo, c.nome AS categoria, l.modalidade, SUM(l.valor) AS valor, COUNT(*) AS qtd
                    FROM lancamentos l JOIN categorias c ON c.id=l.categoria_id
                    WHERE l.competencia=? GROUP BY c.grupo, c.nome, l.modalidade ORDER BY valor DESC""",
                 (competencia,))


def gastos_por_grupo_serie(de, ate) -> pd.DataFrame:
    return query("""SELECT l.competencia, c.grupo, SUM(l.valor) AS valor
                    FROM lancamentos l JOIN categorias c ON c.id=l.categoria_id
                    WHERE l.competencia BETWEEN ? AND ? GROUP BY l.competencia, c.grupo""", (de, ate))


def top_estabelecimentos(competencia, n=10) -> pd.DataFrame:
    return query("""SELECT estabelecimento, SUM(valor) AS valor, COUNT(*) AS qtd
                    FROM lancamentos WHERE competencia=? GROUP BY estabelecimento
                    ORDER BY valor DESC LIMIT ?""", (competencia, n))


# ── Planejamento ────────────────────────────────────────────────────────────
def add_plano(nome, tipo, valor_alvo, data_alvo, prioridade, obs):
    return execute("INSERT INTO planos (nome, tipo, valor_alvo, data_alvo, prioridade, obs, criado_em) "
                   "VALUES (?,?,?,?,?,?,?)", (nome.strip(), tipo, valor_alvo, str(data_alvo) if data_alvo else None,
                                              prioridade, obs, agora()))


def planos(status=None):
    sql = """SELECT p.*, COALESCE((SELECT SUM(valor) FROM planos_aportes a WHERE a.plano_id=p.id),0) AS guardado
             FROM planos p"""
    if status:
        return query(sql + " WHERE p.status=? ORDER BY p.prioridade, p.data_alvo", (status,))
    return query(sql + " ORDER BY p.status, p.prioridade, p.data_alvo")


def set_plano_status(id_, status):
    execute("UPDATE planos SET status=? WHERE id=?", (status, id_))


def del_plano(id_):
    execute("DELETE FROM planos WHERE id=?", (id_,))


def add_aporte_plano(plano_id, data, valor, obs=None):
    execute("INSERT INTO planos_aportes (plano_id, data, valor, obs) VALUES (?,?,?,?)",
            (plano_id, str(data), valor, obs))


def aportes_plano(plano_id):
    return query("SELECT * FROM planos_aportes WHERE plano_id=? ORDER BY data DESC", (plano_id,))


# ── Investimentos ───────────────────────────────────────────────────────────
def add_investimento(nome, tipo, instituicao, ativo_codigo=None):
    moeda = TIPOS_INVESTIMENTO.get(tipo, ("BRL", False))[0]
    return execute("INSERT INTO investimentos (nome, tipo, instituicao, moeda, ativo_codigo, criado_em) "
                   "VALUES (?,?,?,?,?,?)", (nome.strip(), tipo, instituicao, moeda,
                                            (ativo_codigo or "").strip().upper() or None, agora()))


def investimentos(ativos=True):
    return query("SELECT * FROM investimentos" + (" WHERE ativo=1" if ativos else "") + " ORDER BY tipo, nome")


def set_investimento_ativo(id_, ativo):
    execute("UPDATE investimentos SET ativo=? WHERE id=?", (int(ativo), id_))


def salvar_movimento(investimento_id, competencia, aporte, resgate, saldo_final, quantidade=None,
                     cotacao=None, obs=None):
    execute("""INSERT INTO inv_movimentos (investimento_id, competencia, aporte, resgate, quantidade, cotacao,
               saldo_final, obs) VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(investimento_id, competencia) DO UPDATE SET aporte=excluded.aporte,
               resgate=excluded.resgate, quantidade=excluded.quantidade, cotacao=excluded.cotacao,
               saldo_final=excluded.saldo_final, obs=excluded.obs""",
            (investimento_id, competencia, aporte or 0, resgate or 0, quantidade, cotacao, saldo_final, obs))


def del_movimento(id_):
    execute("DELETE FROM inv_movimentos WHERE id=?", (id_,))


def movimentos(investimento_id=None, de=None, ate=None) -> pd.DataFrame:
    sql = """SELECT m.*, i.nome, i.tipo, i.moeda, i.ativo_codigo FROM inv_movimentos m
             JOIN investimentos i ON i.id=m.investimento_id WHERE 1=1"""
    p = []
    if investimento_id:
        sql += " AND m.investimento_id=?"; p.append(investimento_id)
    if de:
        sql += " AND m.competencia>=?"; p.append(de)
    if ate:
        sql += " AND m.competencia<=?"; p.append(ate)
    return query(sql + " ORDER BY m.investimento_id, m.competencia", p)


def quantidade_acumulada(investimento_id, ate_competencia) -> float:
    df = query("SELECT COALESCE(SUM(quantidade),0) q FROM inv_movimentos WHERE investimento_id=? AND competencia<=?",
               (investimento_id, ate_competencia))
    return float(df.iloc[0]["q"])


def rentabilidade(df_mov: pd.DataFrame) -> pd.DataFrame:
    """Rendimento e rentabilidade mensal por investimento a partir dos saldos.

    rendimento = saldo_final - saldo_anterior - aporte + resgate
    rentab_%   = rendimento / (saldo_anterior + aporte)
    """
    if df_mov.empty:
        return df_mov
    df = df_mov.sort_values(["investimento_id", "competencia"]).copy()
    df["saldo_anterior"] = df.groupby("investimento_id")["saldo_final"].shift(1).fillna(0.0)
    df["rendimento"] = df["saldo_final"] - df["saldo_anterior"] - df["aporte"] + df["resgate"]
    base = df["saldo_anterior"] + df["aporte"]
    df["rentab_pct"] = (df["rendimento"] / base.where(base > 0)) * 100
    return df


# ── Metas ───────────────────────────────────────────────────────────────────
def add_meta(tipo, descricao, valor, anos=None, data_inicio=None):
    execute("UPDATE metas SET ativo=0 WHERE tipo=? AND ativo=1", (tipo,)) if tipo != "prazo" else None
    execute("INSERT INTO metas (tipo, descricao, valor, anos, data_inicio) VALUES (?,?,?,?,?)",
            (tipo, descricao, valor, anos, str(data_inicio or date.today())))


def metas(ativas=True):
    return query("SELECT * FROM metas" + (" WHERE ativo=1" if ativas else "") + " ORDER BY tipo, id")


def del_meta(id_):
    execute("DELETE FROM metas WHERE id=?", (id_,))


# ── Benchmark / cotações (cache) ────────────────────────────────────────────
def get_benchmark(competencia, indice):
    df = query("SELECT valor FROM benchmark WHERE competencia=? AND indice=?", (competencia, indice))
    return float(df.iloc[0]["valor"]) if not df.empty else None


def set_benchmark(competencia, indice, valor, origem):
    execute("INSERT INTO benchmark (competencia, indice, valor, origem) VALUES (?,?,?,?) "
            "ON CONFLICT(competencia, indice) DO UPDATE SET valor=excluded.valor, origem=excluded.origem",
            (competencia, indice, valor, origem))


def get_cotacao(codigo, data=None):
    if data:
        df = query("SELECT valor, data FROM cotacoes WHERE codigo=? AND data<=? ORDER BY data DESC LIMIT 1",
                   (codigo, str(data)))
    else:
        df = query("SELECT valor, data FROM cotacoes WHERE codigo=? ORDER BY data DESC LIMIT 1", (codigo,))
    return (float(df.iloc[0]["valor"]), df.iloc[0]["data"]) if not df.empty else (None, None)


def set_cotacao(codigo, valor, data=None, origem="manual"):
    execute("INSERT INTO cotacoes (data, codigo, valor, origem) VALUES (?,?,?,?) "
            "ON CONFLICT(data, codigo) DO UPDATE SET valor=excluded.valor, origem=excluded.origem",
            (str(data or date.today()), codigo.upper(), valor, origem))
