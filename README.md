# OptiLine -- Balanceador de Linha de Produção

Aplicativo em Streamlit para balanceamento de linhas de montagem manuais de modelo único, implementando as três heurísticas clássicas apresentadas em Groover (2010, Cap. 15).

## O que o app faz

A partir de uma lista de tarefas com tempos e relações de precedência, o aplicativo:

- Desenha automaticamente o diagrama de precedência em layout hierárquico;
- Calcula o Takt Time (diretamente ou a partir do tempo disponível e da demanda);
- Executa o balanceamento pela heurística selecionada, respeitando precedência e Takt Time;
- Apresenta métricas completas: nº de estações, eficiência, atraso de balanceamento, tempo ocioso e índice de suavidade (Gerhardt, 2007);
- Exibe o diagrama de precedência colorido por estação e o gráfico de cargas por estação;
- Permite exportar os resultados em **CSV** e em **XLSX** (relatório completo com múltiplas abas).

## Métodos implementados

| Método | Critério de ordenação |
|---|---|
| **Regra do Maior Candidato** | Tempo de execução decrescente (T_ek) |
| **Kilbridge & Wester** | Coluna topológica no diagrama de precedência; desempate por T_ek decrescente |
| **Pesos Posicionais (RPW)** | Peso posicional decrescente: T(i) + soma dos tempos de todos os sucessores (Helgeson & Birnie, 1961) |

Todos os três métodos compartilham o mesmo núcleo de alocação: cada tarefa é atribuída à estação atual se não ultrapassar o Takt Time e se todos os predecessores já estiverem alocados; caso contrário, abre-se nova estação.

## Como executar

Requisitos: Python 3.11+ e `conda` (ou `pip`).

### Com conda

```bash
git clone https://github.com/gideaomilanez/balanceador-linha.git
cd balanceador-linha
conda env create -f environment.yml
conda activate balanceador-linha
streamlit run app.py
```

### Com pip

```bash
git clone https://github.com/gideaomilanez/balanceador-linha.git
cd balanceador-linha
pip install -r requirements.txt
streamlit run app.py
```

Ao iniciar, o Streamlit abre o app em `http://localhost:8501`.

## Uso

1. Na barra lateral, informe o Takt Time — digitando o valor direto ou pelo cálculo automático a partir do tempo disponível e da demanda.
2. Selecione o **método heurístico** desejado na barra lateral.
3. Preencha a tabela central com as tarefas, os tempos e os predecessores. Para tarefas sem predecessores, use `-`; para múltiplos predecessores, separe por vírgula.
4. Alternativamente, carregue um **CSV** ou **XLSX** pela barra lateral.
5. Confira o diagrama de precedência no lado direito, que se atualiza conforme você edita a tabela.
6. Clique em **Balancear linha** para executar o algoritmo e ver os resultados.
7. Exporte o resultado em CSV (atribuição) ou XLSX (relatório completo).

### Formato do arquivo de entrada (CSV ou XLSX)

```csv
Tarefa,Tempo,Predecessores
A,5,-
B,3,A
C,4,A
D,3,"B,C"
```

Colunas obrigatórias: `Tarefa`, `Tempo`, `Predecessores`. Vírgula como separador no CSV; valores com vírgula interna (múltiplos predecessores) entre aspas.

### Exportação XLSX

O arquivo gerado contém as seguintes abas:

| Aba | Conteúdo |
|---|---|
| **Atribuição** | Tarefas por estação, tempo, ociosidade e uso (% do TT) |
| **Métricas** | Todos os indicadores do balanceamento |
| **Pesos Posicionais** | Tabela de RPW ordenada *(somente no método RPW)* |
| **Colunas K&W** | Coluna topológica de cada tarefa *(somente no método Kilbridge & Wester)* |

## Nomenclatura

| Termo | Definição |
|---|---|
| Takt Time (TT) | Tempo máximo por estação, imposto pela demanda. TT = Tempo disponível ÷ Demanda |
| Tempo de Ciclo (TC) | Tempo da estação mais carregada após o balanceamento |
| Eficiência | ΣTᵢ ÷ (n × TT) × 100% |
| Atraso de balanceamento | 100% − Eficiência |
| Tempo ocioso total | n × TT − ΣTᵢ |
| Índice de Suavidade (IS) | √Σ(S_max − Sₚ)² — quanto menor, mais uniforme o balanceamento |

## Estrutura do projeto

```
balanceador-linha/
├── app.py                Aplicação Streamlit
├── requirements.txt      Dependências pip
├── environment.yml       Ambiente conda
├── .gitignore
├── LICENSE
└── README.md
```

## Tecnologias

Python 3.11, Streamlit (interface), Plotly (gráficos e diagrama de precedência), NetworkX (layout hierárquico do grafo), Pandas e NumPy (dados e cálculos), OpenPyXL e XlsxWriter (exportação Excel).

## Referências

- GROOVER, M. P. *Automação Industrial e Sistemas de Fabricação*. 3. ed. Pearson, 2010. Cap. 15.
- HELGESON, W. B.; BIRNIE, D. P. Assembly Line Balancing Using the Ranked Positional Weight Technique. *Journal of Industrial Engineering*, v. 12, n. 6, 1961.
- GERHARDT, M. P. *Sistemática para aplicação de procedimentos de balanceamento em linhas de montagem multi-modelos*. Dissertação de Pós-Graduação. UFRGS / Escola de Engenharia, Porto Alegre, 2005.

## Autor

Gideão

## Licença

Distribuído sob a licença MIT. Consulte [LICENSE](LICENSE) para mais detalhes.
