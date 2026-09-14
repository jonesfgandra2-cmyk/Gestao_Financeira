"""Importação de planilhas de gastos e de faturas de cartão (Nubank, Itaú, XP).

Dois modos, mesmo fluxo:
  1. ler o arquivo e reconhecer as colunas (presets dos bancos ou mapeamento manual);
  2. amarrar cada "tipo" (categoria do banco ou estabelecimento) a uma
     categoria cadastrada — ou assumir o nome que veio, ou criar outra;
  3. conferir e importar. As amarrações ficam gravadas e vêm preenchidas
     na próxima fatura.
"""
import io
import re
import unicodedata
from datetime import date

import pandas as pd
import streamlit as st

import db
from utils import brl, rotulo_comp, rotulo_comp_longo, seletor_competencia

_PISTAS = {
    "data": ["data", "dt", "date", "dia", "vencimento", "compra"],
    "descricao": ["estabelecimento", "descricao", "descr", "historico", "lancamento", "title", "titulo", "local",
                  "loja", "item", "nome"],
    "valor": ["valor", "value", "amount", "total", "preco", "vlr", "quantia", "montante"],
    "tipo": ["tipo", "categoria", "category", "classificacao", "grupo", "modalidade", "class"],
    "parcelas": ["parcelas", "parcela", "qtd_parc", "vezes"],
    "meio": ["meio", "pagamento", "forma", "cartao", "conta", "portador"],
}
NOVA_MESMO_NOME = "➕ Criar categoria com este nome"
NOVA_OUTRO_NOME = "✏️ Criar categoria com outro nome"
IGNORAR = "⛔ Ignorar linhas deste tipo"

# Presets de fatura: como cada banco exporta. Se o cabeçalho não bater,
# o usuário cai no mapeamento manual (mesmo da planilha).
PRESETS = {
    "Nubank (CSV do app)": {"data": ["date"], "descricao": ["title"], "valor": ["amount"],
                            "tipo": ["category"], "sinal": "compra_positiva",
                            "ignorar_desc": ["pagamento recebido", "pagamento em", "estorno"]},
    "Itaú (CSV/Excel do Internet Banking)": {"data": ["data"], "descricao": ["lancamento", "lançamento", "descricao"],
                                             "valor": ["valor"], "tipo": [], "sinal": "compra_positiva",
                                             "ignorar_desc": ["pagamento efetuado", "pagamento de fatura", "saldo"]},
    "XP (CSV da fatura)": {"data": ["data"], "descricao": ["estabelecimento"], "valor": ["valor"],
                           "tipo": [], "parcela_txt": ["parcela"], "sinal": "compra_positiva",
                           "ignorar_desc": ["pagamento", "estorno"]},
    "Outro (mapear colunas)": None,
}


def _norm(txt) -> str:
    t = unicodedata.normalize("NFKD", str(txt or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", t.lower()).strip("_")


def _adivinhar(colunas, chave):
    for c in colunas:
        n = _norm(c)
        if any(p == n or p in n for p in _PISTAS[chave]):
            return c
    return None


def _acha_coluna(colunas, candidatos):
    for c in colunas:
        if _norm(c) in [_norm(x) for x in candidatos]:
            return c
    for c in colunas:
        if any(_norm(x) in _norm(c) for x in candidatos):
            return c
    return None


def _para_float(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v).strip().replace("R$", "").replace(" ", "").replace(" ", "")
    if not t:
        return None
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()+")
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        f = float(t)
    except ValueError:
        return None
    return -f if neg else f


def _parcela(txt):
    """'2/5', '2 de 5', 'Parcela 2/5' -> (2, 5); senão (1, 1)."""
    m = re.search(r"(\d{1,2})\s*(?:/|de)\s*(\d{1,2})", str(txt or ""))
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 1 <= a <= b <= 48:
            return a, b
    return 1, 1


def _ler(arquivo) -> pd.DataFrame:
    dados = arquivo.getvalue()
    if arquivo.name.lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(dados))
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(dados), sep=None, engine="python", encoding=enc)
        except Exception:
            continue
    raise ValueError("Não consegui ler o arquivo. Use .xlsx ou .csv.")


def _detectar_preset(colunas):
    for nome, p in PRESETS.items():
        if not p:
            continue
        if all(_acha_coluna(colunas, p[k]) for k in ("data", "descricao", "valor")) and \
                (not p.get("tipo") or _acha_coluna(colunas, p["tipo"])):
            return nome
    return "Outro (mapear colunas)"


# ═══════════════════════════════════════════════════════════════════════════
def render():
    modo = st.radio("O que você vai importar?",
                    ["📄 Planilha de gastos", "💳 Fatura de cartão (Nubank / Itaú / XP)",
                     "🏦 Extrato da conta (Nubank / Itaú / XP)"],
                    horizontal=True, key="imp_tipo_arq")
    if modo.startswith("📄"):
        _planilha()
    elif modo.startswith("💳"):
        _fatura()
    else:
        _extrato()


# ── Extrato bancário ────────────────────────────────────────────────────────
PALAVRAS_FATURA = ["pagamento de fatura", "pagamento fatura", "pgto fatura", "fatura cartao", "fatura cartão",
                   "pagamento cartao", "pagamento cartão"]
PALAVRAS_INVEST = ["aplicacao", "aplicação", "resgate", "rendimento", "rdb", "cdb", "tesouro", "poupanca", "poupança",
                   "investimento"]


def _extrato():
    st.caption("Exporte o extrato da conta (CSV ou Excel). **Saídas** viram gastos no débito, amarrados a uma "
               "categoria por descrição; **entradas** podem virar créditos (salário, reembolso...) ou ser ignoradas.")
    arq = st.file_uploader("Arquivo do extrato", type=["xlsx", "xls", "csv"], key="ext_arq")
    if not arq:
        st.markdown("""
**Onde exportar**
- **Nubank:** app → Conta → *Extrato* → ⋯ → *Exportar* (CSV com `Data, Valor, Identificador, Descrição`; saídas negativas).
- **Itaú:** Internet Banking → Conta corrente → Extrato → *Salvar como* CSV/Excel (data, lançamento, valor).
- **XP:** app → Conta → Extrato → *Exportar*.

Pagamento da fatura do cartão e aplicações/resgates são ignorados por padrão (o cartão entra pela fatura; os
investimentos, na aba Investimentos).""")
        return
    bruto = _carregar(arq)
    if bruto is None:
        return
    cols = list(bruto.columns)
    opc = ["— não tem —"] + cols

    def _sel(rot, chave, obrig=True):
        sug = _adivinhar(cols, chave)
        v = st.selectbox(rot + (" *" if obrig else ""), opc, index=opc.index(sug) if sug in opc else 0,
                         key=f"ext_col_{chave}")
        return None if v == "— não tem —" else v

    c1, c2, c3 = st.columns(3)
    with c1:
        col_data = _sel("Data", "data")
    with c2:
        col_desc = _sel("Descrição / lançamento", "descricao")
    with c3:
        col_valor = _sel("Valor (negativo = saída)", "valor")
    if not (col_data and col_desc and col_valor):
        st.info("Escolha data, descrição e valor.")
        return

    o1, o2 = st.columns(2)
    ign_fatura = o1.checkbox("Ignorar pagamento de fatura do cartão", value=True, key="ext_ign_fat",
                             help="Evita contar duas vezes: o cartão entra pela importação da fatura.")
    ign_invest = o2.checkbox("Ignorar aplicações e resgates de investimento", value=True, key="ext_ign_inv")

    base = pd.DataFrame({
        "data": pd.to_datetime(bruto[col_data], errors="coerce", dayfirst=True),
        "descricao": bruto[col_desc].astype(str).str.strip(),
        "valor_orig": bruto[col_valor].map(_para_float),
    }).dropna(subset=["data", "valor_orig"])
    base = base[(base["descricao"] != "") & (base["descricao"].str.lower() != "nan")]
    desc_l = base["descricao"].str.lower()
    mask = pd.Series(False, index=base.index)
    if ign_fatura:
        for pal in PALAVRAS_FATURA:
            mask |= desc_l.str.contains(pal, regex=False)
    if ign_invest:
        for pal in PALAVRAS_INVEST:
            mask |= desc_l.str.contains(pal, regex=False)
    if int(mask.sum()):
        st.caption(f"{int(mask.sum())} linha(s) de fatura/investimento ignoradas.")
    base = base[~mask]
    saidas = base[base["valor_orig"] < 0].copy()
    entradas = base[base["valor_orig"] > 0].copy()

    st.markdown(f"**Saídas:** {len(saidas)} lançamento(s) · {brl(-saidas['valor_orig'].sum())}  ·  "
                f"**Entradas:** {len(entradas)} lançamento(s) · {brl(entradas['valor_orig'].sum())}")

    # ── Saídas → gastos no débito ───────────────────────────────────────
    if not saidas.empty:
        st.markdown("### Saídas → gastos (débito)")
        df = pd.DataFrame({"data": saidas["data"], "descricao": saidas["descricao"], "valor": saidas["valor_orig"],
                           "tipo": "", "parcela_num": 1, "parcelas": 1, "meio": "débito"})
        df = _limpar(df)
        if df is not None:
            mapa, pend = _amarrar(df, chave="descricao")
            _confirmar(df, mapa, pend, modo_fatura=None, cartao_id=None, modo_padrao="Débito / Pix", chave="descricao")

    # ── Entradas → créditos ─────────────────────────────────────────────
    if not entradas.empty:
        st.markdown("### Entradas → créditos do mês")
        tipos = db.tipos_credito()
        opcoes = ["⛔ Ignorar"] + tipos["nome"].tolist()
        h1, h2 = st.columns([2.2, 1.4])
        h1.markdown("**No extrato**"); h2.markdown("**Vai para**")
        escolhas = {}
        for _, r in entradas.iterrows():
            a, b = st.columns([2.2, 1.4])
            a.markdown(f"{r['data']:%d/%m/%Y} · **{r['descricao']}** · {brl(r['valor_orig'])}")
            dl = str(r["descricao"]).lower()
            sug = 0
            for i, t in enumerate(opcoes):
                if i and (_norm(t) in _norm(dl) or ("salario" in _norm(t) and any(k in dl for k in ("salario", "salário", "pagamento", "folha", "remuner")))):
                    sug = i
                    break
            escolhas[r.name] = b.selectbox("tipo", opcoes, index=sug, key=f"ext_cred_{r.name}", label_visibility="collapsed")
        n_imp = sum(1 for v in escolhas.values() if v != "⛔ Ignorar")
        if st.button(f"💵 Importar {n_imp} crédito(s)", type="primary", disabled=not n_imp, key="ext_go_cred"):
            feitos = 0
            for idx, esc in escolhas.items():
                if esc == "⛔ Ignorar":
                    continue
                r = entradas.loc[idx]
                tid = int(tipos.loc[tipos["nome"] == esc, "id"].iloc[0])
                d = r["data"].date()
                ja = db.query("SELECT 1 FROM creditos WHERE data=? AND ABS(valor-?)<0.005 AND tipo_id=? LIMIT 1",
                              (str(d), float(r["valor_orig"]), tid))
                if not ja.empty:
                    continue
                db.add_credito(db.competencia_de(d), d, tid, r["descricao"], float(r["valor_orig"]))
                feitos += 1
            st.success(f"{feitos} crédito(s) importado(s)" + (" (repetidos foram pulados)." if feitos < n_imp else "."))


# ── Planilha de gastos ──────────────────────────────────────────────────────
def _planilha():
    st.caption("Aceita **.xlsx** ou **.csv** com uma linha por gasto: data, descrição/estabelecimento, valor e "
               "tipo (categoria). Parcelas e meio de pagamento são opcionais.")
    arq = st.file_uploader("Planilha", type=["xlsx", "xls", "csv"], key="imp_arq")
    if not arq:
        _exemplo()
        return
    bruto = _carregar(arq)
    if bruto is None:
        return
    cols = list(bruto.columns)
    st.markdown("#### 1 · Colunas da planilha")
    opc = ["— não tem —"] + cols

    def _sel(rot, chave, obrig=True):
        sug = _adivinhar(cols, chave)
        v = st.selectbox(rot + (" *" if obrig else ""), opc, index=opc.index(sug) if sug in opc else 0,
                         key=f"imp_col_{chave}")
        return None if v == "— não tem —" else v

    c1, c2, c3 = st.columns(3)
    with c1:
        col_data = _sel("Data", "data"); col_parc = _sel("Parcelas", "parcelas", False)
    with c2:
        col_desc = _sel("Descrição / estabelecimento", "descricao"); col_meio = _sel("Meio (cartão/débito)", "meio", False)
    with c3:
        col_valor = _sel("Valor", "valor"); col_tipo = _sel("Tipo / categoria", "tipo", False)
    if not (col_data and col_desc and col_valor):
        st.info("Escolha ao menos as colunas de data, descrição e valor.")
        return

    st.markdown("#### 2 · Como esses gastos foram pagos")
    cartoes = db.cartoes()
    m1, m2 = st.columns(2)
    with m1:
        modo = st.radio("Modalidade padrão", ["Débito / Pix", "Cartão de crédito"], horizontal=True, key="imp_modo",
                        help="Se houver a coluna 'Meio', ela manda: valores com 'cart'/'credit' vão para o cartão.")
    cartao_id = None
    with m2:
        if not cartoes.empty and (modo == "Cartão de crédito" or col_meio):
            nome_c = st.selectbox("Cartão", cartoes["nome"].tolist(), key="imp_cartao")
            cartao_id = int(cartoes.loc[cartoes["nome"] == nome_c, "id"].iloc[0])
        elif modo == "Cartão de crédito":
            st.warning("Cadastre um cartão em Configurações → Cartões para importar como cartão.")
            return

    df = pd.DataFrame({
        "data": pd.to_datetime(bruto[col_data], errors="coerce", dayfirst=True),
        "descricao": bruto[col_desc].astype(str).str.strip(),
        "valor": bruto[col_valor].map(_para_float),
        "tipo": bruto[col_tipo].astype(str).str.strip() if col_tipo else "",
        "parcela_num": 1,
        "parcelas": pd.to_numeric(bruto[col_parc], errors="coerce").fillna(1).astype(int) if col_parc else 1,
        "meio": bruto[col_meio].astype(str).str.lower() if col_meio else "",
    })
    df = _limpar(df)
    if df is None:
        return
    mapa, pend = _amarrar(df, chave="tipo")
    _confirmar(df, mapa, pend, modo_fatura=None, cartao_id=cartao_id, modo_padrao=modo)


# ── Fatura de cartão ────────────────────────────────────────────────────────
def _fatura():
    st.caption("Exporte a fatura no app/site do banco (CSV ou Excel) e envie aqui. Todas as linhas entram como "
               "compras no cartão escolhido, na fatura do mês escolhido. Pagamentos e estornos são ignorados.")
    cartoes = db.cartoes()
    if cartoes.empty:
        st.warning("Cadastre um cartão em Configurações → Cartões antes de importar faturas.")
        return
    a, b, c = st.columns(3)
    with a:
        nome_c = st.selectbox("Cartão", cartoes["nome"].tolist(), key="fat_cartao")
        cartao_id = int(cartoes.loc[cartoes["nome"] == nome_c, "id"].iloc[0])
    with b:
        comp = seletor_competencia("fat_comp", "Fatura de (mês)")
    with c:
        preset_esc = st.selectbox("Banco / formato", list(PRESETS), key="fat_preset",
                                  help="Deixe em 'Outro' para mapear as colunas na mão. O sistema tenta reconhecer sozinho.")
    arq = st.file_uploader("Arquivo da fatura", type=["xlsx", "xls", "csv"], key="fat_arq")
    if not arq:
        st.markdown("""
**Onde exportar**
- **Nubank:** app → Cartão → fatura → ⋯ → *Exportar* (CSV com `date, category, title, amount`).
- **Itaú:** Internet Banking → Cartões → Fatura → *Exportar* (CSV/Excel com data, lançamento e valor).
- **XP:** app/site → Cartão → Fatura → *Exportar* (CSV com data, estabelecimento, portador, valor e parcela).

Se o arquivo vier com outros nomes de coluna, escolha **Outro** e aponte as colunas.""")
        return
    bruto = _carregar(arq)
    if bruto is None:
        return
    cols = list(bruto.columns)
    detect = _detectar_preset(cols)
    if preset_esc == "Outro (mapear colunas)" and detect != preset_esc:
        st.info(f"Cabeçalho reconhecido como **{detect}**.")
        preset_esc = detect
    p = PRESETS.get(preset_esc)

    if p and _acha_coluna(cols, p["data"]) and _acha_coluna(cols, p["descricao"]) and _acha_coluna(cols, p["valor"]):
        col_data = _acha_coluna(cols, p["data"]); col_desc = _acha_coluna(cols, p["descricao"])
        col_valor = _acha_coluna(cols, p["valor"])
        col_tipo = _acha_coluna(cols, p["tipo"]) if p.get("tipo") else None
        col_parc = _acha_coluna(cols, p.get("parcela_txt", [])) if p.get("parcela_txt") else None
        ignorar_desc = p.get("ignorar_desc", [])
    else:
        st.markdown("#### Colunas do arquivo")
        opc = ["— não tem —"] + cols

        def _sel(rot, chave, obrig=True):
            sug = _adivinhar(cols, chave)
            v = st.selectbox(rot + (" *" if obrig else ""), opc, index=opc.index(sug) if sug in opc else 0,
                             key=f"fat_col_{chave}")
            return None if v == "— não tem —" else v
        c1, c2 = st.columns(2)
        with c1:
            col_data = _sel("Data", "data"); col_valor = _sel("Valor", "valor")
        with c2:
            col_desc = _sel("Estabelecimento", "descricao"); col_tipo = _sel("Categoria do banco", "tipo", False)
        col_parc = _sel("Parcela (ex.: 2/5)", "parcelas", False)
        ignorar_desc = ["pagamento", "estorno"]
        if not (col_data and col_desc and col_valor):
            st.info("Escolha data, estabelecimento e valor.")
            return

    desc = bruto[col_desc].astype(str).str.strip()
    parc_src = bruto[col_parc] if col_parc else desc  # XP tem coluna; Itaú/Nubank escrevem '2/5' na descrição
    pn = parc_src.map(lambda t: _parcela(t)[0])
    pt = parc_src.map(lambda t: _parcela(t)[1])
    df = pd.DataFrame({
        "data": pd.to_datetime(bruto[col_data], errors="coerce", dayfirst=True),
        "descricao": desc,
        "valor": bruto[col_valor].map(_para_float),
        "tipo": bruto[col_tipo].astype(str).str.strip() if col_tipo else "",
        "parcela_num": pn, "parcelas": pt, "meio": "cartão",
    })
    # pagamentos/estornos: valor negativo ou descrição conhecida
    mask_ign = df["valor"].fillna(0) <= 0
    for pal in ignorar_desc:
        mask_ign |= df["descricao"].str.lower().str.contains(pal, regex=False)
    n_ign = int(mask_ign.sum())
    df = df[~mask_ign]
    if n_ign:
        st.caption(f"{n_ign} linha(s) de pagamento/estorno/crédito ignoradas.")
    df = _limpar(df)
    if df is None:
        return
    st.markdown(f"**{len(df)} compra(s)** somando **{brl(df['valor'].sum())}** na fatura de "
                f"**{rotulo_comp_longo(comp)}** · cartão **{nome_c}**")
    # sem categoria do banco: amarra por estabelecimento
    chave = "tipo" if col_tipo else "descricao"
    mapa, pend = _amarrar(df, chave=chave)
    _confirmar(df, mapa, pend, modo_fatura=comp, cartao_id=cartao_id, modo_padrao="Cartão de crédito", chave=chave)


# ── Passos comuns ───────────────────────────────────────────────────────────
def _carregar(arq):
    try:
        bruto = _ler(arq)
    except Exception as e:
        st.error(str(e))
        return None
    if bruto.empty:
        st.warning("O arquivo está vazio.")
        return None
    bruto.columns = [str(c).strip() for c in bruto.columns]
    with st.expander(f"Prévia do arquivo ({len(bruto)} linhas)", expanded=False):
        st.dataframe(bruto.head(10), hide_index=True, width="stretch")
    return bruto


def _limpar(df):
    invalidas = df[df["data"].isna() | df["valor"].isna() | (df["descricao"] == "") | (df["descricao"].str.lower() == "nan")]
    df = df.drop(invalidas.index).copy()
    df["valor"] = df["valor"].abs()
    df = df[df["valor"] > 0]
    df["tipo"] = df["tipo"].replace({"nan": "", "None": ""})
    if not invalidas.empty:
        st.warning(f"{len(invalidas)} linha(s) sem data, valor ou descrição serão ignoradas.")
    if df.empty:
        st.error("Nenhuma linha válida.")
        return None
    return df


def _amarrar(df, chave="tipo"):
    """Tabela de amarração: cada valor distinto de `chave` -> destino."""
    st.markdown("#### Amarrar aos tipos cadastrados")
    cats = db.categorias()
    fixos = db.fixos_tipos()
    rot_cat = {f"{r['grupo']} › {r['nome']}": ("cat", int(r["id"])) for _, r in cats.iterrows()}
    rot_fix = {f"🏠 Fixo: {r['nome']}": ("fixo", int(r["id"])) for _, r in fixos.iterrows()}
    id_para_rot = {v[1]: k for k, v in rot_cat.items()}
    opcoes = [NOVA_MESMO_NOME, NOVA_OUTRO_NOME, IGNORAR] + list(rot_cat) + list(rot_fix)
    grupos = sorted(cats["grupo"].unique().tolist()) if not cats.empty else ["Outros"]
    lembrados = db.mapa_import_get()

    valores = sorted(v for v in df[chave].unique() if v)
    if int((df[chave] == "").sum()):
        valores.append("")
    if chave == "descricao":
        st.caption("Esta fatura não traz categoria: a amarração é por **estabelecimento**. O sistema lembra "
                   "a escolha para as próximas faturas.")
    else:
        st.caption("Escolha, para cada tipo da planilha, a categoria cadastrada — ou crie uma nova na hora.")

    mapa = {}
    h1, h2, h3 = st.columns([1.6, 2, 1.6])
    h1.markdown("**Na planilha**"); h2.markdown("**Vai para**"); h3.markdown("**Categoria nova**")
    for t in valores:
        n = int((df[chave] == t).sum())
        tot = float(df.loc[df[chave] == t, "valor"].sum())
        a, b, c = st.columns([1.6, 2, 1.6])
        a.markdown(f"**{t or '(sem tipo)'}**  \n<span style='font-size:12px;color:#6b6a66'>{n} linha(s) · {brl(tot)}</span>",
                   unsafe_allow_html=True)
        k = _norm(t) or "vazio"
        # sugestão: lembrado > nome parecido > nova
        sug = 0
        lembrado = lembrados.get(_norm(t)) if t else None
        if lembrado and lembrado in id_para_rot:
            sug = opcoes.index(id_para_rot[lembrado])
        else:
            for i, rot in enumerate(opcoes):
                if t and rot not in (NOVA_MESMO_NOME, NOVA_OUTRO_NOME, IGNORAR) and (
                        _norm(rot.split("›")[-1]) == _norm(t) or _norm(t) in _norm(rot)):
                    sug = i
                    break
            if not t:
                sug = opcoes.index(NOVA_OUTRO_NOME)
        escolha = b.selectbox("destino", opcoes, index=sug, key=f"imp_map_{chave}_{k}", label_visibility="collapsed")
        novo_nome, grupo = None, None
        if escolha in (NOVA_MESMO_NOME, NOVA_OUTRO_NOME):
            with c:
                g1, g2 = st.columns(2)
                grupo = g1.selectbox("modalidade", grupos + ["+ nova"], key=f"imp_grp_{chave}_{k}",
                                     label_visibility="collapsed")
                if grupo == "+ nova":
                    grupo = g2.text_input("nova modalidade", key=f"imp_grpn_{chave}_{k}",
                                          placeholder="modalidade", label_visibility="collapsed")
                elif escolha == NOVA_OUTRO_NOME:
                    novo_nome = g2.text_input("nome", key=f"imp_nome_{chave}_{k}",
                                              placeholder="nome da categoria", label_visibility="collapsed")
            if escolha == NOVA_MESMO_NOME:
                novo_nome = t
        mapa[t] = (escolha, novo_nome, grupo)
    pend = [t for t, (e, nome, g) in mapa.items() if e in (NOVA_MESMO_NOME, NOVA_OUTRO_NOME) and (not nome or not g)]
    return mapa, pend


def _confirmar(df, mapa, pend, modo_fatura, cartao_id, modo_padrao, chave="tipo"):
    st.markdown("#### Conferir e importar")
    pular_dup = st.checkbox("Pular lançamentos que já existem (mesma data, descrição e valor)", value=True,
                            key=f"imp_dup_{chave}")
    if pend:
        st.warning("Informe nome e modalidade das categorias novas: "
                   + ", ".join(f"'{p or '(sem tipo)'}'" for p in pend))
    ign = df[chave].map(lambda t: mapa.get(t, ("",))[0] == IGNORAR)
    total = float(df.loc[~ign, "valor"].sum())
    st.markdown(f"**{int((~ign).sum())} lançamento(s)** somando **{brl(total)}**"
                + (f" · {int(ign.sum())} ignorado(s)" if int(ign.sum()) else ""))
    with st.expander("Ver linhas", expanded=False):
        st.dataframe(df.assign(data=df["data"].dt.date, destino=df[chave].map(lambda t: mapa.get(t, ("",))[0]))
                     [["data", "descricao", "valor", "tipo", "parcela_num", "parcelas", "destino"]],
                     hide_index=True, width="stretch", height=300)
    if st.button("📥 Importar", type="primary", disabled=bool(pend), key=f"imp_go_{chave}"):
        with st.spinner("Importando..."):
            res = _importar(df, mapa, chave, modo_fatura, cartao_id, modo_padrao, pular_dup)
        st.success(f"Importados {res['ok']} lançamento(s)"
                   + (f", {res['fixos']} conta(s) fixa(s)" if res["fixos"] else "")
                   + (f", {res['dup']} duplicado(s) pulado(s)" if res["dup"] else "")
                   + (f", {res['novas']} categoria(s) criada(s)" if res["novas"] else "") + ".")
        if res["meses"]:
            st.caption("Meses afetados: " + ", ".join(rotulo_comp(m) for m in sorted(res["meses"])))


def _importar(df, mapa, chave, modo_fatura, cartao_id, modo_padrao, pular_dup):
    """modo_fatura = competência da fatura (importação de fatura) ou None (planilha)."""
    cats = db.categorias()
    fixos = db.fixos_tipos()
    rot_cat = {f"{r['grupo']} › {r['nome']}": ("cat", int(r["id"])) for _, r in cats.iterrows()}
    rot_fix = {f"🏠 Fixo: {r['nome']}": ("fixo", int(r["id"])) for _, r in fixos.iterrows()}
    res = {"ok": 0, "fixos": 0, "dup": 0, "novas": 0, "meses": set()}
    destino = {}
    for t, (escolha, nome, grupo) in mapa.items():
        if escolha == IGNORAR:
            destino[t] = None
        elif escolha in (NOVA_MESMO_NOME, NOVA_OUTRO_NOME):
            db.add_categoria(grupo, nome)
            cid = int(db.query("SELECT id FROM categorias WHERE grupo=? AND nome=?",
                               (grupo.strip(), nome.strip())).iloc[0]["id"])
            db.set_categoria_ativa(cid, True)
            destino[t] = ("cat", cid)
            res["novas"] += 1
        else:
            destino[t] = rot_cat.get(escolha) or rot_fix.get(escolha)
        if t and destino[t] and destino[t][0] == "cat":
            db.mapa_import_set(_norm(t), destino[t][1])   # lembra para a próxima

    cartoes = db.cartoes()
    fech = int(cartoes.loc[cartoes["id"] == cartao_id, "dia_fechamento"].iloc[0]) if cartao_id else None
    for _, r in df.iterrows():
        d = destino.get(r[chave])
        if d is None:
            continue
        data = r["data"].date()
        kind, id_ = d
        if kind == "fixo":
            comp = modo_fatura or db.competencia_de(data)
            if pular_dup and db.existe_fixo_lancado(comp, id_):
                res["dup"] += 1
                continue
            db.salvar_fixo(comp, id_, float(r["valor"]), True, str(data))
            res["fixos"] += 1
            res["meses"].add(comp)
            continue
        if pular_dup and db.existe_lancamento(data, r["descricao"], r["valor"]):
            res["dup"] += 1
            continue
        if modo_fatura:
            db.add_lancamento_fatura(data, cartao_id, r["descricao"], id_, float(r["valor"]), modo_fatura,
                                     int(r["parcela_num"]), int(r["parcelas"]), "fatura importada")
            res["meses"].add(modo_fatura)
        else:
            meio = str(r["meio"] or "")
            e_cartao = any(k in meio for k in ("cart", "credit")) if meio else (modo_padrao == "Cartão de crédito")
            if e_cartao and cartao_id:
                db.add_lancamento(data, "CARTAO", cartao_id, r["descricao"], id_, float(r["valor"]),
                                  int(r["parcelas"]), "importado")
                res["meses"].add(db.competencia_cartao(data, fech))
            else:
                db.add_lancamento(data, "DEBITO", None, r["descricao"], id_, float(r["valor"]), 1, "importado")
                res["meses"].add(db.competencia_de(data))
        res["ok"] += 1
    return res


def _exemplo():
    st.markdown("**Modelo de planilha** (baixe, preencha e envie):")
    ex = pd.DataFrame({
        "Data": ["05/09/2026", "07/09/2026", "10/09/2026", "12/09/2026"],
        "Descrição": ["Ifood", "Coopercica", "Posto Shell", "ALUGUEL"],
        "Valor": [89.90, 650.00, 300.00, 1800.00],
        "Tipo": ["Ifood / Delivery", "Supermercado (Coopercica)", "Combustível", "ALUGUEL"],
        "Parcelas": [1, 1, 1, 1],
        "Meio": ["cartão", "débito", "débito", "débito"],
    })
    st.dataframe(ex, hide_index=True, width="stretch")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        ex.to_excel(w, index=False, sheet_name="Gastos")
    st.download_button("⬇️ Baixar modelo (.xlsx)", buf.getvalue(), "modelo_gastos.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="imp_modelo")
