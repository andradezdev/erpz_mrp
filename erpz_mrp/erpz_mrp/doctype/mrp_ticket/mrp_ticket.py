# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from erpz_mrp.engine.mrp_engine import MRPEngine
from erpz_mrp.engine.execution import execute_ticket_abastecimento

class MRPTicket(Document):
    def validate(self):
        if self.from_date and self.to_date and self.to_date < self.from_date:
            frappe.throw(_("Data Final não pode ser anterior à Data Inicial."))

    @frappe.whitelist()
    def calculate_mrp(self):
        engine = MRPEngine(self.name)
        result = engine.run()
        self.reload()
        return result

    @frappe.whitelist()
    def approve_ticket(self):
        if self.status not in ("Calculado", "Calculado (Simulação)", "Em Análise", "Com Inconsistências"):
            frappe.throw(_("Apenas tickets calculados podem ser aprovados."))
        self.status = "Aprovado"
        self.approved_on = frappe.utils.now_datetime()
        self.approved_by = frappe.session.user
        self.save()
        return True

    @frappe.whitelist()
    def execute_ticket(self, selected_results=None):
        res = execute_ticket_abastecimento(self.name, selected_results)
        self.reload()
        return res
