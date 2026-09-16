# ERPZ MRP — Planejamento de Necessidades de Materiais (Multiempresa)

Solução corporativa de planejamento de necessidades de materiais (MRP I / MRP II) para o **Frappe Framework** e **ERPNext**, com suporte nativo a operações multiempresa consolidadas, rastreabilidade hierárquica multinível, controle estrito de cenários por Ticket e geração automática de ordens operacionais (Work Orders, Material Requests e Stock Entries).

Desenvolvido com base nos padrões e especificações técnicas de mercado (TOTVS Protheus MRP MATA712 / TDN TOTVS).

---

## Sumário Executivo

O **ERPZ MRP** transforma demandas futuras (pedidos de venda, planos de produção e previsões), estoques atuais e entradas programadas em um plano de abastecimento cronológico executável. O sistema responde com precisão:
1. **O que** precisa ser abastecido?
2. **Quanto** é necessário (aplicando estoques de segurança, lotes mínimos e múltiplos)?
3. **Quando** a necessidade ocorrerá e quando a produção/compra deve ser iniciada (retroagindo o lead time em dias úteis)?
4. **Como** deve ser suprido (Produção própria, Compra ou Transferência entre empresas parceiras)?
5. **Qual é a origem** exata que provocou a necessidade?

---

## 1. Arquitetura e Modelo de Dados

O aplicativo é estruturado em DocTypes nativos do Frappe, divididos em entidades de controle, dados de entrada e resultados:

| DocType | Tipo | Finalidade |
| :--- | :--- | :--- |
| **`MRP Ticket`** | Principal | Chave de controle e identificador único do cenário de cálculo (`MRP-.YYYY.-.#####`). Armazena parâmetros, horizonte, métricas e estado do ciclo de vida. |
| **`MRP Settings`** | Single | Parâmetros globais do sistema: horizontes padrão, tratamento de itens sem BOM/lead time, lista de feriados padrão e regras de aglutinação. |
| **`MRP Result`** | Dados | Resultado sumarizado do cálculo por produto, data e necessidade, com colunas de rastreabilidade (Origem documental, Doc Gerado, Situação). |
| **`MRP Timeline`** | Dados | Linha do tempo cronológica diária do saldo projetado (`Saldo = Anterior + Entradas - Demandas`) com flags de ruptura. |
| **`MRP Traceability`** | Dados | Rastreabilidade em árvore multinível encadeando Pedido de Venda $\rightarrow$ OP Pai $\rightarrow$ Componentes $\rightarrow$ Ordens de Compra / Transferências. |
| **`MRP Demand`** | Dados | Demandas consideradas no planejamento (Sales Orders, Material Requests, Planos de Produção e **Demandas Manuais importadas via Excel**). |
| **`MRP Stock`** | Snapshot | Fotografia do saldo físico, reservado e disponível por depósito e empresa na data inicial do cálculo. |
| **`MRP Planned Inflow`** | Dados | Entradas previstas no horizonte (Purchase Orders, Work Orders em andamento, Transferências). |
| **`MRP Company Group`** | Cadastro | Grupo de empresas participantes do planejamento multiempresa e matriz de prioridades. |
| **`MRP Inter Company Lead Time`**| Cadastro | Prazos logísticos e tempos de transporte entre empresas/filiais por rota ou por item. |
| **`MRP Log`** | Auditoria | Registro de inconsistências, estruturas circulares (loops de BOM), itens sem lead time e advertências de parametrização. |
| **`MRP Executed Document`** | Histórico | Rastreabilidade de todos os documentos oficiais gerados no ERPNext após a efetivação do ticket. |

---

## 2. Motor de Cálculo (Fluxo em 20 Etapas)

O motor em memória (`erpz_mrp.engine.mrp_engine`) executa o fluxo completo do planejamento:

1. **Parâmetros e Validações:** Validação do horizonte (`from_date` a `to_date`), periodicidade e filtros.
2. **Carga do Mestre de Itens:** Consulta a itens ativos, lead times, estoques de segurança e parâmetros de lote.
3. **Carga da Estrutura de Produtos (BOMs):** Leitura de estruturas ativas e padrão no ERPNext, tempos e perdas de processo (`process_loss_percentage`).
4. **Snapshot de Estoques:** Leitura das posições de `tabBin` por armazém e empresa.
5. **Carga de Demandas:** Pedidos de Venda (`Sales Order`), Requisições de Consumo (`Material Request`) e **Demandas Manuais**.
6. **Carga de Entradas Programadas:** Ordens de Compra (`Purchase Order`) e Ordens de Produção (`Work Order`) em andamento.
7. **Ordenação Cronológica:** Montagem do calendário diário do horizonte.
8. **Projeção de Saldos:** Aplicação da equação fundamental:
   $$\text{Saldo Projetado}_t = \text{Saldo Anterior}_{t-1} + \text{Entradas Previstas}_t - \text{Demandas}_t$$
9. **Detecção de Insuficiências:** Identificação de momentos em que $\text{Saldo Projetado} < \text{Estoque de Segurança}$.
10. **Cálculo da Necessidade Líquida:** Determinação do volume estrito necessário para restabelecer o estoque de segurança.
11. **Dimensionamento de Lotes:** Aplicação de Lote Mínimo (`min_order_qty`) e Múltiplos de Abastecimento.
12. **Cálculo Retroativo de Lead Time:** Retroage a data de início da necessidade em dias úteis com base na `Holiday List` (desconsiderando finais de semana e feriados).
13. **Decisão de Abastecimento (Produzir, Comprar ou Transferir):**
    - Se o produto possui BOM ativa $\rightarrow$ Sugestão de **Produção**.
    - Se o produto **não possui estrutura (BOM)** $\rightarrow$ Converte automaticamente para **Compra** via API de compras para não paralisar o atendimento da necessidade.
14. **Sourcing Multiempresa:** Avaliação de saldo disponível em empresas parceiras por ordem de prioridade. Se houver saldo viável, gera sugestão de **Transferência** com desconto do lead time de transporte.
15. **Explosão Multinível de BOM:** Para itens produzidos, gera demandas dependentes para componentes no nível subsequente ($N+1$).
16. **Detecção de Ciclos Circulares:** Rastreamento do stack de chamadas para impedir loops infinitos de recursão ($A \rightarrow B \rightarrow C \rightarrow A$).
17. **Aglutinação por Periodicidade:** Se habilitada, consolida ordens do mesmo produto no mesmo período (Diário, Semanal, Quinzenal ou Mensal), preservando todos os vínculos individuais em `MRP Aglutination Link`.
18. **Gravação das Estruturas e Métricas:** Persistência em lote de resultados, timelines, árvores e logs de auditoria.
19. **Aprovação do Cenário:** Permite que o planejador revise e aprove o cenário.
20. **Efetivação Operacional:** Geração dos documentos definitivos no ERPNext.

---

## 3. Controle Estrito por Ticket de Planejamento

Cada processamento do MRP é registrado sob um **Ticket único e imutável**:

```
[ 1. Simulação ] ➔ [ 2. Calculado ] ➔ [ 3. Em Análise ] ➔ [ 4. Aprovado ] ➔ [ 5. Efetivado ]
```

- **Comparação de Cenários:** O planejador pode criar múltiplos tickets com diferentes parâmetros (ex: Ticket 001 com demanda conservadora, Ticket 002 com demanda agressiva e transferências multiempresa) sem que um cálculo sobrescreva o outro.
- **Proteção Contra Duplicidade:** Um ticket já efetivado é travado para novas efetivações, garantindo integridade fiscal e produtiva.
- **Vínculo Obrigatório:** Todo documento gerado recebe o campo `custom_mrp_ticket`, permitindo navegar do documento até o cenário e vice-versa.

---

## 4. Integração Operacional com o ERPNext (Efetivação)

Ao clicar em **Efetivar Abastecimento** a partir de um ticket aprovado, o sistema gera nativamente:

| Sugestão | Documento Gerado no ERPNext | Regras Aplicadas |
| :--- | :--- | :--- |
| **Produção** | `Work Order` | Cria a Ordem de Produção com item, quantidade, BOM, data de início calculada, data de entrega e vínculo com o Pedido de Venda originador. |
| **Compra** | `Material Request` (Purchase) | Agrupa itens comprados por empresa e data de necessidade para evitar pulverização de requisições. |
| **Transferência** | `Material Request` (Material Transfer) | Respeita a segregação multiempresa do ERPNext: gera a requisição de entrada no depósito de destino e a requisição de expedição no armazém da filial fornecedora, sem erros de validação cross-company. |

---

## 5. Importação e Exportação em Excel Formatado

### Importação de Demanda Manual (Excel)
- Permite subir demandas extraordinárias ou previsões de vendas via planilha `.xlsx`.
- O sistema disponibiliza o botão **`Baixar Modelo Excel (.xlsx)`** com as colunas formatadas:
  - `Código do Item*`
  - `Quantidade*`
  - `Data da Necessidade (DD/MM/AAAA)*`
  - `Depósito`
  - `Observação / Justificativa`
- Ao importar, as linhas são inseridas no Ticket como **`Demanda Manual`** e são preservadas entre os recálculos.

### Exportação Formatada em Modo Tabela (`.xlsx`)
O botão **`Exportar Excel`** gera um arquivo com design corporativo via `openpyxl`:
- **Aba 1 (Necessidades e Sugestões):** Tabela estruturada com código, descrição, datas, demandas, saldos, quantidade sugerida, origem e documento gerado, com cabeçalhos azul-escuro (`#1F4E79`), listras alternadas e números formatados.
- **Aba 2 (Linha do Tempo de Saldos):** Projeção diária do saldo e alertas de ruptura.
- **Aba 3 (Demandas Consideradas):** Detalhamento de todos os pedidos e demandas manuais.

---

## 6. Painel de Controle e Workbench (`mrp_workbench`)

Acessível diretamente em **`dev.erpz.io/desk/mrp_workbench`**:
1. **Cards de Indicadores (KPIs):** Total de Demandas, Sugestões de Produção, Compras, Transferências Multiempresa, Rupturas e Alertas.
2. **Resumo de Necessidades com Links Diretos:** Códigos de Ordens de Produção geradas (ex: `MFG-WO-2026-00001`) e Pedidos de Venda são links clicáveis que abrem o formulário correspondente no ERPNext. O botão **`Abrir OP`** permite abrir a OP existente ou criar uma nova OP pré-preenchida para sugestões pendentes.
3. **Linha do Tempo do Saldo Projetado:** Gráfico interativo via Frappe Charts e tabela diária de evolução de estoque com alertas de ruptura.
4. **Rastreabilidade Hierárquica em Árvore (Tree View):** Navegação encadeada com expansão/recolhimento mostrando:
   `Pedido de Venda ➔ Produto Acabado (OP) ➔ Componente (OP Filha) ➔ Matéria-Prima (Compra / Transferência)`.
5. **Multiempresa e Abastecimento:** Painel de rotas de transferência entre filiais com prazos logísticos.

---

## Instalação e Configuração

```bash
# No diretório do frappe-bench:
bench get-app erpz_mrp https://github.com/andradezdev/erpz_mrp.git
bench --site <seu-site> install-app erpz_mrp
bench --site <seu-site> migrate
```

O ícone do **ERPZ MRP** e os menus da barra lateral são criados automaticamente na interface Desk do Frappe.

---

## Licença
Distribuído sob a licença MIT. Copyright © 2026 ERPZ.
