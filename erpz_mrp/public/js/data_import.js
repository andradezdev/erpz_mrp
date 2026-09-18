// Copyright (c) 2026, ERPZ and contributors
// For license information, please see license.txt

frappe.ui.form.on("Data Import", {
	refresh(frm) {
		let ref_dt = frm.doc.reference_doctype;
		let default_type = "items";
		if (ref_dt === "Customer") default_type = "customers";
		else if (ref_dt === "Supplier") default_type = "suppliers";
		else if (ref_dt === "BOM") default_type = "bom";
		else if (ref_dt === "Workstation" || ref_dt === "APS Resource") default_type = "workstations";
		else if (ref_dt === "Stock Reconciliation" || ref_dt === "Stock Entry") default_type = "stock";
		else if (ref_dt === "Item") default_type = "items";

		frm.add_custom_button(__("Importar Cadastros ERPZ (Excel/CSV)"), function () {
			if (window.erpz_mrp && erpz_mrp.show_import_center_dialog) {
				erpz_mrp.show_import_center_dialog(default_type);
			} else {
				frappe.require("/assets/erpz_mrp/js/erpz_mrp.js", function () {
					erpz_mrp.show_import_center_dialog(default_type);
				});
			}
		});
	}
});
