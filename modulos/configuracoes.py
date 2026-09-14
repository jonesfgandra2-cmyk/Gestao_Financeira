"""Configurações: gastos fixos, categorias, cartões, tipos de crédito, parâmetros, usuários."""
import streamlit as st

import db
from utils import brl


def render():
    st.title("⚙️ Configurações")
    abas = st.tabs(["🏠 Gastos fixos", "🏷 Categorias", "💳 Cartões", "💵 Tipos de crédito",
                    "📐 Parâmetros", "👤 Usuários"])
    with abas[0]:
        _fixos()
    with abas[1]:
        _categorias()
    with abas[2]:
        _cartoes()
    with abas[3]:
        _tipos_credito()
    with abas[4]:
        _parametros()
    with abas[5]:
        _usuarios()


def _fixos():
    st.caption("Os fixos aparecem todo mês na aba Gastos com o valor previsto; você ajusta e marca como pago.")
    with st.form("cfg_fixo", clear_on_submit=True):
        a, b, c, d = st.columns([2, 1, 1, 1])
        nome = a.text_input("Nome da conta")
        val = b.number_input("Valor previsto", min_value=0.0, step=10.0, format="%.2f")
        dia = c.number_input("Dia de vencimento", min_value=1, max_value=31, value=10)
        if d.form_submit_button("Salvar", width="stretch") and nome.strip():
            db.add_fixo_tipo(nome, val, int(dia)); st.rerun()
    df = db.fixos_tipos(ativos=False)
    for _, x in df.iterrows():
        a, b, c, d = st.columns([2, 1, 1, 1])
        a.markdown(("~~" if not x["ativo"] else "") + f"**{x['nome']}**" + ("~~" if not x["ativo"] else ""))
        b.markdown(brl(x["valor_previsto"]))
        c.markdown(f"dia {int(x['dia_vencimento'])}")
        if d.button("Desativar" if x["ativo"] else "Reativar", key=f"fx_at_{x['id']}"):
            db.set_fixo_tipo_ativo(int(x["id"]), not x["ativo"]); st.rerun()


def _categorias():
    st.caption("Modalidade = grupo (Alimentação/Lazer, Despesa Casa...). Categoria = o detalhe dentro dela.")
    cats = db.categorias(ativas=False)
    with st.form("cfg_cat", clear_on_submit=True):
        a, b, c = st.columns([1.4, 1.4, 0.8])
        grupos = sorted(cats["grupo"].unique().tolist()) if not cats.empty else []
        grupo = a.selectbox("Modalidade existente", grupos + ["+ nova modalidade"])
        novo_grupo = a.text_input("Nova modalidade (se escolheu '+ nova')")
        nome = b.text_input("Categoria")
        if c.form_submit_button("Adicionar", width="stretch") and nome.strip():
            g = novo_grupo.strip() if grupo == "+ nova modalidade" else grupo
            if g:
                db.add_categoria(g, nome); st.rerun()
    for g, sub in cats.groupby("grupo"):
        with st.expander(f"{g} ({int(sub['ativo'].sum())} ativas)", expanded=False):
            for _, x in sub.iterrows():
                a, b = st.columns([4, 1])
                a.markdown(("~~" if not x["ativo"] else "") + x["nome"] + ("~~" if not x["ativo"] else ""))
                if b.button("Desativar" if x["ativo"] else "Reativar", key=f"cat_at_{x['id']}"):
                    db.set_categoria_ativa(int(x["id"]), not x["ativo"]); st.rerun()


def _cartoes():
    st.caption("Compra depois do dia de fechamento cai na fatura do mês seguinte. Parcelas seguem nas faturas seguintes.")
    with st.form("cfg_cartao", clear_on_submit=True):
        a, b, c, d, e, f = st.columns([1.6, 1, 0.8, 0.8, 1, 0.8])
        nome = a.text_input("Nome", placeholder="Nubank, Itaú...")
        band = b.selectbox("Bandeira", ["Visa", "Mastercard", "Elo", "Amex", "Hipercard", "Outra"])
        fech = c.number_input("Fecha dia", 1, 31, 25)
        venc = d.number_input("Vence dia", 1, 31, 5)
        lim = e.number_input("Limite", min_value=0.0, step=500.0, format="%.2f")
        if f.form_submit_button("Salvar", width="stretch") and nome.strip():
            db.add_cartao(nome, band, int(fech), int(venc), lim); st.rerun()
    for _, x in db.cartoes(ativos=False).iterrows():
        a, b, c = st.columns([2.5, 2, 1])
        a.markdown(("~~" if not x["ativo"] else "") + f"**{x['nome']}** · {x['bandeira']}" + ("~~" if not x["ativo"] else ""))
        b.markdown(f"fecha {int(x['dia_fechamento'])} · vence {int(x['dia_vencimento'])} · limite {brl(x['limite'])}")
        if c.button("Desativar" if x["ativo"] else "Reativar", key=f"ca_at_{x['id']}"):
            db.set_cartao_ativo(int(x["id"]), not x["ativo"]); st.rerun()


def _tipos_credito():
    with st.form("cfg_tc", clear_on_submit=True):
        a, b = st.columns([3, 1])
        nome = a.text_input("Novo tipo de crédito")
        if b.form_submit_button("Adicionar", width="stretch") and nome.strip():
            db.execute("INSERT OR IGNORE INTO tipos_credito (nome) VALUES (?)", (nome.strip(),)); st.rerun()
    for _, x in db.tipos_credito(ativos=False).iterrows():
        a, b = st.columns([4, 1])
        a.markdown(("~~" if not x["ativo"] else "") + x["nome"] + ("~~" if not x["ativo"] else ""))
        if b.button("Desativar" if x["ativo"] else "Reativar", key=f"tc_at_{x['id']}"):
            db.execute("UPDATE tipos_credito SET ativo=? WHERE id=?", (int(not x["ativo"]), int(x["id"]))); st.rerun()


def _parametros():
    st.caption("Valores de referência. Selic, CDI, dólar, euro e cripto são buscados na internet "
               "(Banco Central / CoinGecko); os campos manuais valem quando não houver conexão.")
    campos = [
        ("cdi_anual_manual", "CDI anual manual (% a.a.)"),
        ("poupanca_mensal_manual", "Poupança mensal manual (% a.m.)"),
        ("usd_manual", "Dólar manual (R$)"), ("eur_manual", "Euro manual (R$)"),
        ("limite_baixo_rendimento", "Baixo rendimento: abaixo de X% do CDI"),
        ("limite_oportunidade", "Destaque: acima de X% do CDI"),
        ("meta_taxa_poupanca", "Meta de sobra da renda (%)"),
        ("alerta_cartao_pct_renda", "Alerta: cartão acima de X% da renda"),
    ]
    with st.form("cfg_param"):
        vals = {}
        cols = st.columns(2)
        for i, (k, rot) in enumerate(campos):
            vals[k] = cols[i % 2].number_input(rot, value=db.get_config_float(k, 0), step=0.05, format="%.2f")
        if st.form_submit_button("Salvar parâmetros", type="primary"):
            for k, v in vals.items():
                db.set_config(k, v)
            st.success("Parâmetros salvos.")


def _usuarios():
    u = st.session_state.get("usuario", {})
    st.subheader("Trocar minha senha")
    with st.form("troca_senha", clear_on_submit=True):
        s1 = st.text_input("Nova senha", type="password")
        s2 = st.text_input("Confirmar", type="password")
        if st.form_submit_button("Trocar"):
            if s1 and s1 == s2:
                db.trocar_senha(u["id"], s1); st.success("Senha alterada.")
            else:
                st.error("As senhas não conferem.")
    if u.get("admin"):
        st.subheader("Novo usuário")
        with st.form("novo_usuario", clear_on_submit=True):
            a, b, c, d = st.columns([1.2, 1.2, 1.2, 0.8])
            nome = a.text_input("Nome")
            login = b.text_input("Usuário")
            senha = c.text_input("Senha", type="password")
            if d.form_submit_button("Criar", width="stretch"):
                if nome and login and senha:
                    try:
                        db.criar_usuario(login, nome, senha); st.success("Usuário criado.")
                    except Exception as e:
                        st.error(f"Não foi possível criar: {e}")
        st.dataframe(db.query("SELECT usuario, nome, admin, criado_em FROM usuarios ORDER BY id"),
                     hide_index=True, width="stretch")
