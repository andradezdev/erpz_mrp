// Copyright (c) 2026, ERPZ and contributors
// For license information, please see license.txt

frappe.provide("erpz_mrp");

erpz_mrp.show_import_center_dialog = function(default_type = "items") {
	frappe.call({
		method: "erpz_mrp.api.get_import_center_options",
		callback: function(r) {
			const opts = (r && r.message) || {};
			const cadastros = opts.cadastros || [
				{ id: "items", label: "1 - Produtos / Itens", description: "Cadastro e atualização de Itens no ERPZ com estoque mínimo, ponto de pedido, estoque de segurança e lote mínimo.", template_name: "Modelo_Importacao_Produtos_Itens.xlsx" },
				{ id: "stock", label: "2 - Saldos de Estoque dos Itens", description: "Carga de saldo inicial de estoque por armazém e valor de avaliação via Reconciliação de Estoque no ERPZ.", template_name: "Modelo_Importacao_Estoque_Itens.xlsx" },
				{ id: "workstations", label: "3 - Recursos / Postos de Trabalho", description: "Cadastro de Postos de Trabalho no ERPZ e Recursos no APS com capacidade diária, eficiência e finais de semana.", template_name: "Modelo_Importacao_Recursos_Postos_Trabalho.xlsx" },
				{ id: "alternative_resources", label: "4 - Recursos Alternativos", description: "Vinculação de Recursos Alternativos e Secundários aos Postos Principais com prioridade e fator de eficiência.", template_name: "Modelo_Importacao_Recursos_Alternativos.xlsx" },
				{ id: "bom", label: "5 - Estrutura de Produtos (BOM)", description: "Estrutura do produto onde o Dono do Registro (Pai) e o Componente (Filho) ficam lado a lado por linha, gerando BOMs no ERPZ.", template_name: "Modelo_Importacao_Estrutura_BOM.xlsx" },
				{ id: "customers", label: "6 - Clientes", description: "Importação de Clientes no ERPZ com Razão Social, Nome Fantasia, CNPJ/CPF, Inscrição Estadual, telefone e e-mail.", template_name: "Modelo_Importacao_Clientes.xlsx" },
				{ id: "suppliers", label: "7 - Fornecedores", description: "Importação de Fornecedores no ERPZ com Razão Social, CNPJ/CPF, Inscrição Estadual, contatos e endereço.", template_name: "Modelo_Importacao_Fornecedores.xlsx" }
			];

			const default_company = opts.default_company || "";
			const select_options = cadastros.map(c => ({ value: c.id, label: c.label }));

			function get_instructions_html(type_id) {
				const cad = cadastros.find(c => c.id === type_id) || cadastros[0];
				return `
					<div class="alert alert-info small mb-3">
						<div class="d-flex justify-content-between align-items-start">
							<div>
								<b>${cad.label}</b><br>
								${cad.description}
							</div>
							<div>
								<a href="/api/method/erpz_mrp.api.download_cadastros_template?import_type=${cad.id}" class="btn btn-xs btn-primary text-nowrap" target="_blank">
									<i class="octicon octicon-cloud-download"></i> Baixar Modelo Excel (.xlsx)
								</a>
							</div>
						</div>
						<div class="mt-2 text-muted" style="font-size: 11px;">
							<i>Formatos aceitos: <b>.xlsx</b> (Excel modelo padrão) ou <b>.csv</b> (delimitado por ponto e vírgula (padrão ERPZ)).</i>
						</div>
					</div>
				`;
			}

			let d = new frappe.ui.Dialog({
				title: __("Central de Importação e Carga de Cadastros"),
				fields: [
					{
						label: __("Selecione o Cadastro"),
						fieldname: "import_type",
						fieldtype: "Select",
						options: select_options,
						default: default_type,
						reqd: 1,
						change() {
							const cur_type = d.get_value("import_type");
							d.fields_dict.instructions.$wrapper.html(get_instructions_html(cur_type));
						}
					},
					{
						label: __("Empresa de Destino"),
						fieldname: "company",
						fieldtype: "Link",
						options: "Company",
						default: default_company,
						reqd: 1
					},
					{
						fieldtype: "HTML",
						fieldname: "instructions",
						options: get_instructions_html(default_type)
					},
					{
						label: __("Arquivo de Carga (.xlsx ou .csv)"),
						fieldname: "data_file",
						fieldtype: "Attach",
						reqd: 1
					}
				],
				primary_action_label: __("Importar e Processar"),
				primary_action(values) {
					if (!values.data_file) {
						frappe.msgprint(__("Por favor, selecione um arquivo para importar."));
						return;
					}

					const cur_cad = cadastros.find(c => c.id === values.import_type) || {};
					d.hide();
					frappe.show_alert({ message: __("Processando carga de {0}...", [cur_cad.label || values.import_type]), indicator: "blue" });

					frappe.call({
						method: "erpz_mrp.api.import_cadastros",
						args: {
							import_type: values.import_type,
							file_url: values.data_file,
							company: values.company
						},
						timeout: 3600,
						freeze: true,
						freeze_message: __("Processando dados e inserindo no sistema..."),
						callback: function(res) {
							const data = (res && res.message) || {};
							if (data.success) {
								let error_html = "";
								if (data.errors && data.errors.length > 0) {
									error_html = `
										<div class="mt-3">
											<h6 class="text-danger">Inconsistências / Alertas (${data.errors.length}):</h6>
											<div class="border p-2 bg-light rounded" style="max-height: 150px; overflow-y: auto; font-size: 11px;">
												${data.errors.map(e => `<div class="text-danger py-0.5">• ${frappe.utils.escape_html(e)}</div>`).join("")}
											</div>
										</div>
									`;
								}

								let msg = `
									<div class="py-2">
										<div class="d-flex gap-3 mb-3">
											<div class="card p-2 text-center flex-fill border bg-light">
												<div class="text-muted small">Total de Linhas</div>
												<div class="h4 mb-0 font-weight-bold text-dark">${data.total_rows || 0}</div>
											</div>
											<div class="card p-2 text-center flex-fill border bg-light">
												<div class="text-muted small">Registros Criados</div>
												<div class="h4 mb-0 font-weight-bold text-success">${data.created_count || 0}</div>
											</div>
											<div class="card p-2 text-center flex-fill border bg-light">
												<div class="text-muted small">Atualizados</div>
												<div class="h4 mb-0 font-weight-bold text-primary">${data.updated_count || 0}</div>
											</div>
										</div>
										<p class="text-muted small mb-0">Carga de <b>${cur_cad.label || values.import_type}</b> processada com sucesso no ERPZ!</p>
										${error_html}
									</div>
								`;

								frappe.msgprint({
									title: __("Carga Concluída com Sucesso"),
									indicator: data.errors && data.errors.length > 0 ? "orange" : "green",
									message: msg,
									wide: true
								});
							}
						}
					});
				}
			});
			d.show();
		}
	});
};
