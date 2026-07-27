import csv
import io
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


# =========================================================
# CONFIGURAÇÃO
# =========================================================
st.set_page_config(
    page_title="Dashboard de Vendas | Dauto Tintas",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

LOJAS = {
    "004": "ADE",
    "006": "Gama",
    "012": "Sofnorte",
    "013": "Ceilândia",
    "014": "SIA",
    "015": "Unaí",
    "016": "Águas Lindas",
    "022": "Guará",
    "024": "Luziânia",
}

ORDEM_LOJAS = [
    "ADE", "Gama", "Luziânia", "Sofnorte", "Ceilândia",
    "SIA", "Unaí", "Águas Lindas", "Guará"
]

ANO_ANTERIOR = {
    "ADE": 171267.64,
    "Gama": 169342.44,
    "Luziânia": 319198.39,
    "Sofnorte": 235304.73,
    "Ceilândia": 253148.05,
    "SIA": 322817.82,
    "Unaí": 132666.72,
    "Águas Lindas": 116011.78,
    "Guará": 237466.11,
}

METAS_MES = {
    "ADE": 226479.98,
    "Gama": 222262.12,
    "Luziânia": 362744.56,
    "Sofnorte": 259021.08,
    "Ceilândia": 285322.45,
    "SIA": 339914.05,
    "Unaí": 145190.64,
    "Águas Lindas": 140872.71,
    "Guará": 270285.62,
}

METAS_ANIVERSARIO = {
    "ADE": 70000.00,
    "Gama": 65000.00,
    "Luziânia": 105000.00,
    "Sofnorte": 93000.00,
    "Ceilândia": 90000.00,
    "SIA": 100000.00,
    "Unaí": 48000.00,
    "Águas Lindas": 40000.00,
    "Guará": 90000.00,
}

COLUNAS_VENDAS = [
    "CLIENTE", "TELEFONE", "NR_DOC", "DATA", "DOC_ORIGEM",
    "EMP", "VEN", "CIDADE", "CPF_CNPJ", "COD_PRODUTO",
    "DESCRICAO", "CAMPO_EXTRA", "UN", "CFOP", "QTD",
    "UNIT", "VR_TOTAL", "CUSTO", "MARGEM_PCT"
]

COLUNAS_CADASTRO = {
    "codigo": "Cód.Item",
    "descricao": "Descrição",
    "marca": "Desc. Marca",
    "linha": "Desc. Linha/Grupo",
    "segmento": "SEGMENTO",
}


# =========================================================
# ESTILO
# =========================================================
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.2rem; padding-bottom: 3rem;}
    div[data-testid="stMetric"] {
        background: white;
        border: 1px solid #e8eaf0;
        padding: 14px 16px;
        border-radius: 14px;
        box-shadow: 0 4px 14px rgba(20, 30, 55, 0.05);
    }
    div[data-testid="stMetricLabel"] {font-weight: 700;}
    .section-title {
        font-size: 1.55rem;
        font-weight: 800;
        margin-top: .4rem;
        margin-bottom: .2rem;
    }
    .section-subtitle {
        color: #667085;
        margin-bottom: 1rem;
    }
    .status-card {
        padding: 14px 16px;
        border-radius: 14px;
        border: 1px solid #e5e7eb;
        background: white;
        margin-bottom: 8px;
    }
    .positive {color: #1565c0; font-weight: 800;}
    .negative {color: #c62828; font-weight: 800;}
    .neutral {color: #475467; font-weight: 800;}
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# FUNÇÕES UTILITÁRIAS
# =========================================================
def normalizar_texto(valor):
    if pd.isna(valor):
        return ""
    texto = str(valor).strip()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", texto).upper()


def brl(valor):
    valor = 0.0 if pd.isna(valor) else float(valor)
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(valor, casas=1):
    if pd.isna(valor) or np.isinf(valor):
        return "—"
    return f"{valor:.{casas}f}%".replace(".", ",")


def numero_br(serie):
    texto = serie.astype(str).str.strip()
    texto = texto.str.replace(r"\s+", "", regex=True)
    texto = texto.str.replace(".", "", regex=False)
    texto = texto.str.replace(",", ".", regex=False)
    return pd.to_numeric(texto, errors="coerce")


def codigo_chave(serie):
    return (
        serie.astype(str)
        .str.replace(r"\.0$", "", regex=True)
        .str.extract(r"(\d+)", expand=False)
        .str.lstrip("0")
        .replace("", np.nan)
    )


def detectar_codificacao(conteudo_bytes):
    """Detecta a codificação usando apenas uma amostra do arquivo."""
    amostra = conteudo_bytes[:262_144]
    for encoding in ("utf-8-sig", "cp1252", "latin1"):
        try:
            amostra.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return "latin1"


def encontrar_linha_cabecalho_bytes(conteudo_bytes, encoding):
    """Localiza o cabeçalho sem decodificar nem copiar o CSV inteiro."""
    stream = io.TextIOWrapper(
        io.BytesIO(conteudo_bytes),
        encoding=encoding,
        errors="replace",
        newline="",
    )
    for i, linha in enumerate(stream):
        linha_upper = linha.upper()
        if "CLIENTE" in linha_upper and "VR.TOTAL" in linha_upper and "EMP" in linha_upper:
            return i
        # O cabeçalho institucional fica no início; evita varrer arquivos anormais inteiros.
        if i >= 500:
            break
    return None


def _ler_csv_fallback(conteudo_bytes, encoding, header_idx):
    """Leitor tolerante para relatórios com aspas ou linhas irregulares."""
    texto = conteudo_bytes.decode(encoding, errors="replace")
    trecho = "\n".join(texto.splitlines()[header_idx:])
    leitor = csv.reader(io.StringIO(trecho), delimiter=";", quotechar='"', strict=False)
    next(leitor, None)

    dados = []
    for linha in leitor:
        if len(linha) >= 19:
            dados.append(linha[:19])

    if not dados:
        raise ValueError("Nenhuma linha válida foi encontrada.")
    return pd.DataFrame.from_records(dados, columns=COLUNAS_VENDAS)


@st.cache_data(show_spinner=False, max_entries=3)
def ler_relatorio_vendas(conteudo_bytes, nome_arquivo):
    nome = nome_arquivo.lower()

    if nome.endswith((".xlsx", ".xls")):
        # Leitura única da planilha: identifica o cabeçalho e reaproveita o DataFrame.
        bruto = pd.read_excel(io.BytesIO(conteudo_bytes), header=None, dtype=str)

        header_idx = None
        for idx, row in bruto.head(500).iterrows():
            valores = row.fillna("").astype(str).str.upper()
            texto = " | ".join(valores.tolist())
            if "CLIENTE" in texto and "VR.TOTAL" in texto and "EMP" in texto:
                header_idx = idx
                break

        if header_idx is None:
            raise ValueError("Não foi possível localizar o cabeçalho do relatório de vendas.")

        df = bruto.iloc[header_idx + 1:, :19].copy()
        if df.shape[1] < 19:
            raise ValueError("O relatório não possui as 19 colunas esperadas.")
        df.columns = COLUNAS_VENDAS

    else:
        encoding = detectar_codificacao(conteudo_bytes)
        header_idx = encontrar_linha_cabecalho_bytes(conteudo_bytes, encoding)
        if header_idx is None:
            raise ValueError("Não foi possível localizar o cabeçalho CLIENTE/EMP/VR.TOTAL.")

        # Caminho rápido: parser C do pandas. Não cria uma lista com todas as linhas.
        try:
            df = pd.read_csv(
                io.BytesIO(conteudo_bytes),
                sep=";",
                encoding=encoding,
                skiprows=header_idx,
                header=0,
                names=COLUNAS_VENDAS,
                usecols=range(19),
                dtype=str,
                engine="c",
                low_memory=False,
                on_bad_lines="skip",
            )
        except Exception:
            # Mantém compatibilidade com exportações antigas ou malformadas do Autcom.
            df = _ler_csv_fallback(conteudo_bytes, encoding, header_idx)

    # Limpeza vetorizada
    df = df.dropna(how="all").copy()
    df["EMP"] = df["EMP"].str.extract(r"(\d+)", expand=False).str.zfill(3)
    df["LOJA"] = df["EMP"].map(LOJAS)
    mask_sem_loja = df["LOJA"].isna()
    df.loc[mask_sem_loja, "LOJA"] = (
        "Empresa não mapeada (" + df.loc[mask_sem_loja, "EMP"].fillna("?") + ")"
    )
    df["DATA"] = pd.to_datetime(df["DATA"], dayfirst=True, errors="coerce", format="mixed")

    for coluna in ["QTD", "UNIT", "VR_TOTAL", "CUSTO", "MARGEM_PCT"]:
        df[coluna] = numero_br(df[coluna])

    df["COD_KEY"] = codigo_chave(df["COD_PRODUTO"])
    df["CLIENTE"] = df["CLIENTE"].fillna("CLIENTE NÃO INFORMADO").str.strip()
    df["DESCRICAO"] = df["DESCRICAO"].fillna("PRODUTO NÃO INFORMADO").str.strip()
    df["NR_DOC"] = df["NR_DOC"].fillna("").str.strip()

    # Remove linhas inválidas, preservando devoluções e valores negativos.
    return df.loc[df["DATA"].notna() & df["VR_TOTAL"].notna()].copy()


@st.cache_data(show_spinner=False)
def ler_cadastro_produtos(caminho_ou_bytes, origem="arquivo"):
    if origem == "repositorio":
        xls = pd.ExcelFile(caminho_ou_bytes)
    else:
        xls = pd.ExcelFile(io.BytesIO(caminho_ou_bytes))

    aba = None
    for nome in xls.sheet_names:
        teste = pd.read_excel(xls, sheet_name=nome, nrows=5)
        nomes_norm = {normalizar_texto(c): c for c in teste.columns}
        if "COD.ITEM" in nomes_norm and "DESC. MARCA" in nomes_norm:
            aba = nome
            break

    if aba is None:
        raise ValueError(
            "Não foi localizada uma aba com as colunas Cód.Item e Desc. Marca."
        )

    cadastro = pd.read_excel(xls, sheet_name=aba)

    faltantes = [
        coluna for coluna in COLUNAS_CADASTRO.values()
        if coluna not in cadastro.columns
    ]
    if faltantes:
        raise ValueError("Colunas ausentes no cadastro: " + ", ".join(faltantes))

    cadastro = cadastro.rename(columns={
        COLUNAS_CADASTRO["codigo"]: "COD_CADASTRO",
        COLUNAS_CADASTRO["descricao"]: "DESCRICAO_CADASTRO",
        COLUNAS_CADASTRO["marca"]: "MARCA",
        COLUNAS_CADASTRO["linha"]: "LINHA",
        COLUNAS_CADASTRO["segmento"]: "SEGMENTO",
    })

    cadastro["COD_KEY"] = codigo_chave(cadastro["COD_CADASTRO"])
    cadastro = cadastro.dropna(subset=["COD_KEY"]).copy()

    # Em caso de código repetido, prioriza o cadastro mais completo.
    cadastro["_COMPLETUDE"] = cadastro[["MARCA", "LINHA", "SEGMENTO"]].notna().sum(axis=1)
    cadastro = (
        cadastro.sort_values("_COMPLETUDE", ascending=False)
        .drop_duplicates("COD_KEY", keep="first")
        .drop(columns="_COMPLETUDE")
    )

    return cadastro[[
        "COD_KEY", "DESCRICAO_CADASTRO", "MARCA", "LINHA", "SEGMENTO"
    ]]


def enriquecer_vendas(vendas, cadastro):
    df = vendas.merge(cadastro, on="COD_KEY", how="left")

    df["STATUS_CADASTRO"] = np.where(
        df["DESCRICAO_CADASTRO"].isna(),
        "Produto não encontrado no cadastro",
        "Encontrado"
    )

    for coluna, rotulo in [
        ("MARCA", "MARCA NÃO INFORMADA"),
        ("LINHA", "LINHA/GRUPO NÃO INFORMADO"),
        ("SEGMENTO", "SEGMENTO NÃO INFORMADO"),
    ]:
        df[coluna] = df[coluna].fillna(rotulo).replace("", rotulo)

    return df


def base_lojas(realizado, meta):
    base = pd.DataFrame({"LOJA": ORDEM_LOJAS})
    base["REALIZADO"] = base["LOJA"].map(realizado).fillna(0.0)
    base["META"] = base["LOJA"].map(meta).fillna(0.0)
    base["FALTA"] = base["META"] - base["REALIZADO"]
    base["ATINGIMENTO_PCT"] = np.where(
        base["META"] != 0,
        base["REALIZADO"] / base["META"] * 100,
        np.nan
    )
    return base


def tabela_estilizada(df, formatos=None, positivos=None, negativos=None):
    styler = df.style
    if formatos:
        styler = styler.format(formatos)

    def cor_sinal(valor):
        try:
            if valor > 0:
                return "color: #1565c0; font-weight: 700;"
            if valor < 0:
                return "color: #c62828; font-weight: 700;"
        except Exception:
            pass
        return ""

    for coluna in positivos or []:
        if coluna in df.columns:
            styler = styler.map(cor_sinal, subset=[coluna])

    def cor_falta(valor):
        try:
            if valor > 0:
                return "color: #c62828; font-weight: 700;"
            return "color: #1565c0; font-weight: 700;"
        except Exception:
            return ""

    for coluna in negativos or []:
        if coluna in df.columns:
            styler = styler.map(cor_falta, subset=[coluna])

    return styler




def criar_curva_abc(df, dimensoes, metrica, nome_metrica):
    """Cria Curva ABC pelo valor acumulado da métrica informada."""
    base = (
        df.groupby(dimensoes, dropna=False)
        .agg(VALOR_ABC=(metrica, "sum"))
        .reset_index()
        .sort_values("VALOR_ABC", ascending=False)
        .reset_index(drop=True)
    )

    # A Curva ABC clássica usa contribuições positivas. Valores líquidos
    # iguais ou inferiores a zero permanecem visíveis, mas são classificados como C.
    base["VALOR_POSITIVO_ABC"] = base["VALOR_ABC"].clip(lower=0)
    total = base["VALOR_POSITIVO_ABC"].sum()
    if total == 0:
        base["PARTICIPACAO_PCT"] = 0.0
        base["ACUMULADO_PCT"] = 0.0
    else:
        base["PARTICIPACAO_PCT"] = base["VALOR_POSITIVO_ABC"] / total * 100
        base["ACUMULADO_PCT"] = base["PARTICIPACAO_PCT"].cumsum()

    base["CURVA_ABC"] = np.select(
        [
            (base["VALOR_ABC"] > 0) & (base["ACUMULADO_PCT"] <= 80),
            (base["VALOR_ABC"] > 0) & (base["ACUMULADO_PCT"] <= 95),
        ],
        ["A", "B"],
        default="C",
    )
    base = base.drop(columns="VALOR_POSITIVO_ABC")
    base["POSICAO"] = np.arange(1, len(base) + 1)
    base["NOME_METRICA"] = nome_metrica
    return base


def estilo_curva_abc(df, coluna_classe="Curva ABC"):
    styler = df.style

    def destacar_classe(valor):
        if valor == "A":
            return "background-color: #d8f3dc; color: #14532d; font-weight: 800;"
        if valor == "B":
            return "background-color: #fff3bf; color: #7c5c00; font-weight: 800;"
        if valor == "C":
            return "background-color: #fde2e2; color: #991b1b; font-weight: 800;"
        return ""

    if coluna_classe in df.columns:
        styler = styler.map(destacar_classe, subset=[coluna_classe])
    return styler


def grafico_gauge(valor_pct, titulo):
    valor_plot = max(0, min(float(valor_pct or 0), 150))
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=valor_plot,
        number={"suffix": "%", "font": {"size": 42}},
        title={"text": titulo, "font": {"size": 18}},
        gauge={
            "axis": {"range": [0, 150], "tickwidth": 1},
            "bar": {"color": "#1565c0" if valor_pct >= 100 else "#c62828"},
            "steps": [
                {"range": [0, 80], "color": "#fdecec"},
                {"range": [80, 100], "color": "#fff4d6"},
                {"range": [100, 150], "color": "#e5f0ff"},
            ],
            "threshold": {
                "line": {"color": "#111827", "width": 4},
                "thickness": 0.8,
                "value": 100,
            },
        }
    ))
    fig.update_layout(height=300, margin=dict(l=20, r=20, t=55, b=10))
    return fig


# =========================================================
# CARREGAMENTO
# =========================================================
st.title("Dashboard de Vendas")
st.caption("Acompanhamento da Semana do Aniversário, metas mensais, crescimento e mix de produtos.")

with st.sidebar:
    st.header("Atualização das bases")

    arquivo_vendas = st.file_uploader(
        "Relatório de vendas",
        type=["csv", "txt", "xlsx", "xls"],
        help="Aceita o relatório analítico do Autcom, inclusive com o cabeçalho institucional antes da tabela."
    )

    caminho_cadastro = Path("TABELA PARA DASHBOARD.xlsx")
    cadastro_repositorio = caminho_cadastro.exists()

    if cadastro_repositorio:
        st.success("Cadastro de produtos localizado no repositório.")
        arquivo_cadastro = None
    else:
        st.warning("TABELA PARA DASHBOARD.xlsx não foi encontrada no repositório.")
        arquivo_cadastro = st.file_uploader(
            "Carregue a TABELA PARA DASHBOARD",
            type=["xlsx", "xls"]
        )

    st.divider()
    st.subheader("Filtros")
    incluir_devolucoes = st.checkbox(
        "Considerar devoluções e valores negativos",
        value=True,
        help="Quando marcado, devoluções reduzem o faturamento líquido."
    )

if arquivo_vendas is None:
    st.info("Carregue o relatório de vendas na barra lateral para atualizar o dashboard.")
    st.stop()

if not cadastro_repositorio and arquivo_cadastro is None:
    st.info("Carregue também a TABELA PARA DASHBOARD para classificar linha, marca e segmento.")
    st.stop()

try:
    vendas = ler_relatorio_vendas(arquivo_vendas.getvalue(), arquivo_vendas.name)

    if cadastro_repositorio:
        cadastro = ler_cadastro_produtos(str(caminho_cadastro), origem="repositorio")
    else:
        cadastro = ler_cadastro_produtos(arquivo_cadastro.getvalue(), origem="arquivo")

    dados = enriquecer_vendas(vendas, cadastro)

except Exception as erro:
    st.error(f"Erro ao processar as bases: {erro}")
    st.stop()

if not incluir_devolucoes:
    dados = dados[dados["VR_TOTAL"] >= 0].copy()

if dados.empty:
    st.warning("Nenhum registro válido permaneceu após a leitura e os filtros.")
    st.stop()

data_min = dados["DATA"].min().date()
data_max = dados["DATA"].max().date()

with st.sidebar:
    periodo = st.date_input(
        "Período geral",
        value=(data_min, data_max),
        min_value=data_min,
        max_value=data_max,
    )

if isinstance(periodo, tuple) and len(periodo) == 2:
    inicio, fim = periodo
else:
    inicio = fim = periodo

dados_periodo = dados[
    dados["DATA"].dt.date.between(inicio, fim)
].copy()

lojas_disponiveis = [loja for loja in ORDEM_LOJAS if loja in dados_periodo["LOJA"].unique()]
lojas_extras = sorted(set(dados_periodo["LOJA"].unique()) - set(ORDEM_LOJAS))
lojas_filtro = lojas_disponiveis + lojas_extras

with st.sidebar:
    lojas_selecionadas = st.multiselect(
        "Lojas",
        options=lojas_filtro,
        default=lojas_filtro,
    )

if lojas_selecionadas:
    dados_periodo = dados_periodo[dados_periodo["LOJA"].isin(lojas_selecionadas)].copy()

# Semana fixa solicitada
dados_aniversario = dados[
    (dados["DATA"].dt.month == 7) &
    (dados["DATA"].dt.day.between(27, 31))
].copy()

if lojas_selecionadas:
    dados_aniversario = dados_aniversario[
        dados_aniversario["LOJA"].isin(lojas_selecionadas)
    ].copy()


# =========================================================
# 1. SEMANA DO ANIVERSÁRIO
# =========================================================
st.markdown('<div class="section-title">Semana do Aniversário — 27 a 31 de julho</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-subtitle">Primeira análise do dashboard: realizado, distância para a meta, desempenho diário e ranking.</div>',
    unsafe_allow_html=True
)

real_aniv = dados_aniversario.groupby("LOJA")["VR_TOTAL"].sum().to_dict()
aniv = base_lojas(real_aniv, METAS_ANIVERSARIO)
if lojas_selecionadas:
    aniv = aniv[aniv["LOJA"].isin(lojas_selecionadas)].copy()

total_real_aniv = aniv["REALIZADO"].sum()
total_meta_aniv = aniv["META"].sum()
total_falta_aniv = total_meta_aniv - total_real_aniv
total_pct_aniv = total_real_aniv / total_meta_aniv * 100 if total_meta_aniv else 0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Realizado na semana", brl(total_real_aniv))
c2.metric("Meta da semana", brl(total_meta_aniv))
c3.metric("Atingimento", pct(total_pct_aniv))
c4.metric(
    "Falta para a meta",
    brl(max(total_falta_aniv, 0)),
    delta=("Meta superada" if total_falta_aniv <= 0 else None),
    delta_color="normal"
)

col_tab, col_graf = st.columns([1.35, 1])

aniv_exib = aniv.rename(columns={
    "REALIZADO": "Realizado",
    "META": "Meta",
    "FALTA": "Falta / Excedente",
    "ATINGIMENTO_PCT": "% da Meta",
})

with col_tab:
    st.subheader("Desempenho por loja")
    st.dataframe(
        tabela_estilizada(
            aniv_exib[["LOJA", "Realizado", "Meta", "Falta / Excedente", "% da Meta"]],
            formatos={
                "Realizado": brl,
                "Meta": brl,
                "Falta / Excedente": brl,
                "% da Meta": lambda x: pct(x),
            },
            negativos=["Falta / Excedente"],
        ),
        use_container_width=True,
        hide_index=True,
        height=390,
    )

with col_graf:
    fig_aniv = px.bar(
        aniv,
        x="LOJA",
        y=["REALIZADO", "META"],
        barmode="group",
        labels={"value": "Valor", "variable": "Indicador", "LOJA": "Loja"},
        title="Realizado x Meta da Semana",
    )
    fig_aniv.update_layout(
        height=390,
        legend_title_text="",
        yaxis_tickprefix="R$ ",
        xaxis_tickangle=-25,
    )
    st.plotly_chart(fig_aniv, use_container_width=True)

st.subheader("Ranking das lojas na Semana do Aniversário")
st.caption(
    "Critério: maior diferença entre realizado e meta. "
    "Os maiores valores positivos ficam na frente; entre valores negativos, "
    "fica na frente quem estiver mais próximo de zero."
)

# Diferença = Realizado - Meta.
# O ranking é ordenado diretamente pela diferença, do maior valor para o menor.
# Exemplos: +3 fica à frente de +1; -12 fica à frente de -39.
ranking = aniv.copy()
ranking["DIFERENCA"] = ranking["REALIZADO"] - ranking["META"]
ranking = ranking.sort_values(
    ["DIFERENCA", "REALIZADO"],
    ascending=[False, False]
).reset_index(drop=True)

medalhas = {1: "🥇 1º", 2: "🥈 2º", 3: "🥉 3º"}
ranking["POSIÇÃO_NUM"] = range(1, len(ranking) + 1)
ranking["POSIÇÃO"] = ranking["POSIÇÃO_NUM"].map(
    lambda pos: medalhas.get(pos, f"{pos}º")
)
ranking["PERCENTUAL_META"] = np.where(
    ranking["META"] != 0,
    ranking["REALIZADO"] / ranking["META"] * 100,
    np.nan,
)
ranking["SITUAÇÃO"] = np.select(
    [ranking["DIFERENCA"] > 0, ranking["DIFERENCA"] == 0],
    ["Acima da meta", "Meta atingida"],
    default="Abaixo da meta"
)

ranking_exib = ranking.rename(columns={
    "POSIÇÃO": "Posição",
    "LOJA": "Loja",
    "META": "Meta",
    "REALIZADO": "Realizado",
    "PERCENTUAL_META": "% da Meta",
    "DIFERENCA": "Diferença",
    "SITUAÇÃO": "Situação",
})

def formatar_diferenca(valor):
    if valor > 0:
        return f"+{brl(valor)}"
    if valor < 0:
        return f"-{brl(abs(valor))}"
    return brl(0)

ranking_tabela = ranking_exib[[
    "Posição", "Loja", "Meta", "Realizado",
    "% da Meta", "Diferença", "Situação"
]].copy()

styler_ranking = ranking_tabela.style.format({
    "Meta": brl,
    "Realizado": brl,
    "% da Meta": lambda x: pct(x),
    "Diferença": formatar_diferenca,
})

def destacar_diferenca(valor):
    if valor > 0:
        return "color: #1565c0; font-weight: 800;"
    if valor < 0:
        return "color: #c62828; font-weight: 800;"
    return "color: #475467; font-weight: 800;"

styler_ranking = styler_ranking.map(
    destacar_diferenca,
    subset=["Diferença"]
)

def destacar_podio(linha):
    posicao = str(linha["Posição"])
    if posicao.startswith("🥇"):
        return ["background-color: #fff4bf; font-weight: 800;"] * len(linha)
    if posicao.startswith("🥈"):
        return ["background-color: #f1f3f5; font-weight: 700;"] * len(linha)
    if posicao.startswith("🥉"):
        return ["background-color: #f7dfcf; font-weight: 700;"] * len(linha)
    return [""] * len(linha)

styler_ranking = styler_ranking.apply(destacar_podio, axis=1)

st.dataframe(
    styler_ranking,
    use_container_width=True,
    hide_index=True,
    height=min(470, 44 + 36 * len(ranking_tabela)),
)

st.subheader("Meta diária — comparação de 27 a 31 de julho")
dias_aniversario = pd.date_range("2026-07-27", "2026-07-31", freq="D")
loja_diaria = st.selectbox(
    "Selecione a loja para analisar os cinco dias",
    options=aniv["LOJA"].tolist(),
    key="loja_diaria"
) if not aniv.empty else None

if loja_diaria:
    meta_dia = METAS_ANIVERSARIO[loja_diaria] / 5
    diario = (
        dados_aniversario[dados_aniversario["LOJA"] == loja_diaria]
        .groupby(dados_aniversario["DATA"].dt.normalize())["VR_TOTAL"]
        .sum()
        .reindex(dias_aniversario, fill_value=0)
        .rename("REALIZADO")
        .reset_index()
        .rename(columns={"index": "DATA"})
    )
    diario["META_DIARIA"] = meta_dia
    diario["DIFERENCA"] = diario["REALIZADO"] - diario["META_DIARIA"]
    diario["ATINGIMENTO_PCT"] = diario["REALIZADO"] / diario["META_DIARIA"] * 100
    diario["DIA"] = diario["DATA"].dt.strftime("%d/%m")

    cd1, cd2 = st.columns([1.2, 1])
    with cd1:
        fig_dia = px.bar(
            diario,
            x="DIA",
            y=["REALIZADO", "META_DIARIA"],
            barmode="group",
            title=f"{loja_diaria} — realizado x meta diária",
            labels={"value": "Valor", "variable": "Indicador", "DIA": "Dia"},
        )
        fig_dia.update_layout(height=370, yaxis_tickprefix="R$ ", legend_title_text="")
        st.plotly_chart(fig_dia, use_container_width=True)

    with cd2:
        diario_exib = diario.rename(columns={
            "DIA": "Dia",
            "REALIZADO": "Realizado",
            "META_DIARIA": "Meta diária",
            "DIFERENCA": "Diferença",
            "ATINGIMENTO_PCT": "% da Meta",
        })
        st.dataframe(
            tabela_estilizada(
                diario_exib[["Dia", "Realizado", "Meta diária", "Diferença", "% da Meta"]],
                formatos={
                    "Realizado": brl,
                    "Meta diária": brl,
                    "Diferença": brl,
                    "% da Meta": lambda x: pct(x),
                },
                positivos=["Diferença"],
            ),
            use_container_width=True,
            hide_index=True,
            height=370,
        )

st.divider()


# =========================================================
# 2. VISÃO GERAL DE VENDAS
# =========================================================
st.markdown('<div class="section-title">Vendas gerais por loja</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="section-subtitle">Comparação de Ano-1 usando todo o período do relatório: '
    f'{data_min.strftime("%d/%m/%Y")} a {data_max.strftime("%d/%m/%Y")}.</div>',
    unsafe_allow_html=True
)

# Para os comparativos de Ano-1 e Meta, o realizado considera todo o período
# disponível no relatório carregado, independentemente do filtro geral de datas.
# O filtro de lojas continua sendo respeitado.
dados_comparativo = dados.copy()
if lojas_selecionadas:
    dados_comparativo = dados_comparativo[
        dados_comparativo["LOJA"].isin(lojas_selecionadas)
    ].copy()

real_geral = dados_comparativo.groupby("LOJA")["VR_TOTAL"].sum().to_dict()
geral = pd.DataFrame({"LOJA": ORDEM_LOJAS})
if lojas_selecionadas:
    geral = geral[geral["LOJA"].isin(lojas_selecionadas)].copy()

geral["REALIZADO"] = geral["LOJA"].map(real_geral).fillna(0)
geral["ANO_ANTERIOR"] = geral["LOJA"].map(ANO_ANTERIOR)
geral["VARIACAO_VALOR"] = geral["REALIZADO"] - geral["ANO_ANTERIOR"]
geral["CRESCIMENTO_PCT"] = np.where(
    geral["ANO_ANTERIOR"] != 0,
    geral["VARIACAO_VALOR"] / geral["ANO_ANTERIOR"] * 100,
    np.nan,
)

vg1, vg2, vg3 = st.columns(3)
vg1.metric("Faturamento selecionado", brl(geral["REALIZADO"].sum()))
vg2.metric("Base Ano-1", brl(geral["ANO_ANTERIOR"].sum()))
cres_total = (
    (geral["REALIZADO"].sum() - geral["ANO_ANTERIOR"].sum())
    / geral["ANO_ANTERIOR"].sum() * 100
    if geral["ANO_ANTERIOR"].sum() else 0
)
vg3.metric("Crescimento consolidado", pct(cres_total), delta=pct(cres_total))

g1, g2 = st.columns([1.15, 1])
with g1:
    geral_exib = geral.rename(columns={
        "REALIZADO": "Realizado",
        "ANO_ANTERIOR": "Ano-1",
        "VARIACAO_VALOR": "Variação",
        "CRESCIMENTO_PCT": "Crescimento %",
    })
    st.dataframe(
        tabela_estilizada(
            geral_exib[["LOJA", "Realizado", "Ano-1", "Variação", "Crescimento %"]],
            formatos={
                "Realizado": brl,
                "Ano-1": brl,
                "Variação": brl,
                "Crescimento %": lambda x: pct(x),
            },
            positivos=["Variação", "Crescimento %"],
        ),
        use_container_width=True,
        hide_index=True,
        height=400,
    )

with g2:
    fig_geral = px.bar(
        geral,
        x="LOJA",
        y=["REALIZADO", "ANO_ANTERIOR"],
        barmode="group",
        title="Vendas atuais x Ano-1",
        labels={"value": "Valor", "variable": "Período", "LOJA": "Loja"},
    )
    fig_geral.update_layout(
        height=400,
        yaxis_tickprefix="R$ ",
        xaxis_tickangle=-25,
        legend_title_text=""
    )
    st.plotly_chart(fig_geral, use_container_width=True)

st.divider()


# =========================================================
# 3. METAS MENSAIS
# =========================================================
st.markdown('<div class="section-title">Acompanhamento das metas mensais</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="section-subtitle">Percentual da meta e distância em valor, considerando o faturamento completo '
    f'do relatório ({data_min.strftime("%d/%m/%Y")} a {data_max.strftime("%d/%m/%Y")}).</div>',
    unsafe_allow_html=True
)

metas = base_lojas(real_geral, METAS_MES)
if lojas_selecionadas:
    metas = metas[metas["LOJA"].isin(lojas_selecionadas)].copy()

loja_gauge = st.selectbox(
    "Loja do velocímetro",
    options=metas["LOJA"].tolist(),
    key="loja_gauge"
) if not metas.empty else None

mg1, mg2 = st.columns([1, 1.45])
if loja_gauge:
    linha_gauge = metas[metas["LOJA"] == loja_gauge].iloc[0]
    with mg1:
        st.plotly_chart(
            grafico_gauge(linha_gauge["ATINGIMENTO_PCT"], f"Meta mensal — {loja_gauge}"),
            use_container_width=True
        )
        cc1, cc2 = st.columns(2)
        cc1.metric("Realizado", brl(linha_gauge["REALIZADO"]))
        cc2.metric("Meta", brl(linha_gauge["META"]))

with mg2:
    fig_metas = px.bar(
        metas.sort_values("ATINGIMENTO_PCT"),
        x="ATINGIMENTO_PCT",
        y="LOJA",
        orientation="h",
        text=metas.sort_values("ATINGIMENTO_PCT")["ATINGIMENTO_PCT"].map(lambda x: pct(x)),
        title="% da meta mensal por loja",
        labels={"ATINGIMENTO_PCT": "% da meta", "LOJA": "Loja"},
    )
    fig_metas.add_vline(x=100, line_width=2, line_dash="dash")
    fig_metas.update_layout(height=380, xaxis_ticksuffix="%")
    st.plotly_chart(fig_metas, use_container_width=True)

metas_exib = metas.rename(columns={
    "REALIZADO": "Realizado",
    "META": "Meta mensal",
    "FALTA": "Falta / Excedente",
    "ATINGIMENTO_PCT": "% da Meta",
})
st.dataframe(
    tabela_estilizada(
        metas_exib[["LOJA", "Realizado", "Meta mensal", "Falta / Excedente", "% da Meta"]],
        formatos={
            "Realizado": brl,
            "Meta mensal": brl,
            "Falta / Excedente": brl,
            "% da Meta": lambda x: pct(x),
        },
        negativos=["Falta / Excedente"],
    ),
    use_container_width=True,
    hide_index=True,
)

st.divider()


# =========================================================
# 4. DRILL POR LOJA / CLIENTE / PRODUTO
# =========================================================
st.markdown('<div class="section-title">Drill de vendas por loja</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-subtitle">Detalhamento do cliente, valor comprado e produtos adquiridos.</div>',
    unsafe_allow_html=True
)

opcoes_drill = sorted(dados_periodo["LOJA"].unique())
loja_drill = st.selectbox("Loja para detalhamento", opcoes_drill, key="loja_drill")
drill = dados_periodo[dados_periodo["LOJA"] == loja_drill].copy()

clientes = (
    drill.groupby(["CLIENTE", "CPF_CNPJ"], dropna=False)
    .agg(
        VALOR_COMPRADO=("VR_TOTAL", "sum"),
        QUANTIDADE_ITENS=("QTD", "sum"),
        DOCUMENTOS=("NR_DOC", "nunique"),
    )
    .reset_index()
    .sort_values("VALOR_COMPRADO", ascending=False)
)

dc1, dc2 = st.columns([1, 1.1])
with dc1:
    fig_clientes = px.bar(
        clientes.head(15).sort_values("VALOR_COMPRADO"),
        x="VALOR_COMPRADO",
        y="CLIENTE",
        orientation="h",
        title=f"Top 15 clientes — {loja_drill}",
        labels={"VALOR_COMPRADO": "Valor comprado", "CLIENTE": "Cliente"},
    )
    fig_clientes.update_layout(height=480, xaxis_tickprefix="R$ ")
    st.plotly_chart(fig_clientes, use_container_width=True)

with dc2:
    clientes_exib = clientes.rename(columns={
        "CPF_CNPJ": "CPF/CNPJ",
        "VALOR_COMPRADO": "Valor comprado",
        "QUANTIDADE_ITENS": "Quantidade",
        "DOCUMENTOS": "Documentos",
    })
    st.dataframe(
        clientes_exib.style.format({
            "Valor comprado": brl,
            "Quantidade": lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        }),
        use_container_width=True,
        hide_index=True,
        height=480,
    )

cliente_escolhido = st.selectbox(
    "Selecione um cliente para ver os produtos",
    options=clientes["CLIENTE"].tolist(),
    key="cliente_drill"
)

prod_cliente = (
    drill[drill["CLIENTE"] == cliente_escolhido]
    .groupby(["COD_PRODUTO", "DESCRICAO", "MARCA", "LINHA", "SEGMENTO"], dropna=False)
    .agg(
        QUANTIDADE=("QTD", "sum"),
        VALOR=("VR_TOTAL", "sum"),
        PRECO_MEDIO=("UNIT", "mean"),
    )
    .reset_index()
    .sort_values("VALOR", ascending=False)
    .rename(columns={
        "COD_PRODUTO": "Código",
        "DESCRICAO": "Produto",
        "MARCA": "Marca",
        "LINHA": "Linha/Grupo",
        "SEGMENTO": "Segmento",
        "QUANTIDADE": "Quantidade",
        "VALOR": "Valor",
        "PRECO_MEDIO": "Preço médio",
    })
)

st.dataframe(
    prod_cliente.style.format({
        "Quantidade": lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        "Valor": brl,
        "Preço médio": brl,
    }),
    use_container_width=True,
    hide_index=True,
)

st.divider()


# =========================================================
# 5. PRODUTOS, PARTICIPAÇÃO E CURVA ABC
# =========================================================
st.markdown('<div class="section-title">Produtos e composição do faturamento</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-subtitle">Ranking, participação percentual e Curvas ABC por faturamento e unidades.</div>',
    unsafe_allow_html=True
)

ranking_prod = (
    dados_periodo.groupby(["COD_PRODUTO", "DESCRICAO"], dropna=False)
    .agg(QUANTIDADE=("QTD", "sum"), VALOR=("VR_TOTAL", "sum"))
    .reset_index()
    .sort_values("VALOR", ascending=False)
)

total_faturamento_periodo = dados_periodo["VR_TOTAL"].sum()
total_unidades_periodo = dados_periodo["QTD"].sum()
ranking_prod["PARTICIPACAO_FAT_PCT"] = np.where(
    total_faturamento_periodo != 0,
    ranking_prod["VALOR"] / total_faturamento_periodo * 100,
    0,
)
ranking_prod["PARTICIPACAO_UN_PCT"] = np.where(
    total_unidades_periodo != 0,
    ranking_prod["QUANTIDADE"] / total_unidades_periodo * 100,
    0,
)

rp1, rp2 = st.columns([1, 1.15])
with rp1:
    top_n = st.slider("Quantidade de produtos no ranking", 5, 50, 15)
    fig_prod = px.bar(
        ranking_prod.head(top_n).sort_values("VALOR"),
        x="VALOR",
        y="DESCRICAO",
        orientation="h",
        title=f"Top {top_n} produtos por faturamento",
        labels={"VALOR": "Faturamento", "DESCRICAO": "Produto"},
        text="PARTICIPACAO_FAT_PCT",
    )
    fig_prod.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
    fig_prod.update_layout(height=max(430, top_n * 28), xaxis_tickprefix="R$ ")
    st.plotly_chart(fig_prod, use_container_width=True)

with rp2:
    ranking_prod_exib = ranking_prod.rename(columns={
        "COD_PRODUTO": "Código",
        "DESCRICAO": "Produto",
        "QUANTIDADE": "Quantidade",
        "VALOR": "Valor",
        "PARTICIPACAO_FAT_PCT": "% do Faturamento",
        "PARTICIPACAO_UN_PCT": "% das Unidades",
    })
    st.dataframe(
        ranking_prod_exib.head(100).style.format({
            "Quantidade": lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "Valor": brl,
            "% do Faturamento": lambda x: pct(x, 2),
            "% das Unidades": lambda x: pct(x, 2),
        }),
        use_container_width=True,
        hide_index=True,
        height=max(430, top_n * 28),
    )

st.subheader("Participação no faturamento geral")
abas_mix = st.tabs(["Linha/Grupo", "Marca", "Segmento"])

for aba, dimensao, titulo in zip(
    abas_mix,
    ["LINHA", "MARCA", "SEGMENTO"],
    ["Faturamento por Linha/Grupo", "Faturamento por Marca", "Faturamento por Segmento"],
):
    with aba:
        mix = (
            dados_periodo.groupby(dimensao, dropna=False)
            .agg(FATURAMENTO=("VR_TOTAL", "sum"), QUANTIDADE=("QTD", "sum"))
            .reset_index()
            .sort_values("FATURAMENTO", ascending=False)
        )
        mix["PARTICIPACAO_PCT"] = np.where(
            total_faturamento_periodo != 0,
            mix["FATURAMENTO"] / total_faturamento_periodo * 100,
            0,
        )

        mx1, mx2 = st.columns([1.15, 1])
        with mx1:
            fig_mix = px.bar(
                mix.head(20).sort_values("FATURAMENTO"),
                x="FATURAMENTO",
                y=dimensao,
                orientation="h",
                title=titulo,
                labels={"FATURAMENTO": "Faturamento", dimensao: dimensao.title()},
                text="PARTICIPACAO_PCT",
            )
            fig_mix.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
            fig_mix.update_layout(height=520, xaxis_tickprefix="R$ ")
            st.plotly_chart(fig_mix, use_container_width=True)

        with mx2:
            fig_pizza = px.pie(
                mix.head(12),
                names=dimensao,
                values="FATURAMENTO",
                hole=0.48,
                title="Participação no faturamento geral",
            )
            fig_pizza.update_traces(textinfo="percent+label")
            fig_pizza.update_layout(height=520)
            st.plotly_chart(fig_pizza, use_container_width=True)

        mix_exib = mix.rename(columns={
            dimensao: dimensao.title(),
            "FATURAMENTO": "Faturamento",
            "QUANTIDADE": "Quantidade",
            "PARTICIPACAO_PCT": "% do Total",
        })
        st.dataframe(
            mix_exib.style.format({
                "Faturamento": brl,
                "Quantidade": lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
                "% do Total": lambda x: pct(x, 2),
            }),
            use_container_width=True,
            hide_index=True,
        )

st.divider()

# =========================================================
# 6. CURVAS ABC
# =========================================================
st.markdown('<div class="section-title">Curvas ABC</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-subtitle">Classificação A até 80% acumulado, B de 80% a 95% e C acima de 95%.</div>',
    unsafe_allow_html=True
)

abc_prod_fat = criar_curva_abc(
    dados_periodo, ["COD_PRODUTO", "DESCRICAO"], "VR_TOTAL", "Faturamento"
)
abc_prod_un = criar_curva_abc(
    dados_periodo, ["COD_PRODUTO", "DESCRICAO"], "QTD", "Unidades"
)
abc_linha_fat = criar_curva_abc(
    dados_periodo, ["LINHA"], "VR_TOTAL", "Faturamento"
)
abc_linha_un = criar_curva_abc(
    dados_periodo, ["LINHA"], "QTD", "Unidades"
)

abas_abc = st.tabs([
    "Produtos — Faturamento",
    "Produtos — Unidades",
    "Linha/Grupo — Faturamento",
    "Linha/Grupo — Unidades",
])

config_abc = [
    (abas_abc[0], abc_prod_fat, ["COD_PRODUTO", "DESCRICAO"], "Faturamento"),
    (abas_abc[1], abc_prod_un, ["COD_PRODUTO", "DESCRICAO"], "Unidades"),
    (abas_abc[2], abc_linha_fat, ["LINHA"], "Faturamento"),
    (abas_abc[3], abc_linha_un, ["LINHA"], "Unidades"),
]

for aba, base_abc, dimensoes, tipo_metrica in config_abc:
    with aba:
        resumo_classes = (
            base_abc.groupby("CURVA_ABC", dropna=False)
            .agg(ITENS=("CURVA_ABC", "size"), VALOR=("VALOR_ABC", "sum"))
            .reindex(["A", "B", "C"], fill_value=0)
            .reset_index()
        )
        total_valor_abc = resumo_classes["VALOR"].sum()
        resumo_classes["PARTICIPACAO_PCT"] = np.where(
            total_valor_abc != 0, resumo_classes["VALOR"] / total_valor_abc * 100, 0
        )

        a1, a2, a3 = st.columns(3)
        for col, classe in zip([a1, a2, a3], ["A", "B", "C"]):
            linha = resumo_classes[resumo_classes["CURVA_ABC"] == classe].iloc[0]
            valor_formatado = brl(linha["VALOR"]) if tipo_metrica == "Faturamento" else f"{linha['VALOR']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            col.metric(
                f"Curva {classe}",
                valor_formatado,
                delta=f"{int(linha['ITENS'])} itens | {pct(linha['PARTICIPACAO_PCT'])}",
                delta_color="off",
            )

        abc_exib = base_abc.copy()
        renomear = {
            "POSICAO": "Posição",
            "VALOR_ABC": tipo_metrica,
            "PARTICIPACAO_PCT": "% Participação",
            "ACUMULADO_PCT": "% Acumulado",
            "CURVA_ABC": "Curva ABC",
            "COD_PRODUTO": "Código",
            "DESCRICAO": "Produto",
            "LINHA": "Linha/Grupo",
        }
        abc_exib = abc_exib.rename(columns=renomear)
        colunas = ["Posição"] + [renomear.get(c, c) for c in dimensoes] + [
            tipo_metrica, "% Participação", "% Acumulado", "Curva ABC"
        ]

        styler_abc = estilo_curva_abc(abc_exib[colunas]).format({
            tipo_metrica: brl if tipo_metrica == "Faturamento" else (
                lambda x: f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            ),
            "% Participação": lambda x: pct(x, 2),
            "% Acumulado": lambda x: pct(x, 2),
        })
        st.dataframe(
            styler_abc,
            use_container_width=True,
            hide_index=True,
            height=520,
        )

st.divider()


# =========================================================
# 7. QUALIDADE DO CADASTRO
# =========================================================
st.markdown('<div class="section-title">Qualidade do cadastro de produtos</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="section-subtitle">Itens sem relacionamento ou sem classificação na TABELA PARA DASHBOARD.</div>',
    unsafe_allow_html=True
)

sem_produto = dados_periodo["STATUS_CADASTRO"].ne("Encontrado")
sem_marca = dados_periodo["MARCA"].eq("MARCA NÃO INFORMADA")
sem_linha = dados_periodo["LINHA"].eq("LINHA/GRUPO NÃO INFORMADO")
sem_segmento = dados_periodo["SEGMENTO"].eq("SEGMENTO NÃO INFORMADO")

q1, q2, q3, q4 = st.columns(4)
q1.metric("Produtos não encontrados", dados_periodo.loc[sem_produto, "COD_PRODUTO"].nunique())
q2.metric("Sem marca", dados_periodo.loc[sem_marca, "COD_PRODUTO"].nunique())
q3.metric("Sem linha/grupo", dados_periodo.loc[sem_linha, "COD_PRODUTO"].nunique())
q4.metric("Sem segmento", dados_periodo.loc[sem_segmento, "COD_PRODUTO"].nunique())

pendencias = dados_periodo[
    sem_produto | sem_marca | sem_linha | sem_segmento
].copy()

if pendencias.empty:
    st.success("Todos os produtos vendidos no período possuem cadastro completo.")
else:
    pendencias_resumo = (
        pendencias.groupby(["COD_PRODUTO", "DESCRICAO"], dropna=False)
        .agg(
            FATURAMENTO=("VR_TOTAL", "sum"),
            MARCA=("MARCA", "first"),
            LINHA=("LINHA", "first"),
            SEGMENTO=("SEGMENTO", "first"),
            STATUS=("STATUS_CADASTRO", "first"),
        )
        .reset_index()
        .sort_values("FATURAMENTO", ascending=False)
        .rename(columns={
            "COD_PRODUTO": "Código",
            "DESCRICAO": "Produto",
            "FATURAMENTO": "Faturamento",
            "MARCA": "Marca",
            "LINHA": "Linha/Grupo",
            "SEGMENTO": "Segmento",
            "STATUS": "Status",
        })
    )
    st.warning(
        f"Foram identificados {len(pendencias_resumo)} produtos com alguma pendência de cadastro."
    )
    st.dataframe(
        pendencias_resumo.style.format({"Faturamento": brl}),
        use_container_width=True,
        hide_index=True,
    )

# Diagnóstico de empresas não mapeadas
empresas_nao_mapeadas = sorted(
    dados.loc[~dados["EMP"].isin(LOJAS.keys()), "EMP"].dropna().unique()
)
if empresas_nao_mapeadas:
    st.warning(
        "Empresas sem loja mapeada: " + ", ".join(empresas_nao_mapeadas)
    )

st.caption(
    "Critério do ranking da Semana do Aniversário: diferença entre realizado e meta, ordenada do maior valor para o menor. "
    "Valores negativos são preservados como devoluções quando a opção correspondente está marcada."
)
