# 💰 Controle Financeiro

Controle financeiro pessoal em **Streamlit + SQLite**. Roda 100% na sua máquina; o banco fica em `data/financeiro.db` e **não é versionado** (está no `.gitignore`).

## Rodar

```bash
# Windows: dê dois cliques em run.bat
# Linux/Mac:
./run.sh
```

Ou manualmente:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows  |  source .venv/bin/activate (Linux/Mac)
pip install -r requirements.txt
streamlit run app.py
```

No primeiro acesso o sistema pede para criar o usuário administrador.

## O que tem

| Aba | O que faz |
|---|---|
| **Saúde Financeira** | Score 0–100 do mês (sobra da renda, cartão × renda, fixos × renda, quanto guardou), onde o dinheiro foi, maiores gastos, 12 meses de créditos × gastos, comparativo mês a mês por modalidade, oportunidades de melhora, evolução do patrimônio. Painel de mercado: Selic, CDI do mês, dólar, euro e as criptos da sua carteira. |
| **Créditos do mês** | Salário, horas extras, 13º, férias, bônus... (tipos configuráveis). |
| **Gastos** | **Fixos** (Aluguel, Energia, Gás, Internet, Carona, Fatura Vivo, Crossfit, Pós, Seguro — já cadastrados; valor previsto, marcar pago). **Cartão de crédito** com cadastro de cartões (dia de fechamento/vencimento/limite), compra parcelada gera as parcelas nas faturas seguintes, visão por fatura e comprometido futuro. **Débito/Pix**. Todo lançamento tem modalidade → categoria (ex.: Alimentação/Lazer → Ifood; Despesa Casa → Coopercica; Transporte → Combustível; Compras Diversas → Enjoei). |
| **Planejamento futuro** | Objetivos (viagem, troca de carro, casa, celular...), valor alvo, prazo, prioridade, aportes e quanto guardar por mês para chegar lá. |
| **Investimentos** | Cadastro por tipo (CDB, Tesouro, LCI/LCA, fundos, ações, FII, **cripto, dólar, euro**...). Lançamento mês a mês (aporte, resgate, saldo; para cripto/moeda: quantidade + cotação, com saldo calculado automaticamente). Rendimento e rentabilidade por mês, comparação com **CDI e poupança**, rótulos de *baixo rendimento* / *destaque*. Metas de aporte mensal, anual e patrimônio em X anos (com o aporte mensal necessário). |
| **Imposto de Renda** | Importe os **informes em PDF** (comprovante do empregador/INSS, bancos e corretoras, plano de saúde, escola, previdência): o sistema lê o texto, reconhece o tipo, extrai os valores e monta os lançamentos **para você conferir** antes de gravar — organizados nas fichas da declaração (tributáveis, isentos, exclusiva, pagamentos, dependentes, bens e direitos, dívidas, renda variável). Botão para **sugerir lançamentos a partir do próprio sistema** (saldos dos investimentos em 31/12, rendimentos, salário, saúde/educação). **Apuração** completa × simplificada pela tabela anual (editável por ano, com a redução para renda baixa de 2026), IR retido, saldo a pagar/restituir, alertas (variação patrimonial × renda, limite de educação, obrigatoriedade) e **roteiro em Excel**, uma aba por ficha, para digitar no programa da Receita. |
| **Configurações** | Fixos (tabela editável: nome, valor previsto, **dia de vencimento**, ativo), categorias/modalidades, cartões, tipos de crédito, **cotações do painel**, parâmetros (limites de alerta, valores manuais de CDI/dólar/euro), usuários e senha. |

## Cotações e índices

Buscados automaticamente, sem chave de API, e guardados no banco:

- **Banco Central (SGS):** Selic meta, CDI acumulado no mês, poupança mensal, IPCA do mês, dólar e euro PTAX.
- **CoinGecko:** criptomoedas em BRL (BTC, ETH, SOL, BNB, XRP, ADA, USDT, USDC, DOGE, DOT, LTC, MATIC — outros pelo id do CoinGecko).

Você escolhe **o que aparece no painel** em **Configurações → Cotações** (quais taxas, quais moedas, quais criptos — inclusive outras pelo id do CoinGecko). Sem internet, o sistema usa o último valor guardado ou os valores manuais de **Configurações → Parâmetros**; a origem de cada número aparece embaixo dele. As cotações ficam em cache por 15 minutos.

## Importar planilhas, faturas e extratos

Em **Gastos → 📥 Importar planilha** há três modos:

| Modo | O que faz |
|---|---|
| **Planilha de gastos** | .xlsx/.csv com data, descrição, valor, tipo (categoria), parcelas e meio (cartão/débito). Há um modelo para baixar. |
| **Fatura de cartão** | CSV/Excel exportado do **Nubank**, **Itaú** ou **XP** (reconhecimento automático do cabeçalho; ou mapeie as colunas). Você escolhe o cartão e o mês da fatura; pagamentos/estornos são ignorados; parcelas "2/5" entram como a parcela 2 de 5. |
| **Extrato da conta** | Saídas viram gastos no débito; entradas podem virar créditos (salário, reembolso...). Pagamento de fatura e aplicações/resgates são ignorados por padrão para não contar em dobro. |

Em todos os modos cada **tipo** que veio no arquivo (categoria do banco ou estabelecimento) é amarrado a uma categoria cadastrada — ou você **assume o nome que veio**, ou **cria uma com outro nome**, ou ignora. A amarração fica gravada e vem preenchida na próxima importação. Lançamentos repetidos (mesma data, descrição e valor) são pulados.

## Como o cartão funciona

Compra feita **depois do dia de fechamento** cai na fatura do mês seguinte. Compra parcelada em N vezes gera N lançamentos, um por fatura, com o valor dividido (centavos ajustados na última). Excluir uma parcela exclui a compra inteira.

## Como o rendimento é calculado

Para cada investimento e mês:

```
rendimento     = saldo_final − saldo_anterior − aporte + resgate
rentabilidade  = rendimento ÷ (saldo_anterior + aporte)
```

O rótulo compara a rentabilidade com o CDI do mês: abaixo de 70% do CDI = **baixo rendimento**; acima de 120% = **destaque**. Os dois limites são configuráveis.

## Estrutura

```
app.py            entrada: login, menu e roteamento
db.py             SQLite: schema, dados padrão, todas as consultas
mercado.py        cotações e índices (BCB, CoinGecko) com cache e fallback
utils.py          formatação R$, competências, tema dos gráficos
modulos/          uma página por aba
data/             banco local (ignorado pelo git)
```

## Backup

O banco é um arquivo só: copie `data/financeiro.db`.

## Publicar no GitHub

```bash
git init
git add .
git commit -m "Controle financeiro: primeira versão"
git remote add origin https://github.com/SEU_USUARIO/controle-financeiro.git
git push -u origin main
```

O `.gitignore` já impede que o banco com seus dados suba para o repositório.
