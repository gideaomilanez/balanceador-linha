# Balanceador de Linha de Produção

Aplicativo em Streamlit que realiza o balanceamento de linhas de produção pelo método do Peso Posicional (RPW — *Ranked Positional Weight*).

## O que o app faz

A partir de uma lista de tarefas com tempos e relações de precedência informadas pelo usuário, o aplicativo:

- Desenha automaticamente o diagrama de precedência em layout hierárquico;
- Calcula o Takt Time (diretamente ou a partir do tempo disponível e da demanda);
- Executa o balanceamento da linha pela heurística do Peso Posicional, respeitando precedência e Takt Time;
- Apresenta os resultados com métricas (nº de estações, eficiência, atraso de balanceamento, tempo ocioso, índice de suavidade), diagrama colorido por estação e gráfico de cargas;
- Permite exportar o resultado em CSV.

## Como executar

Requisitos: Python 3.11+ e `conda` (ou `pip`).

### Com conda

```bash
git clone https://github.com/SEU_USUARIO/balanceador-linha.git
cd balanceador-linha
conda env create -f environment.yml
conda activate balanceador-linha
streamlit run app.py
```

### Com pip

```bash
git clone https://github.com/SEU_USUARIO/balanceador-linha.git
cd balanceador-linha
pip install -r requirements.txt
streamlit run app.py
```

Ao iniciar, o Streamlit abre o app em `http://localhost:8501`.

## Uso

1. Na barra lateral, informe o Takt Time — seja digitando o valor direto, seja pelo cálculo automático a partir do tempo disponível e da demanda.
2. Preencha a tabela central com as tarefas, os tempos e os predecessores. Para tarefas sem predecessores, use `-`; para múltiplos predecessores, separe por vírgula.
3. Alternativamente, carregue um CSV pela barra lateral.
4. Confira o diagrama de precedência no lado direito, que se atualiza conforme você edita a tabela.
5. Clique em *Balancear linha (Peso Posicional)* para executar o algoritmo e ver os resultados.

### Formato do CSV

```csv
Tarefa,Tempo,Predecessores
A,5,-
B,3,A
C,4,A
D,3,"B,C"
```

Vírgula como separador; valores com vírgula interna (múltiplos predecessores) entre aspas.

## Fundamentação

A heurística do Peso Posicional foi proposta por Helgeson e Birnie em 1961. Para cada tarefa *i*, calcula-se:

```
Peso(i) = T(i) + soma dos tempos de todos os sucessores de i
```

As tarefas são ordenadas em ordem decrescente de peso posicional e atribuídas às estações na sequência: cada tarefa é alocada à estação atual se sua adição não ultrapassar o Takt Time e se todos os predecessores já tiverem sido alocados; caso contrário, abre-se nova estação.

### Nomenclatura

| Termo | Definição |
|---|---|
| Takt Time (TT) | Tempo máximo por estação, imposto pela demanda. TT = Tempo disponível ÷ Demanda |
| Tempo de Ciclo (TC) | Tempo da estação mais carregada após o balanceamento |
| Eficiência | ΣTᵢ ÷ (n × TT) × 100% |
| Atraso de balanceamento | 100% − Eficiência |
| Tempo ocioso total | n × TT − ΣTᵢ |

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

Python 3.11, Streamlit (interface), Plotly (gráficos e diagrama de precedência), NetworkX (layout hierárquico do grafo), Pandas e NumPy (dados e cálculos).

## Referências

- HELGESON, W. B.; BIRNIE, D. P. Assembly Line Balancing Using the Ranked Positional Weight Technique. *Journal of Industrial Engineering*, v. 12, n. 6, 1961.
- EBERT, S. *Flexible Line Balancing* (software educacional). University of Wisconsin-Stout. Referência conceitual para o desenho da interface; nenhum código foi reutilizado.

## Autor

Gideão

## Licença

Distribuído sob a licença MIT. Consulte [LICENSE](LICENSE) para mais detalhes.
