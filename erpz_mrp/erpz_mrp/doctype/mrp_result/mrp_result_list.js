// Copyright (c) 2026, ERPZ and contributors
// For license information, please see license.txt

frappe.listview_settings["MRP Result"] = {
	add_fields: ["status", "supply_type", "suggested_qty", "need_date", "supply_date", "origin_name", "situation"],
	get_indicator(doc) {
		if (doc.status === "Efetivado") {
			return [__("Efetivado"), "green", "status,=,Efetivado"];
		} else if (doc.status === "Aprovado") {
			return [__("Aprovado"), "blue", "status,=,Aprovado"];
		} else if (doc.status === "Atrasado") {
			return [__("Atrasado"), "red", "status,=,Atrasado"];
		} else if (doc.status === "Descartado") {
			return [__("Descartado"), "grey", "status,=,Descartado"];
		} else {
			return [__("Pendente"), "orange", "status,=,Pendente"];
		}
	}
};
