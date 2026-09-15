// Copyright (c) 2026, ERPZ and contributors
// For license information, please see license.txt

frappe.ui.form.on("MRP Ticket", {
	refresh(frm) {
		// Custom status indicators
		frm.page.set_indicator(frm.doc.status, get_status_color(frm.doc.status));

		// Button: Abrir Painel Interativo
		frm.add_custom_button(__("Abrir Painel MRP"), function() {
			frappe.set_route("mrp_workbench", { ticket: frm.doc.name });
		}).addClass("btn-primary");

		// Button: Calcular MRP
		if (["Em Preparação", "Calculado", "Calculado (Simulação)", "Com Inconsistências", "Em Análise"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Calcular MRP"), function() {
				frappe.confirm(__("Deseja iniciar o processamento do motor MRP para este cenário?"), function() {
					frappe.show_alert({ message: __("Processando motor de cálculo MRP..."), indicator: "blue" });
					frappe.call({
						method: "erpz_mrp.api.run_mrp_calculation",
						args: { ticket_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Processando projeção de estoque, BOMs e lead times..."),
						callback: function(r) {
							if (r.message) {
								frappe.msgprint({
									title: __("Cálculo Concluído"),
									indicator: "green",
									message: __("Sugestões geradas: {0}<br>Tempo de execução: {1}s", [r.message.total_suggestions, r.message.execution_time])
								});
								frm.reload_doc();
							}
						}
					});
				});
			}, __("Ações"));
		}

		// Button: Aprovar Cenário
		if (["Calculado", "Calculado (Simulação)", "Em Análise", "Com Inconsistências"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Aprovar Cenário"), function() {
				frappe.call({
					method: "erpz_mrp.api.approve_ticket",
					args: { ticket_name: frm.doc.name },
					callback: function(r) {
						frappe.show_alert({ message: __("Cenário Aprovado com Sucesso!"), indicator: "green" });
						frm.reload_doc();
					}
				});
			}, __("Ações"));
		}

		// Button: Efetivar Documentos
		if (frm.doc.status === "Aprovado") {
			frm.add_custom_button(__("Efetivar Abastecimento (Gerar OPs/OCs)"), function() {
				frappe.confirm(__("Atenção: A efetivação criará as Ordens de Produção, Solicitações de Compra e Transferências definitivas no ERPNext vinculadas a este Ticket. Deseja prosseguir?"), function() {
					frappe.call({
						method: "erpz_mrp.api.execute_ticket",
						args: { ticket_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Gerando Ordens de Produção e Requisições no ERPNext..."),
						callback: function(r) {
							if (r.message) {
								frappe.msgprint({
									title: __("Efetivação Concluída"),
									indicator: "green",
									message: __("Foram gerados {0} documentos no ERPNext vinculados ao Ticket.", [r.message.created_count])
								});
								frm.reload_doc();
							}
						}
					});
				});
			}, __("Ações")).addClass("btn-danger");
		}

		// Button: Ver Resultados
		frm.add_custom_button(__("Ver Resultados Sumarizados"), function() {
			frappe.route_options = { "mrp_ticket": frm.doc.name };
			frappe.set_route("List", "MRP Result");
		}, __("Visualizações"));

		// Button: Ver Linha do Tempo
		frm.add_custom_button(__("Ver Linha do Tempo de Saldos"), function() {
			frappe.route_options = { "mrp_ticket": frm.doc.name };
			frappe.set_route("List", "MRP Timeline");
		}, __("Visualizações"));

		// Button: Ver Rastreabilidade
		frm.add_custom_button(__("Ver Rastreabilidade Multinível"), function() {
			frappe.route_options = { "mrp_ticket": frm.doc.name };
			frappe.set_route("List", "MRP Traceability");
		}, __("Visualizações"));

		// Button: Ver Documentos Efetivados
		frm.add_custom_button(__("Ver Documentos Efetivados"), function() {
			frappe.route_options = { "mrp_ticket": frm.doc.name };
			frappe.set_route("List", "MRP Executed Document");
		}, __("Visualizações"));
	}
});

function get_status_color(status) {
	const map = {
		"Em Preparação": "grey",
		"Processando": "orange",
		"Calculado": "blue",
		"Calculado (Simulação)": "blue",
		"Em Análise": "purple",
		"Aprovado": "yellow",
		"Efetivado": "green",
		"Cancelado": "red",
		"Com Inconsistências": "red"
	};
	return map[status] || "grey";
}
