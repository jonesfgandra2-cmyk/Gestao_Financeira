"""Controle Financeiro Pessoal — Streamlit + SQLite.

Execute:  streamlit run app.py
"""
import streamlit as st

import db
from modulos import (configuracoes, creditos, dashboard, gastos, investimentos, ir,
                     planejamento)

st.set_page_config(page_title="Controle Financeiro", page_icon="💰", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
  .block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1280px;}
  h1, h2, h3 {letter-spacing: -.01em;}
  div[data-testid="stMetric"] {border:1px solid #e3e2de; border-radius:8px; padding:10px 14px; background:#fff;}

  /* ── Menu lateral ─────────────────────────────────────────────── */
  [data-testid="stSidebar"] {background: #12171f; border-right: 1px solid #1f2733;}
  [data-testid="stSidebar"] * {color: #e6eaf0;}
  [data-testid="stSidebar"] .block-container,
  [data-testid="stSidebar"] > div:first-child {padding-top: 1.2rem;}
  .sb-brand {display:flex; align-items:center; gap:10px; margin: 0 0 18px 2px;}
  .sb-logo {width:36px; height:36px; border-radius:10px; display:flex; align-items:center; justify-content:center;
            background: linear-gradient(135deg, #2a78d6, #1baf7a); font-size:18px; color:#fff;}
  .sb-title {font-weight:700; font-size:15px; letter-spacing:-.01em; line-height:1.1;}
  .sb-sub {font-size:11px; color:#8b97a6 !important;}
  .sb-user {display:flex; align-items:center; gap:10px; padding:10px 12px; border-radius:10px;
            background:#1a2130; margin-bottom:18px;}
  .sb-avatar {width:34px; height:34px; border-radius:50%; background:#2a78d6; color:#fff; font-weight:700;
              display:flex; align-items:center; justify-content:center; font-size:13px; flex:none;}
  .sb-user-name {font-weight:600; font-size:14px; line-height:1.15;}
  .sb-user-role {font-size:11px; color:#8b97a6 !important;}
  .sb-section {font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:#6b7684 !important;
               font-weight:600; margin: 12px 0 0 8px;}
  [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {margin-bottom:0;}
  /* itens de navegacao = botoes tercearios/primarios, alinhados a esquerda */
  [data-testid="stSidebar"] .stButton > button {
      width:100%; justify-content:flex-start; text-align:left; border-radius:10px;
      padding: 0 12px; min-height: 40px; height: 40px; font-size:14.5px; font-weight:500;
      border:1px solid transparent; background: transparent; color:#c3cbd6; box-shadow:none;
      transition: background .12s;
  }
  [data-testid="stSidebar"] .stButton > button:hover {background:#1d2532; color:#fff; border-color:#1d2532;}
  [data-testid="stSidebar"] .stButton > button[kind="primary"] {
      background:#1f2f45; color:#fff; border-color:#2a78d6; font-weight:600;
      box-shadow: inset 3px 0 0 #2a78d6;
  }
  [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {background:#24364f;}
  [data-testid="stSidebar"] .stButton > button > div {width:100%; text-align:left; justify-content:flex-start;}
  [data-testid="stSidebar"] .stButton > button p {color: inherit; text-align:left;}
  [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {gap: .25rem;}
  [data-testid="stSidebar"] [data-testid="stElementContainer"] {margin:0;}
  [data-testid="stSidebar"] .stButton {margin: 0;}
  [data-testid="stSidebar"] hr {border-color:#243040; margin: 14px 0;}
  .sb-foot {font-size:11px; color:#6b7684 !important; margin-top:6px;}
  .sb-foot code {color:#8b97a6; background:#1a2130; padding:1px 5px; border-radius:4px;}
  [data-testid="stSidebar"] button[kind="secondary"].sb-sair {background:#1a2130;}
</style>""", unsafe_allow_html=True)

db.iniciar_banco()

# (rótulo, ícone, função, seção)
PAGINAS = [
    ("Saúde Financeira", "📊", dashboard.render, "Visão geral"),
    ("Créditos do mês", "💵", creditos.render, "Movimento"),
    ("Gastos", "🧾", gastos.render, "Movimento"),
    ("Planejamento futuro", "🎯", planejamento.render, "Futuro"),
    ("Investimentos", "📈", investimentos.render, "Futuro"),
    ("Imposto de Renda", "🧾", ir.render, "Obrigações"),
    ("Configurações", "⚙️", configuracoes.render, "Sistema"),
]


def _iniciais(nome: str) -> str:
    partes = [p for p in (nome or "").split() if p]
    return "".join(p[0] for p in partes[:2]).upper() or "•"


def menu_lateral(u):
    """Menu lateral: marca, usuário, navegação por seções e rodapé."""
    st.markdown(
        '<div class="sb-brand"><div class="sb-logo">💰</div>'
        '<div><div class="sb-title">Controle Financeiro</div>'
        '<div class="sb-sub">pessoal · local</div></div></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="sb-user"><div class="sb-avatar">{_iniciais(u["nome"])}</div>'
        f'<div><div class="sb-user-name">{u["nome"]}</div>'
        f'<div class="sb-user-role">{"Administrador" if u.get("admin") else "Usuário"}</div></div></div>',
        unsafe_allow_html=True)

    atual = st.session_state.get("pagina", PAGINAS[0][0])
    secao_ant = None
    for rotulo, icone, _, secao in PAGINAS:
        if secao != secao_ant:
            st.markdown(f'<div class="sb-section">{secao}</div>', unsafe_allow_html=True)
            secao_ant = secao
        ativo = rotulo == atual
        if st.button(f"{icone}  {rotulo}", key=f"nav_{rotulo}", width="stretch",
                     type="primary" if ativo else "tertiary"):
            st.session_state["pagina"] = rotulo
            st.rerun()

    st.markdown("<hr>", unsafe_allow_html=True)
    if st.button("⏻  Sair", key="btn_sair", width="stretch", type="tertiary"):
        st.session_state.pop("usuario", None)
        st.rerun()
    st.markdown(f'<div class="sb-foot">Banco local: <code>{db.DB_PATH.split("/")[-1].split(chr(92))[-1]}</code></div>',
                unsafe_allow_html=True)
    return atual


LOGIN_CSS = """
<style>
  [data-testid="stAppViewContainer"] {
      background: radial-gradient(1200px 600px at 10% -10%, #dfeaf8 0%, transparent 60%),
                  radial-gradient(900px 500px at 110% 110%, #dff3ec 0%, transparent 55%), #f7f8fa;
  }
  [data-testid="stSidebar"], [data-testid="collapsedControl"] {display:none;}
  .block-container {max-width: 440px; padding-top: 9vh;}
  .lg-logo {width:56px; height:56px; border-radius:16px; margin: 0 auto 14px; display:flex; align-items:center;
            justify-content:center; font-size:28px; background: linear-gradient(135deg, #2a78d6, #1baf7a);
            box-shadow: 0 8px 24px rgba(42,120,214,.25);}
  .lg-title {text-align:center; font-size:28px !important; font-weight:700; letter-spacing:-.02em; margin:0;
             line-height:1.15;}
  .lg-sub {text-align:center; color:#6b6a66; font-size:15px !important; margin: 6px 0 22px;}
  div[data-testid="stForm"] {background:#fff; border:1px solid #e3e2de; border-radius:16px; padding: 22px 22px 8px;
                              box-shadow: 0 10px 30px rgba(16,22,31,.06);}
  div[data-testid="stForm"] .stTextInput input {border-radius:10px; padding: 10px 12px;}
  div[data-testid="stForm"] button[kind="primaryFormSubmit"] {border-radius:10px; padding: 10px 0; font-weight:600;}
  .lg-foot {text-align:center; color:#8a8987; font-size:12px; margin-top:16px;}
</style>"""


def _cabecalho_login(sub):
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="lg-logo">💰</div><div class="lg-title">Controle Financeiro</div>'
                f'<div class="lg-sub">{sub}</div>', unsafe_allow_html=True)


def tela_primeiro_acesso():
    _cabecalho_login("Primeiro acesso — crie o usuário administrador")
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
    _cabecalho_login("Suas finanças, na sua máquina.")
    with st.form("login"):
        usuario = st.text_input("Usuário", placeholder="seu usuário")
        senha = st.text_input("Senha", type="password", placeholder="••••••••")
        if st.form_submit_button("Entrar", type="primary", width="stretch"):
            u = db.autenticar(usuario, senha)
            if u:
                st.session_state["usuario"] = u
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")
    st.markdown('<div class="lg-foot">Os dados ficam só neste computador (SQLite local).</div>',
                unsafe_allow_html=True)


def main():
    if not db.tem_usuarios():
        tela_primeiro_acesso()
        return
    if not st.session_state.get("usuario"):
        tela_login()
        return

    u = st.session_state["usuario"]
    with st.sidebar:
        pagina = menu_lateral(u)
    for rotulo, _, render, _ in PAGINAS:
        if rotulo == pagina:
            render()
            break


main()
