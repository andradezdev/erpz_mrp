# ERPZ MRP — Planejamento de Necessidades de Materiais (Multiempresa)

Aplicativo Frappe / ERPNext para planejamento de necessidades de materiais (MRP I / MRP II) com suporte nativo a operações multiempresa, rastreabilidade hierárquica multinível, controle estrito de cenários por Ticket e geração automática de ordens operacionais (Work Orders, Material Requests e Stock Entries).

Baseado nos conceitos e especificações avançadas de mercado (TOTVS Protheus MRP MATA712 / TDN TOTVS).

---

## Principais Funcionalidades

### 1. Motor de Cálculo Cronológico
- **Saldo Projetado Diário:** `Saldo = Saldo Anterior + Entradas Previstas - Demandas`.
- **Demandas Integradas:** Pedidos de Venda (`Sales Order`), Planos de Produção (`Production Plan`) e Requisições de Consumo (`Material Request`).
- **Entradas Programadas:** Ordens de Compra (`Purchase Order`), Ordens de Produção (`Work Order`) e Transferências em trânsito.
- **Explosão Multinível Recursiva de BOM:** Varredura topológica de estruturas (Nível 0 ao Nível N) com detecção e bloqueio de loops infinitos (ciclos circulares).
- **Tratamento de Perdas (Scrap):** Aplicação percentual de perdas e quebras da estrutura do produto.
- **Políticas de Lote:** Lote Mínimo (`min_order_qty`), Lote Econômico e Múltiplos de Abastecimento.
- **Lead Time com Calendário Operacional:** Cálculo retroativo de datas com base em dias úteis ou corridos, respeitando listas de feriados (`Holiday List`).

### 2. Controle de Cenários por Ticket
- Ciclo de vida imutável: **Simulação $\rightarrow$ Calculado $\rightarrow$ Em Análise $\rightarrow$ Aprovado $\rightarrow$ Efetivado**.
- Comparação histórica de cenários sem sobreposição de dados.
- Vínculo obrigatório e bidirecional (`custom_mrp_ticket`) com todos os documentos gerados no ERPNext.

### 3. Planejamento Multiempresa Consolidado
- Grupos de planejamento com empresa centralizadora e empresas parceiras.
- Prioridade determinística de abastecimento.
- Avaliação automática de transferência de estoque disponível vs. produção na empresa parceira com lead times encadeados.

### 4. Aglutinação de Necessidades
- Consolidação configurável de ordens de produção e compras por periodicidade: **Diária, Semanal, Quinzenal ou Mensal**.
- Preservação integral da matriz de rastreabilidade para cada demanda original componente.

### 5. Central de Planejamento MRP (Desk Workbench)
- **Painel Interativo:** Indicadores executivos (KPIs), visualização sumarizada com filtros combinados.
- **Gráfico Cronológico:** Evolução do saldo projetado com alertas de ruptura e estoque de segurança.
- **Árvore de Rastreabilidade:** Navegação visual encadeada de Pedidos $\rightarrow$ OPs $\rightarrow$ Componentes $\rightarrow$ Requisições de Compra / Transferência.
- **Exportação:** Exportação estruturada para relatórios analíticos.

---

## Estrutura do Módulo

```
erpz_mrp/
├── erpz_mrp/
│   ├── engine/
│   │   ├── calendar_utils.py    # Cálculo de dias úteis e lead times
│   │   ├── multi_company.py     # Decisão de abastecimento multiempresa
│   │   ├── aglutination.py      # Aglutinação de ordens por periodicidade
│   │   ├── mrp_engine.py        # Motor de cálculo em 20 etapas
│   │   └── execution.py         # Geração de Work Orders, Material Requests e Stock Entries
│   ├── api.py                   # APIs Whitelisted REST para Desk e UI
│   ├── setup.py                 # Custom fields e vínculos no ERPNext
│   ├── page/
│   │   └── mrp_workbench/       # Painel interativo de controle MRP
│   ├── workspace/
│   │   └── erpz_mrp/            # Workspace e menus do módulo
│   └── erpz_mrp/
│       └── doctype/
│           ├── mrp_ticket/
│           ├── mrp_settings/
│           ├── mrp_company_group/
│           ├── mrp_inter_company_lead_time/
│           ├── mrp_result/
│           ├── mrp_timeline/
│           ├── mrp_traceability/
│           ├── mrp_demand/
│           ├── mrp_stock/
│           ├── mrp_planned_inflow/
│           ├── mrp_log/
│           ├── mrp_executed_document/
│           └── mrp_aglutination_link/
```

---

## Licença
MIT License © 2026 ERPZ
