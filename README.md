# SST-1 OC Lab — simulador 3dfx Voodoo Graphics

Dashboard interativo em Streamlit para explorar, de forma **didática e probabilística**, o efeito do overclock sobre desempenho relativo, potência e temperatura estimadas da 3dfx Voodoo Graphics (SST-1, 1996). Inclui persistência SQLite com SQLAlchemy, perfis de configuração, histórico dos benchmarks simulados, gráficos Plotly e testes automatizados.

> **Limite importante:** este projeto não emula o chip em nível de ciclo, não executa benchmarks reais e não controla hardware físico. FPS, score, consumo, temperatura e probabilidade de falha são estimativas matemáticas transparentes. A tensão de referência de 2,5 V, a resistência térmica e o limite de 68 °C são parâmetros do modelo, não especificações universais certificadas da SST-1.

## Funcionalidades

- Ajuste de core clock, memory clock, Vcore *modelada*, temperatura ambiente e refrigeração hipotética.
- Estimativas de FPS, índice de desempenho, fill-rate, largura de banda teórica agregada, potência e energia estimada.
- Curva térmica transitória e comparação de FPS entre a configuração nominal (50/50 MHz) e o cenário atual.
- Benchmark simulado com sorteio probabilístico de sucesso ou crash.
- Perfis de overclock salvos em SQLite, incluindo risco e classificação estimada.
- Histórico persistente, visualização de tendências e exclusão explícita com confirmação.
- Motor matemático separado da UI e camada de persistência isolada.

## Requisitos

- Python 3.10 ou superior (recomendado: Python 3.11/3.12).
- Dependências listadas em `requirements.txt`.

## Instalação e execução

### Windows (PowerShell)

```powershell
cd voodoo_sst1_lab
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

### Linux / macOS

```bash
cd voodoo_sst1_lab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

O Streamlit abrirá o painel no navegador. O banco `data/voodoo_sim.db` é criado automaticamente na primeira execução.

## Configuração do banco

Por padrão, utiliza SQLite no caminho `data/voodoo_sim.db`. Para mudar o caminho do arquivo:

```bash
# Linux/macOS
export VOODOO_DB_PATH=/caminho/voodoo_sim.db
```

```powershell
# Windows PowerShell
$env:VOODOO_DB_PATH = "C:\dados\voodoo_sim.db"
```

Também aceita `VOODOO_DATABASE_URL` com uma URL SQLAlchemy, por exemplo `sqlite:////tmp/voodoo.db`. Para outros bancos SQL compatíveis, configure a URL e instale o driver correspondente.

## Execução com Docker

Também é possível criar uma imagem sem instalar dependências Python no host:

```bash
docker build -t voodoo-sst1-lab .
docker run --rm -p 8501:8501 -v voodoo-data:/app/data voodoo-sst1-lab
```

Abra `http://localhost:8501`. O volume `voodoo-data` preserva o banco entre reinicializações. A imagem roda com um usuário sem privilégios e inclui health check.

## Testes

```bash
pip install -r requirements-dev.txt
pytest -q
```

Os testes cobrem referência de desempenho, aumento relativo com overclock, efeito da refrigeração, risco de falha heurístico, reprodutibilidade com seed e validação de entrada.

## Estrutura

```text
voodoo_sst1_lab/
├── app.py                  # Interface Streamlit
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── Dockerfile
├── .dockerignore
├── .github/workflows/quality.yml
├── README.md
├── voodoo_sim/
│   ├── __init__.py
│   ├── engine.py           # Equações e benchmark probabilístico
│   └── db.py               # Modelos e acesso SQLite/SQLAlchemy
└── tests/
    └── test_engine.py
```

## Modelo de engenharia

- **Desempenho:** os clocks são normalizados pela referência de 50 MHz; uma combinação ponderada representa a progressão quase linear, enquanto um termo de gargalo representa limitações quando core e memória sobem de forma desigual.
- **Potência:** `P ≈ 12,5 W × (0,68 × f_core_ratio + 0,32 × f_mem_ratio) × (V / 2,5)²`.
- **Temperatura de regime:** `T∞ = Tambiente + P × Rθ`.
- **Resposta transitória:** `T(t) = Tambiente + (T∞ − Tambiente) × (1 − e^(−t/τ))`.
- **Falha:** função logística heurística aumenta o risco com o overclock e a temperatura e reduz o risco modelado quando a tensão ou a refrigeração são aumentadas. A tensão também aumenta a potência, criando um compromisso explícito.

Os coeficientes de potência, refrigeração, desempenho e estabilidade são hipóteses do simulador. Não são uma curva de engenharia inversa validada para todos os fabricantes de placas SST-1.

## Referências históricas

- DOS Days, *3Dfx Voodoo Graphics*: https://dosdays.co.uk/topics/Manufacturers/3dfx/3dfx_voodoo.php
- 3dfx Interactive, *SST-1 High Performance Graphics Engine for 3D Game Acceleration*, Rev. 1.61: https://www.bitsavers.org/components/3dfx/Voodoo1_SST-1_Spec_r1.61_199912.pdf
- Hardware.fr, *Overclocking — 3dfx Voodoo Graphics*: https://www.hardware.fr/articles/188-1/overclocking-3dfx-voodoo-graphics.html
- 3DFx.eu, *Voodoo1*: https://3dfx.eu/voodoo1

## Observações de produção

Este repositório é um ponto de partida sólido para um dashboard local. Para operação multiusuário em produção, recomenda-se mover a persistência para PostgreSQL, configurar autenticação/autorização, logs estruturados, migrações Alembic, monitoramento e CI/CD. O SQLite atende bem ao uso local e à demonstração.
