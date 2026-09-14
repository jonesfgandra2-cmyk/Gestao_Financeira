"""Controle Financeiro Pessoal — Streamlit + SQLite.

Execute:  streamlit run app.py
"""
import streamlit as st

import db
from modulos import (configuracoes, creditos, dashboard, gastos, investimentos,
                     planejamento)

st.set_page_config(page_title="Controle Financeiro", page_icon="💰", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1280px;}
  h1, h2, h3 {letter-spacing: -.01em;}
  [data-testid="stSidebar"] .stRadio label {font-size: 15px;}
  div[data-testid="stMetric"] {border:1px solid #e3e2de; border-radius:8px; padding:10px 14px; background:#fff;}
</style>""", unsafe_allow_html=True)

db.iniciar_banco()

PAGINAS = {
    "📊 Saúde Financeira": dashboard.render,
    "💵 Créditos do mês": creditos.render,
    "🧾 Gastos": gastos.render,
    "🎯 Planejamento futuro": planejamento.render,
    "📈 Investimentos": investimentos.render,
    "⚙️ Configurações": configuracoes.render,
}


def tela_primeiro_acesso():
    st.title("💰 Controle Financeiro")
    st.subheader("Primeiro acesso — crie o usuário administrador")
    with st.form("primeiro_usuario"):
        nome = st.text_input("Seu nome")
        usuario = st.text_input("Usuário (login)")
        s1 = st.text_input("Senha", type="password")
        s2 = st.text_input("Confirme a senha", type="password")
        if st.form_submit_button("Criar e entrar", type="primary"):
            if not (nome and usuario and s1):
                st.error("Preencha nome, usuário e senha.")
            elif s1 != s2:
                st.error("As senhas não conferem.")
            elif len(s1) < 4:
                st.error("Use uma senha com pelo menos 4 caracteres.")
            else:
                db.criar_usuario(usuario, nome, s1, admin=True)
                st.session_state["usuario"] = db.autenticar(usuario, s1)
                st.rerun()


def tela_login():
    st.title("💰 Controle Financeiro")
    with st.form("login"):
        usuario = st.text_input("Usuário")
        senha = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar", type="primary"):
            u = db.autenticar(usuario, senha)
            if u:
                st.session_state["usuario"] = u
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")


def main():
    if not db.tem_usuarios():
        tela_primeiro_acesso()
        return
    if not st.session_state.get("usuario"):
        tela_login()
        return

    u = st.session_state["usuario"]
    with st.sidebar:
        st.markdown(f"### 💰 Controle Financeiro\nOlá, **{u['nome']}**")
        pagina = st.radio("Menu", list(PAGINAS), label_visibility="collapsed", key="menu")
        st.divider()
        if st.button("Sair", width="stretch"):
            st.session_state.pop("usuario", None)
            st.rerun()
        st.caption(f"Banco: `{db.DB_PATH.split('/')[-1]}`")
    PAGINAS[pagina]()


main()
