// Copyright (c) 2026, ERPZ and contributors
// For license information, please see license.txt

function init_mrp_workbench(wrapper) {
	var page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Central de Planejamento MRP"),
		single_column: true
	});

	frappe.mrp_workbench = new MRPWorkbench(page);
}

function show_mrp_workbench(wrapper) {
	if (frappe.mrp_workbench && frappe.route_options && frappe.route_options.ticket) {
		frappe.mrp_workbench.ticket_field.set_value(frappe.route_options.ticket);
		frappe.route_options = null;
	}
}

frappe.provide("frappe.pages");
frappe.pages["mrp-workbench"] = frappe.pages["mrp-workbench"] || {};
frappe.pages["mrp-workbench"].on_page_load = init_mrp_workbench;
frappe.pages["mrp-workbench"].on_page_show = show_mrp_workbench;

frappe.pages["mrp_workbench"] = frappe.pages["mrp_workbench"] || {};
frappe.pages["mrp_workbench"].on_page_load = init_mrp_workbench;
frappe.pages["mrp_workbench"].on_page_show = show_mrp_workbench;

class MRPWorkbench {
	constructor(page) {
		this.page = page;
		this.current_ticket = null;
		this.active_tab = "summary";
		this.chart = null;
		this.selected_results = new Set();
		this.init();
	}

	init() {
		this.setup_header();
		this.render_layout();
		this.bind_events();
		this.load_initial_ticket();
	}

	setup_header() {
		const me = this;

		// Ticket selector
		this.ticket_field = this.page.add_field({
			fieldname: "mrp_ticket",
			label: __("Ticket MRP"),
			fieldtype: "Link",
			options: "MRP Ticket",
			change() {
				const val = me.ticket_field.get_value();
				if (val && val !== me.current_ticket) {
					me.current_ticket = val;
					me.reload_all();
				}
			}
		});

		// Button: Novo Ticket
		this.page.add_button(__("Novo Ticket"), function() {
			frappe.new_doc("MRP Ticket");
		});

		// Button: Executar Motor (Calcular)
		this.btn_calculate = this.page.add_button(__("Calcular MRP"), function() {
			me.run_calculation();
		}, { icon: "refresh" });

		// Button: Aprovar Cenário
		this.btn_approve = this.page.add_button(__("Aprovar Cenário"), function() {
			me.approve_scenario();
		});

		// Button: Efetivar Documentos
		this.btn_execute = this.page.add_button(__("Efetivar Abastecimento"), function() {
			me.execute_scenario();
		}, { btn_class: "btn-danger" });
	}

	render_layout() {
		this.$container = $(`
			<div class="mrp-workbench">
				<!-- Stepper Card -->
				<div class="mrp-header-card">
					<div class="d-flex justify-content-between align-items-center">
						<div>
							<h4 class="m-0 font-weight-bold" id="mrp-ticket-title">Selecione um Ticket MRP</h4>
							<small class="text-muted" id="mrp-ticket-subtitle">Planejamento de Necessidades de Materiais Multiempresa</small>
						</div>
						<div id="mrp-status-badge"></div>
					</div>
					<div class="mrp-stepper" id="mrp-stepper">
						<div class="mrp-step" data-step="1"><div class="mrp-step-circle">1</div>Simulação</div>
						<div class="mrp-step-line"></div>
						<div class="mrp-step" data-step="2"><div class="mrp-step-circle">2</div>Calculado</div>
						<div class="mrp-step-line"></div>
						<div class="mrp-step" data-step="3"><div class="mrp-step-circle">3</div>Em Análise</div>
						<div class="mrp-step-line"></div>
						<div class="mrp-step" data-step="4"><div class="mrp-step-circle">4</div>Aprovado</div>
						<div class="mrp-step-line"></div>
						<div class="mrp-step" data-step="5"><div class="mrp-step-circle">5</div>Efetivado</div>
					</div>
				</div>

				<!-- KPI Cards -->
				<div class="mrp-kpi-grid">
					<div class="mrp-kpi-card">
						<span class="mrp-kpi-title">Total Demandas</span>
						<span class="mrp-kpi-val" id="kpi-demands">-</span>
					</div>
					<div class="mrp-kpi-card">
						<span class="mrp-kpi-title">Sugestões de Produção (OP)</span>
						<span class="mrp-kpi-val text-primary" id="kpi-produced">-</span>
					</div>
					<div class="mrp-kpi-card">
						<span class="mrp-kpi-title">Sugestões de Compra (OC/SC)</span>
						<span class="mrp-kpi-val text-warning" id="kpi-purchased">-</span>
					</div>
					<div class="mrp-kpi-card">
						<span class="mrp-kpi-title">Transferências Multiempresa</span>
						<span class="mrp-kpi-val text-purple" id="kpi-transferred">-</span>
					</div>
					<div class="mrp-kpi-card">
						<span class="mrp-kpi-title">Pontos de Ruptura / Falta</span>
						<span class="mrp-kpi-val text-danger" id="kpi-shortages">-</span>
					</div>
					<div class="mrp-kpi-card">
						<span class="mrp-kpi-title">Inconsistências / Alertas</span>
						<span class="mrp-kpi-val text-danger" id="kpi-inconsistencies">-</span>
					</div>
				</div>

				<!-- Tabs Container -->
				<div class="mrp-tabs-container">
					<div class="mrp-nav-tabs">
						<div class="mrp-nav-tab active" data-tab="summary">
							<i class="octicon octicon-list-unordered"></i> Resumo de Necessidades
						</div>
						<div class="mrp-nav-tab" data-tab="timeline">
							<i class="octicon octicon-graph"></i> Linha do Tempo & Saldo Projetado
						</div>
						<div class="mrp-nav-tab" data-tab="traceability">
							<i class="octicon octicon-git-branch"></i> Rastreabilidade Hierárquica
						</div>
						<div class="mrp-nav-tab" data-tab="multicompany">
							<i class="octicon octicon-organization"></i> Multiempresa & Abastecimento
						</div>
					</div>

					<div class="mrp-tab-content">
						<!-- Tab 1: Summary -->
						<div class="mrp-tab-pane" id="pane-summary">
							<div class="mrp-filter-bar">
								<div class="flex-grow-1" style="max-width: 250px;">
									<input type="text" class="form-control form-control-sm" id="filter-search-item" placeholder="Filtrar por produto ou código...">
								</div>
								<div>
									<select class="form-control form-control-sm" id="filter-supply-type">
										<option value="">Todos os Tipos</option>
										<option value="Produção">Produção</option>
										<option value="Compra">Compra</option>
										<option value="Transferência">Transferência</option>
									</select>
								</div>
								<div>
									<select class="form-control form-control-sm" id="filter-status">
										<option value="">Todas as Situações</option>
										<option value="Pendente">Pendente</option>
										<option value="Aprovado">Aprovado</option>
										<option value="Efetivado">Efetivado</option>
										<option value="Atrasado">Atrasado</option>
									</select>
								</div>
								<div class="ml-auto d-flex gap-2">
									<button class="btn btn-sm btn-primary" id="btn-import-demand">
										<i class="octicon octicon-upload"></i> Importar Demanda (Excel)
									</button>
									<button class="btn btn-sm btn-default" id="btn-export-excel">
										<i class="octicon octicon-file"></i> Exportar Excel
									</button>
								</div>
							</div>

							<div class="mrp-table-wrap">
								<table class="mrp-table" id="mrp-summary-table">
									<thead>
										<tr>
											<th width="30"><input type="checkbox" id="check-all-results"></th>
											<th>Produto Atual</th>
											<th>Produto Originador</th>
											<th>Origem / Demanda</th>
											<th>Doc Gerado / OP</th>
											<th>Data Necessidade</th>
											<th>Data Abastecimento</th>
											<th>Demanda</th>
											<th>Saldo Projetado</th>
											<th>Sugerida</th>
											<th>Abastecimento</th>
											<th>Empresa Destino</th>
											<th>Situação</th>
											<th style="min-width: 140px;">Ações</th>
										</tr>
									</thead>
									<tbody id="mrp-summary-tbody">
										<tr><td colspan="14" class="text-center text-muted p-4">Selecione ou calcule um Ticket MRP.</td></tr>
									</tbody>
								</table>
							</div>
						</div>

						<!-- Tab 2: Timeline -->
						<div class="mrp-tab-pane d-none" id="pane-timeline">
							<div class="mrp-filter-bar">
								<div style="min-width: 280px;" id="timeline-item-select-wrap"></div>
								<button class="btn btn-sm btn-primary" id="btn-load-timeline">Atualizar Gráfico</button>
							</div>
							<div id="mrp-chart-container" style="min-height: 280px; margin-bottom: 25px;"></div>
							<h6 class="font-weight-bold mb-3">Movimentações Cronológicas Diárias</h6>
							<div class="mrp-table-wrap">
								<table class="mrp-table" id="mrp-timeline-table">
									<thead>
										<tr>
											<th>Data</th>
											<th>Item</th>
											<th>Saldo Inicial</th>
											<th>Entradas (Previstas + Sugeridas)</th>
											<th>Saídas (Demandas)</th>
											<th>Saldo Projetado</th>
											<th>Estoque Mínimo</th>
											<th>Ponto Pedido + Seg</th>
											<th>Falta / Ruptura</th>
											<th>Situação</th>
										</tr>
									</thead>
									<tbody id="mrp-timeline-tbody"></tbody>
								</table>
							</div>
						</div>

						<!-- Tab 3: Traceability -->
						<div class="mrp-tab-pane d-none" id="pane-traceability">
							<p class="text-muted small">Navegação encadeada da Demanda (Pedido de Venda) até as OPs filhas, Requisições de Compra e Transferências:</p>
							<div id="mrp-traceability-tree" class="p-2"></div>
						</div>

						<!-- Tab 4: Multi-company -->
						<div class="mrp-tab-pane d-none" id="pane-multicompany">
							<h6 class="font-weight-bold mb-2">Transferências e Abastecimento entre Empresas do Grupo</h6>
							<p class="text-muted small">Cadeias de abastecimento intercompany com lead times calculados retroativamente.</p>
							<div class="mrp-table-wrap">
								<table class="mrp-table">
									<thead>
										<tr>
											<th>Item</th>
											<th>Empresa Origem</th>
											<th>Depósito Fornecedor</th>
											<th>Empresa Destino</th>
											<th>Depósito Destino</th>
											<th>Quantidade</th>
											<th>Lead Time Transferência</th>
											<th>Data Transferência</th>
											<th>Data Necessidade</th>
											<th>Justificativa</th>
										</tr>
									</thead>
									<tbody id="mrp-multicompany-tbody"></tbody>
								</table>
							</div>
						</div>
					</div>
				</div>
			</div>
		`).appendTo(this.page.main);
	}

	bind_events() {
		const me = this;

		// Tab switching
		this.$container.find(".mrp-nav-tab").on("click", function() {
			const tab = $(this).data("tab");
			me.$container.find(".mrp-nav-tab").removeClass("active");
			$(this).addClass("active");
			me.$container.find(".mrp-tab-pane").addClass("d-none");
			me.$container.find(`#pane-${tab}`).removeClass("d-none");
			me.active_tab = tab;

			if (tab === "timeline") {
				me.on_timeline_tab_opened();
			} else if (tab === "traceability") {
				me.load_traceability_tree();
			} else if (tab === "multicompany") {
				me.load_multicompany_grid();
			}
		});

		// Filters
		this.$container.find("#filter-search-item, #filter-supply-type, #filter-status").on("change keyup", function() {
			me.load_summary_table();
		});

		// Select All Checkbox
		this.$container.find("#check-all-results").on("change", function() {
			const checked = $(this).is(":checked");
			me.$container.find(".mrp-row-check").prop("checked", checked);
			me.update_selected_results();
		});

		// Timeline button
		this.$container.find("#btn-load-timeline").on("click", function() {
			const item_code = me.timeline_item_select ? me.timeline_item_select.get_value() : null;
			if (item_code) {
				me.render_timeline_chart();
			} else {
				frappe.confirm(
					__("Nenhum produto foi selecionado. Deseja processar a visualização geral consolidada de todos os produtos?<br><br><span class='text-muted small'>Pela quantidade de registros do planejamento, o processamento geral pode levar alguns instantes.</span>"),
					() => {
						me.render_timeline_chart(true);
					}
				);
			}
		});

		// Import Excel button
		this.$container.find("#btn-import-demand").on("click", function() {
			me.show_import_demand_dialog();
		});

		// Export Excel
		this.$container.find("#btn-export-excel").on("click", function() {
			me.export_summary_data();
		});
	}

	load_initial_ticket() {
		const me = this;
		frappe.db.get_list("MRP Ticket", {
			order_by: "creation desc",
			limit: 1
		}).then(records => {
			if (records && records.length > 0) {
				me.ticket_field.set_value(records[0].name);
			}
		});
	}

	reload_all() {
		if (!this.current_ticket) return;
		this.load_metrics();
		this.load_summary_table();
		this.load_timeline_items();
	}

	load_metrics() {
		const me = this;
		frappe.call({
			method: "erpz_mrp.api.get_ticket_dashboard_metrics",
			args: { ticket_name: this.current_ticket },
			callback: function(r) {
				if (r.message) {
					const m = r.message;
					$("#mrp-ticket-title").text(`Ticket: ${me.current_ticket}`);
					$("#mrp-ticket-subtitle").text(`Situação: ${m.status} | Tempo: ${m.execution_time}s`);
					$("#kpi-demands").text(m.total_demands);
					$("#kpi-produced").text(m.total_produced);
					$("#kpi-purchased").text(m.total_purchased);
					$("#kpi-transferred").text(m.total_transferred);
					$("#kpi-shortages").text(m.total_shortages);
					$("#kpi-inconsistencies").text(m.total_inconsistencies);

					me.update_stepper(m.status);
					me.update_action_buttons(m.status);
				}
			}
		});
	}

	update_action_buttons(status) {
		if (status === "Efetivado") {
			this.btn_execute.show().prop("disabled", true).addClass("disabled").text(__("Efetivado (Concluído)"));
			this.btn_approve.hide();
		} else if (status === "Aprovado") {
			this.btn_execute.show().prop("disabled", false).removeClass("disabled").text(__("Efetivar Abastecimento"));
			this.btn_approve.hide();
		} else if (["Calculado", "Calculado (Simulação)", "Em Análise", "Com Inconsistências"].includes(status)) {
			this.btn_approve.show().prop("disabled", false).removeClass("disabled");
			this.btn_execute.show().prop("disabled", true).addClass("disabled").text(__("Efetivar Abastecimento"));
		} else {
			this.btn_approve.hide();
			this.btn_execute.hide();
		}
	}

	update_stepper(status) {
		const stepMap = {
			"Em Preparação": 1,
			"Processando": 1,
			"Calculado": 2,
			"Calculado (Simulação)": 2,
			"Em Análise": 3,
			"Aprovado": 4,
			"Efetivado": 5
		};
		const activeStep = stepMap[status] || 1;
		$(".mrp-step").each(function() {
			const s = parseInt($(this).data("step"));
			$(this).removeClass("active completed");
			if (s < activeStep) {
				$(this).addClass("completed");
			} else if (s === activeStep) {
				$(this).addClass("active");
			}
		});
	}

	load_summary_table() {
		const me = this;
		const search = $("#filter-search-item").val();
		const supply_type = $("#filter-supply-type").val();
		const status = $("#filter-status").val();

		frappe.call({
			method: "erpz_mrp.api.get_mrp_summary",
			args: {
				ticket_name: this.current_ticket,
				item_code: search,
				supply_type: supply_type,
				status: status,
				start: 0,
				page_length: 100
			},
			callback: function(r) {
				const tbody = $("#mrp-summary-tbody").empty();
				if (r.message && r.message.items && r.message.items.length > 0) {
					r.message.items.forEach(it => {
						const supplyBadge = it.supply_type === "Produção" ? "mrp-badge-produce" :
							(it.supply_type === "Compra" ? "mrp-badge-purchase" : "mrp-badge-transfer");
						const statusBadge = `mrp-badge-${(it.status || "pendente").toLowerCase()}`;

						// Origin doc link
						let originHtml = "-";
						if (it.origin_name) {
							originHtml = `<a href="#" class="btn-open-doc text-dark font-weight-bold" data-doctype="${it.origin_doctype || 'Sales Order'}" data-docname="${it.origin_name}" title="Abrir ${it.origin_doctype || 'Origem'} ${it.origin_name}"><i class="octicon octicon-link-external mr-1 text-muted"></i>${it.origin_name}</a>`;
						}

						// Generated doc (Work Order / Material Request / Stock Entry)
						let generatedHtml = `<span class="text-muted small">-</span>`;
						if (it.generated_docname) {
							generatedHtml = `<a href="#" class="btn-open-doc text-primary font-weight-bold" data-doctype="${it.generated_doctype || 'Work Order'}" data-docname="${it.generated_docname}" title="Abrir ${it.generated_doctype || 'OP'} ${it.generated_docname}"><i class="octicon octicon-link-external mr-1"></i><b>${it.generated_docname}</b></a>`;
						} else if (it.supply_type === "Produção") {
							generatedHtml = `<span class="badge badge-light text-muted">Pendente (OP)</span>`;
						}

						// Actions
						let opActionBtn = "";
						if (it.generated_docname) {
							opActionBtn = `<button class="btn btn-xs btn-primary btn-open-doc mr-1" data-doctype="${it.generated_doctype || 'Work Order'}" data-docname="${it.generated_docname}" title="Abrir ${it.generated_doctype} ${it.generated_docname}"><i class="octicon octicon-link-external"></i> Abrir OP</button>`;
						} else if (it.supply_type === "Produção") {
							opActionBtn = `<button class="btn btn-xs btn-default btn-create-op mr-1" data-item="${it.item_code}" data-qty="${it.suggested_qty}" data-date="${it.need_date}" data-supply="${it.supply_date}" data-bom="${it.bom_no || ''}" data-origin="${it.origin_name || ''}" data-company="${it.company}" title="Criar / Abrir Ordem de Produção"><i class="octicon octicon-plus"></i> Abrir OP</button>`;
						}

						const row = $(`
							<tr>
								<td><input type="checkbox" class="mrp-row-check" data-id="${it.name}"></td>
								<td><strong>${it.item_code}</strong><br><small class="text-muted">${it.item_name || ''}</small></td>
								<td>${it.origin_item || '-'}</td>
								<td>${originHtml}</td>
								<td>${generatedHtml}</td>
								<td>${frappe.datetime.str_to_user(it.need_date)}</td>
								<td>${frappe.datetime.str_to_user(it.supply_date)}</td>
								<td>${it.gross_demand}</td>
								<td>${it.projected_balance}</td>
								<td><strong>${it.suggested_qty}</strong></td>
								<td><span class="mrp-badge ${supplyBadge}">${it.supply_type}</span></td>
								<td>${it.company}</td>
								<td><span class="mrp-badge ${statusBadge}">${it.status}</span></td>
								<td class="d-flex align-items-center">
									${opActionBtn}
									<button class="btn btn-xs btn-default btn-view-timeline" data-item="${it.item_code}" title="Ver Timeline">
										<i class="octicon octicon-graph"></i>
									</button>
								</td>
							</tr>
						`).appendTo(tbody);

						row.find(".btn-view-timeline").on("click", function() {
							const item = $(this).data("item");
							me.active_tab = "timeline";
							$(".mrp-nav-tab[data-tab='timeline']").click();
							if (me.timeline_item_select) {
								me.timeline_item_select.set_value(item);
							}
						});
					});

					tbody.off("click", ".btn-open-doc").on("click", ".btn-open-doc", function(e) {
						e.preventDefault();
						const doctype = $(this).data("doctype");
						const docname = $(this).data("docname");
						if (doctype && docname) {
							frappe.set_route("Form", doctype, docname);
						}
					});

					tbody.off("click", ".btn-create-op").on("click", ".btn-create-op", function(e) {
						e.preventDefault();
						const item = $(this).data("item");
						const qty = $(this).data("qty");
						const supply_date = $(this).data("supply");
						const need_date = $(this).data("date");
						const bom = $(this).data("bom");
						const origin = $(this).data("origin");
						const comp = $(this).data("company");
						frappe.new_doc("Work Order", {
							production_item: item,
							bom_no: bom,
							qty: qty,
							planned_start_date: supply_date,
							expected_delivery_date: need_date,
							company: comp,
							custom_mrp_ticket: me.current_ticket,
							custom_mrp_origin_demand: origin
						});
					});
				} else {
					tbody.append(`<tr><td colspan="13" class="text-center text-muted p-4">Nenhum resultado encontrado.</td></tr>`);
				}
			}
		});
	}

	on_timeline_tab_opened() {
		const me = this;
		const item_code = this.timeline_item_select ? this.timeline_item_select.get_value() : null;

		if (item_code) {
			this.render_timeline_chart();
		} else {
			frappe.confirm(
				__("Deseja processar a Linha do Tempo Geral de todos os produtos?<br><br><span class='text-muted small'>Pela quantidade de registros do planejamento, o processamento geral pode levar alguns instantes e exigir mais processamento do navegador.<br><br><b>Dica:</b> Para maior rapidez e análise individual, você pode cancelar e selecionar um produto específico.</span>"),
				() => {
					me.render_timeline_chart(true);
				},
				() => {
					me.show_select_item_placeholder();
				}
			);
		}
	}

	show_select_item_placeholder() {
		const me = this;
		if (this.chart) {
			this.chart.destroy();
			this.chart = null;
		}
		$("#mrp-chart-container").html(`
			<div class="text-center p-5 text-muted bg-light rounded border" style="margin: 20px 0;">
				<i class="octicon octicon-search text-primary" style="font-size: 32px;"></i>
				<h5 class="mt-3 text-dark font-weight-bold">Selecione um Produto para Visualizar</h5>
				<p class="text-muted mb-3" style="max-width: 500px; margin: 0 auto;">
					Utilize o campo acima para buscar qualquer produto e visualizar seu gráfico de saldo projetado, pontos de pedido e rupturas diárias.
				</p>
				<button class="btn btn-sm btn-outline-secondary" id="btn-load-general-confirm">
					<i class="octicon octicon-graph mr-1"></i> Carregar Visão Geral Consolidada de Todos os Produtos
				</button>
			</div>
		`);
		$("#mrp-timeline-tbody").empty();
		$("#btn-load-general-confirm").on("click", function() {
			frappe.confirm(
				__("Deseja realmente carregar a Linha do Tempo Geral consolidada de todos os produtos?"),
				() => {
					me.render_timeline_chart(true);
				}
			);
		});
	}

	load_timeline_items() {
		const me = this;
		$("#timeline-item-select-wrap").empty();
		this.timeline_item_select = frappe.ui.form.make_control({
			parent: $("#timeline-item-select-wrap")[0],
			df: {
				fieldtype: "Link",
				fieldname: "timeline_item",
				options: "Item",
				label: __("Selecionar Produto para Visualizar Gráfico de Saldo"),
				change() {
					const val = me.timeline_item_select.get_value();
					if (val) {
						me.render_timeline_chart();
					} else {
						me.show_select_item_placeholder();
					}
				}
			},
			render_input: true
		});
	}

	render_timeline_chart(force_general = false) {
		const me = this;
		const item_code = this.timeline_item_select ? this.timeline_item_select.get_value() : null;

		if (!item_code && !force_general) {
			this.show_select_item_placeholder();
			return;
		}

		$("#mrp-chart-container").html(`
			<div class="text-center p-5 text-muted bg-light rounded border" style="margin: 20px 0;">
				<div class="spinner-border text-primary mb-2" role="status"></div>
				<div class="font-weight-bold">Carregando dados da linha do tempo...</div>
				<div class="small text-muted mt-1">Processando posições de saldo projetado e demandas</div>
			</div>
		`);

		frappe.call({
			method: "erpz_mrp.api.get_timeline_data",
			args: {
				ticket_name: this.current_ticket,
				item_code: item_code
			},
			callback: function(r) {
				if (r.message && r.message.dates && r.message.dates.length > 0) {
					const data = r.message;
					const isGeneral = !!data.is_general;

					const chartTitle = isGeneral 
						? "Visão Geral Consolidada: Saldo Projetado, Entradas e Demandas Totais" 
						: `Evolução Cronológica do Estoque: ${item_code}`;

					const chartData = {
						labels: data.dates.map(d => frappe.datetime.str_to_user(d)),
						datasets: [
							{ name: "Saldo Projetado", values: data.projected_balance, chartType: "line" },
							{ name: "Estoque Mínimo", values: data.min_stock || [], chartType: "line" },
							{ name: "Ponto Pedido + Seg", values: data.critical_threshold || [], chartType: "line" },
							{ name: "Entradas Totais", values: data.inflows, chartType: "bar" },
							{ name: "Demandas / Saídas", values: data.outflows, chartType: "bar" }
						]
					};

					if (me.chart) {
						me.chart.destroy();
					}
					me.chart = new frappe.Chart("#mrp-chart-container", {
						title: chartTitle,
						data: chartData,
						type: "axis-mixed",
						height: 280,
						colors: ["#2490ef", "#e53e3e", "#ed8936", "#38a169", "#718096"]
					});

					// Render Table rows
					const tbody = $("#mrp-timeline-tbody").empty();
					if (isGeneral) {
						tbody.append(`
							<tr class="bg-light">
								<td colspan="10" class="text-muted small py-2 px-3">
									<i class="octicon octicon-info mr-1 text-primary"></i> <b>Visão Geral Consolidada:</b> O gráfico acima exibe a evolução diária agregada de todo o planejamento. Na grade abaixo estão listadas as ocorrências com déficit ou movimentação diária. Selecione um item específico no campo acima para visualizar a grade cronológica detalhada de um produto individual.
								</td>
							</tr>
						`);
					}

					(data.raw_rows || []).forEach(rw => {
						let shortageBadge = `<span class="badge badge-success">Normal</span>`;
						if (rw.has_shortage) {
							const typeText = rw.shortage_type || "Ruptura";
							shortageBadge = `<span class="badge badge-danger" title="Déficit: ${rw.shortage_qty}">${typeText}</span>`;
						}

						tbody.append(`
							<tr>
								<td>${frappe.datetime.str_to_user(rw.timeline_date)}</td>
								<td><strong>${rw.item_code}</strong> <small class="text-muted">${rw.item_name || ''}</small></td>
								<td>${rw.initial_balance}</td>
								<td>${rw.inflows + rw.suggested_inflow}</td>
								<td>${rw.outflows}</td>
								<td class="${rw.has_shortage ? 'text-danger font-weight-bold' : ''}">${rw.projected_balance}</td>
								<td>${rw.min_stock || 0}</td>
								<td>${rw.critical_threshold || rw.safety_stock || 0}</td>
								<td>${rw.shortage_qty > 0 ? rw.shortage_qty : '-'}</td>
								<td>${shortageBadge}</td>
							</tr>
						`);
					});
				} else {
					me.show_select_item_placeholder();
				}
			}
		});
	}

	load_traceability_tree() {
		const me = this;
		frappe.call({
			method: "erpz_mrp.api.get_traceability_tree",
			args: { ticket_name: this.current_ticket },
			callback: function(r) {
				const container = $("#mrp-traceability-tree").empty();
				if (r.message && r.message.length > 0) {
					$(`
						<div class="d-flex justify-content-between align-items-center mb-3 p-2 bg-light rounded border">
							<div class="small text-muted">
								<b>Árvore Genealógica de Rastreabilidade Multinível</b> (Pedido de Venda &rarr; Produto Acabado &rarr; Subconjuntos &rarr; Matérias-Primas)
							</div>
							<div class="d-flex gap-2">
								<button class="btn btn-xs btn-default mr-1" id="mrp-tree-expand-all"><i class="octicon octicon-chevron-down mr-1"></i> Expandir Todos os Níveis</button>
								<button class="btn btn-xs btn-default" id="mrp-tree-collapse-all"><i class="octicon octicon-chevron-right mr-1"></i> Recolher Todos</button>
							</div>
						</div>
					`).appendTo(container);

					$("#mrp-tree-expand-all").on("click", function() {
						container.find(".mrp-tree-children").show();
						container.find(".mrp-tree-toggle i").removeClass("octicon-chevron-right").addClass("octicon-chevron-down");
					});
					$("#mrp-tree-collapse-all").on("click", function() {
						container.find(".mrp-tree-children").hide();
						container.find(".mrp-tree-toggle i").removeClass("octicon-chevron-down").addClass("octicon-chevron-right");
					});

					const treeContent = $(`<div class="mrp-tree-content"></div>`).appendTo(container);
					me.render_tree_nodes(r.message, treeContent);
				} else {
					container.html(`<div class="text-muted p-3">Nenhum registro de rastreabilidade encontrado.</div>`);
				}
			}
		});
	}

	render_tree_nodes(nodes, parentEl) {
		const me = this;
		nodes.forEach(node => {
			if (node.is_root_demand) {
				const rootCard = $(`
					<div class="mrp-tree-root mb-3">
						<div class="mrp-tree-root-header p-2 d-flex align-items-center" style="cursor: pointer; background: #f1f5f9; border-radius: 6px; border: 1px solid #cbd5e1;">
							<span class="mrp-tree-toggle mr-2"><i class="octicon octicon-chevron-down"></i></span>
							<i class="octicon octicon-file-text text-primary mr-2"></i>
							<strong class="text-primary" style="font-size: 13px;">${node.demand_source_doctype}: ${node.demand_source_name}</strong>
							<span class="badge badge-info ml-2">${(node.children || []).length} Produto(s) Raiz</span>
						</div>
						<div class="mrp-tree-children mt-2"></div>
					</div>
				`).appendTo(parentEl);

				rootCard.find("> .mrp-tree-root-header").on("click", function(e) {
					const ch = rootCard.find("> .mrp-tree-children");
					const icon = $(this).find(".mrp-tree-toggle i");
					ch.slideToggle(150);
					icon.toggleClass("octicon-chevron-down octicon-chevron-right");
				});

				if (node.children && node.children.length > 0) {
					me.render_tree_nodes(node.children, rootCard.find("> .mrp-tree-children"));
				}
			} else {
				const typeBadge = node.supply_type === "Produção" ? "mrp-badge-produce" :
					(node.supply_type === "Compra" ? "mrp-badge-purchase" : "mrp-badge-transfer");
				const hasChildren = node.children && node.children.length > 0;
				const toggleIcon = hasChildren ? `<span class="mrp-tree-toggle mr-2" style="cursor: pointer;"><i class="octicon octicon-chevron-down"></i></span>` : `<span class="mr-3"></span>`;
				const countBadge = hasChildren ? `<span class="badge badge-light border text-muted ml-2" style="font-size: 10px;">${node.children.length} subcomponentes</span>` : ``;
				const lvlStyle = node.bom_level === 0 ? "background: #dbeafe; color: #1e40af; border: 1px solid #bfdbfe;" :
					(node.bom_level === 1 ? "background: #e0e7ff; color: #3730a3; border: 1px solid #c7d2fe;" :
					(node.bom_level === 2 ? "background: #ede9fe; color: #5b21b6; border: 1px solid #ddd6fe;" :
					"background: #f1f5f9; color: #475569; border: 1px solid #e2e8f0;"));

				const itemNode = $(`
					<div class="mrp-tree-node-wrap mb-2">
						<div class="mrp-tree-card d-flex align-items-center justify-content-between p-2" style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 6px; cursor: ${hasChildren ? 'pointer' : 'default'}; box-shadow: 0 1px 2px rgba(0,0,0,0.03);">
							<div class="d-flex align-items-center flex-grow-1">
								${toggleIcon}
								<div>
									<span class="badge mr-2" style="font-size: 11px; font-weight: 700; ${lvlStyle}">Nível ${node.bom_level}</span><strong style="color: #1e293b;">${node.child_item}</strong> <small class="text-muted">${node.item_name || ''}</small>
									${countBadge}
									<div class="small text-muted mt-1">
										<span>Qtd: <b style="color: #0f172a;">${node.allocated_qty}</b></span> &bull;
										<span>Início: ${frappe.datetime.str_to_user(node.planned_start_date)}</span> &bull;
										<span>Necessidade: ${frappe.datetime.str_to_user(node.need_date)}</span>
									</div>
								</div>
							</div>
							<div class="d-flex align-items-center gap-2">
								<span class="mrp-badge ${typeBadge}">${node.supply_type}</span>
								<span class="badge badge-light">${node.to_company}</span>
								<span class="badge badge-secondary">${node.target_doctype}: ${node.target_docname || 'Sugestão'}</span>
							</div>
						</div>
						<div class="mrp-tree-children" style="margin-left: 20px; padding-left: 12px; border-left: 2px solid #cbd5e1; margin-top: 6px;"></div>
					</div>
				`).appendTo(parentEl);

				if (hasChildren) {
					itemNode.find("> .mrp-tree-card").on("click", function(e) {
						const ch = itemNode.find("> .mrp-tree-children");
						const icon = $(this).find(".mrp-tree-toggle i");
						ch.slideToggle(150);
						icon.toggleClass("octicon-chevron-down octicon-chevron-right");
					});

					me.render_tree_nodes(node.children, itemNode.find("> .mrp-tree-children"));
				}
			}
		});
	}

	load_multicompany_grid() {
		frappe.db.get_list("MRP Result", {
			filters: { mrp_ticket: this.current_ticket, supply_type: "Transferência" },
			fields: ["item_code", "from_company", "from_warehouse", "company", "warehouse", "suggested_qty", "lead_time_days", "supply_date", "need_date", "situation"]
		}).then(records => {
			const tbody = $("#mrp-multicompany-tbody").empty();
			if (records && records.length > 0) {
				records.forEach(r => {
					tbody.append(`
						<tr>
							<td><strong>${r.item_code}</strong></td>
							<td>${r.from_company}</td>
							<td>${r.from_warehouse || '-'}</td>
							<td>${r.company}</td>
							<td>${r.warehouse || '-'}</td>
							<td><strong>${r.suggested_qty}</strong></td>
							<td>${r.lead_time_days} dias</td>
							<td>${frappe.datetime.str_to_user(r.supply_date)}</td>
							<td>${frappe.datetime.str_to_user(r.need_date)}</td>
							<td><small class="text-muted">${r.situation}</small></td>
						</tr>
					`);
				});
			} else {
				tbody.append(`<tr><td colspan="10" class="text-center text-muted p-4">Nenhuma transferência multiempresa sugerida para este ticket.</td></tr>`);
			}
		});
	}

	update_selected_results() {
		const me = this;
		this.selected_results.clear();
		$(".mrp-row-check:checked").each(function() {
			me.selected_results.add($(this).data("id"));
		});
	}

	run_calculation() {
		const me = this;
		if (!this.current_ticket) return;

		frappe.confirm(__("Deseja iniciar o cálculo do MRP para o cenário selecionado?"), function() {
			frappe.call({
				method: "erpz_mrp.api.run_mrp_calculation",
				args: { ticket_name: me.current_ticket },
				freeze: true,
				freeze_message: __("Processando motor de cálculo MRP..."),
				callback: function(r) {
					frappe.show_alert({ message: __("Cálculo concluído com sucesso!"), indicator: "green" });
					me.reload_all();
				}
			});
		});
	}

	approve_scenario() {
		const me = this;
		if (!this.current_ticket) return;

		frappe.call({
			method: "erpz_mrp.api.approve_ticket",
			args: { ticket_name: me.current_ticket },
			callback: function(r) {
				frappe.show_alert({ message: __("Cenário Aprovado! Pronto para efetivação."), indicator: "green" });
				me.reload_all();
			}
		});
	}

	execute_scenario() {
		const me = this;
		if (!this.current_ticket) return;

		frappe.confirm(__("Deseja gerar os documentos definitivos no ERPNext (Work Orders, Material Requests, Stock Entries)?"), function() {
			frappe.call({
				method: "erpz_mrp.api.execute_ticket",
				args: { ticket_name: me.current_ticket },
				freeze: true,
				freeze_message: __("Gerando ordens no ERPNext..."),
				callback: function(r) {
					if (r.message && r.message.status === "already_executed") {
						frappe.msgprint({
							title: __("Ticket Já Efetivado"),
							indicator: "blue",
							message: __("Todos os documentos deste Ticket já foram efetivados e constam na tabela abaixo.")
						});
					} else if (r.message && r.message.created_count > 0) {
						frappe.msgprint({
							title: __("Efetivação Concluída"),
							indicator: "green",
							message: __("Foram gerados {0} documentos no ERPNext vinculados a este Ticket.", [r.message.created_count])
						});
					}
					me.reload_all();
				}
			});
		});
	}

	show_import_demand_dialog() {
		const me = this;
		if (!this.current_ticket) {
			frappe.msgprint(__("Selecione um Ticket MRP primeiro."));
			return;
		}

		let d = new frappe.ui.Dialog({
			title: __("Importar Demanda Manual (Excel)"),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "instructions",
					options: `
						<div class="alert alert-info small mb-3">
							<b>Instruções de Importação:</b><br>
							Baixe o modelo padrão em Excel, preencha as colunas e faça o upload do arquivo. As demandas serão incorporadas como <b>Demanda Manual</b> neste Ticket.
							<div class="mt-2">
								<a href="/api/method/erpz_mrp.api.download_manual_demand_template" class="btn btn-xs btn-primary" target="_blank">
									<i class="octicon octicon-cloud-download"></i> Baixar Modelo Excel (.xlsx)
								</a>
							</div>
						</div>
					`
				},
				{
					label: __("Arquivo Excel (.xlsx)"),
					fieldname: "excel_file",
					fieldtype: "Attach",
					reqd: 1
				}
			],
			primary_action_label: __("Importar e Processar"),
			primary_action(values) {
				d.hide();
				frappe.show_alert({ message: __("Importando demandas manuais..."), indicator: "blue" });
				frappe.call({
					method: "erpz_mrp.api.import_manual_demands",
					args: {
						ticket_name: me.current_ticket,
						file_url: values.excel_file
					},
					freeze: true,
					freeze_message: __("Processando arquivo Excel e inserindo demandas..."),
					callback: function(r) {
						if (r.message && r.message.success) {
							frappe.msgprint({
								title: __("Importação Concluída"),
								indicator: "green",
								message: __("Foram importadas {0} linhas de demanda manual com sucesso!<br>Clique em <b>Calcular MRP</b> para recalcular o planejamento com estas demandas.", [r.message.imported_count])
							});
							me.reload_all();
						}
					}
				});
			}
		});
		d.show();
	}

	export_summary_data() {
		const me = this;
		if (!this.current_ticket) return;
		window.open(`/api/method/erpz_mrp.api.export_mrp_excel?ticket_name=${me.current_ticket}`);
	}
}
