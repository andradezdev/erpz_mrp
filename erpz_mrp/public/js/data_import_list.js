// Copyright (c) 2026, ERPZ and contributors
// For license information, please see license.txt

frappe.listview_settings["Data Import"] = frappe.listview_settings["Data Import"] || {};

const orig_onload = frappe.listview_settings["Data Import"].onload;
const orig_refresh = frappe.listview_settings["Data Import"].refresh;

frappe.listview_settings["Data Import"].onload = function (listview) {
	if (orig_onload) orig_onload(listview);
};

frappe.listview_settings["Data Import"].refresh = function (listview) {
	if (orig_refresh) orig_refresh(listview);

	if (!listview.page.__erpz_btn_added) {
		listview.page.__erpz_btn_added = true;

		// Detect if reference_doctype is filtered in route or URL
		let ref_dt = (frappe.route_options && frappe.route_options.reference_doctype) || "";
		if (!ref_dt && window.location.search) {
			const params = new URLSearchParams(window.location.search);
			ref_dt = params.get("reference_doctype") || "";
		}

		let default_type = "items";
		if (ref_dt === "Customer") default_type = "customers";
		else if (ref_dt === "Supplier") default_type = "suppliers";
		else if (ref_dt === "BOM") default_type = "bom";
		else if (ref_dt === "Workstation" || ref_dt === "APS Resource") default_type = "workstations";
		else if (ref_dt === "Stock Reconciliation" || ref_dt === "Stock Entry") default_type = "stock";
		else if (ref_dt === "Item") default_type = "items";

		// Add custom button to page
		let btn = listview.page.add_inner_button(
			__("Importar Cadastros ERPZ (Excel/CSV)"),
			function () {
				if (window.erpz_mrp && erpz_mrp.show_import_center_dialog) {
					erpz_mrp.show_import_center_dialog(default_type);
				} else {
					frappe.require("/assets/erpz_mrp/js/erpz_mrp.js", function () {
						erpz_mrp.show_import_center_dialog(default_type);
					});
				}
			}
		);
		if (btn) {
			btn.addClass("btn-primary font-weight-bold text-white");
		}
	}
};
