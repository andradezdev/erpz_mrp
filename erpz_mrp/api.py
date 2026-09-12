# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime, getdate, flt
from erpz_mrp.engine.mrp_engine import MRPEngine
from erpz_mrp.engine.execution import execute_ticket_abastecimento

@frappe.whitelist()
def run_mrp_calculation(ticket_name):
    """Triggers the 20-step MRP calculation engine for a given ticket."""
    if not frappe.has_permission("MRP Ticket", "write"):
        frappe.throw(_("Sem permissão para executar cálculo de MRP."))
        
    engine = MRPEngine(ticket_name)
    result = engine.run()
    return result

@frappe.whitelist()
def approve_ticket(ticket_name):
    """Approves an MRP ticket for subsequent document execution."""
    if not frappe.has_permission("MRP Ticket", "write"):
        frappe.throw(_("Sem permissão para aprovar Ticket MRP."))
        
    ticket = frappe.get_doc("MRP Ticket", ticket_name)
    if ticket.status not in ("Calculado", "Calculado (Simulação)", "Em Análise", "Com Inconsistências"):
        frappe.throw(_("Apenas tickets calculados podem ser aprovados."))
        
    ticket.db_set({
        "status": "Aprovado",
        "approved_on": now_datetime(),
        "approved_by": frappe.session.user
    })
    frappe.db.commit()
    return {"status": "success", "message": _("Ticket aprovado com sucesso.")}

@frappe.whitelist()
def execute_ticket(ticket_name, selected_results=None):
    """Generates Work Orders, Material Requests, and Stock Entries from MRP results."""
    if not frappe.has_permission("MRP Ticket", "write"):
        frappe.throw(_("Sem permissão para efetivar Ticket MRP."))
        
    if isinstance(selected_results, str):
        import json
        selected_results = json.loads(selected_results)
        
    res = execute_ticket_abastecimento(ticket_name, selected_results)
    return res

@frappe.whitelist()
def get_mrp_summary(ticket_name, company=None, item_code=None, supply_type=None, status=None, start=0, page_length=50):
    """Returns paginated MRP Results with filters for the Desk grid."""
    filters = {"mrp_ticket": ticket_name}
    if company:
        filters["company"] = company
    if item_code:
        filters["item_code"] = item_code
    if supply_type:
        filters["supply_type"] = supply_type
    if status:
        filters["status"] = status
        
    total_count = frappe.db.count("MRP Result", filters=filters)
    results = frappe.get_all(
        "MRP Result",
        filters=filters,
        fields=[
            "name", "item_code", "item_name", "company", "warehouse",
            "need_date", "supply_date", "gross_demand", "initial_stock",
            "planned_inflows", "projected_balance", "safety_stock",
            "net_requirement", "suggested_qty", "supply_type",
            "origin_item", "origin_doctype", "origin_name",
            "bom_level", "lead_time_days", "from_company", "from_warehouse",
            "status", "situation", "generated_doctype", "generated_docname"
        ],
        start=cint(start),
        page_length=cint(page_length),
        order_by="need_date ASC, item_code ASC"
    )
    
    return {
        "total": total_count,
        "items": results
    }

@frappe.whitelist()
def get_timeline_data(ticket_name, item_code=None, company=None):
    """Returns day-by-day projected balance and chart series for an item."""
    filters = {"mrp_ticket": ticket_name}
    if item_code:
        filters["item_code"] = item_code
    if company:
        filters["company"] = company
        
    rows = frappe.get_all(
        "MRP Timeline",
        filters=filters,
        fields=[
            "item_code", "item_name", "company", "timeline_date",
            "initial_balance", "inflows", "outflows", "projected_balance",
            "safety_stock", "shortage_qty", "suggested_inflow", "has_shortage"
        ],
        order_by="timeline_date ASC"
    )
    
    dates = []
    projected = []
    safety = []
    shortages = []
    inflows = []
    outflows = []
    
    for r in rows:
        d_str = str(r.timeline_date)
        dates.append(d_str)
        projected.append(r.projected_balance)
        safety.append(r.safety_stock)
        shortages.append(r.shortage_qty)
        inflows.append(r.inflows + r.suggested_inflow)
        outflows.append(r.outflows)
        
    return {
        "dates": dates,
        "projected_balance": projected,
        "safety_stock": safety,
        "shortage_qty": shortages,
        "inflows": inflows,
        "outflows": outflows,
        "raw_rows": rows
    }

@frappe.whitelist()
def get_traceability_tree(ticket_name, root_demand=None):
    """Builds a hierarchical tree from MRP Traceability nodes."""
    nodes = frappe.get_all(
        "MRP Traceability",
        filters={"mrp_ticket": ticket_name},
        fields=[
            "name", "demand_source_doctype", "demand_source_name",
            "root_item", "parent_item", "child_item", "bom_level",
            "required_qty", "allocated_qty", "supply_type",
            "from_company", "to_company", "need_date", "planned_start_date",
            "target_doctype", "target_docname", "status"
        ],
        order_by="bom_level ASC, need_date ASC"
    )
    
    # Build tree representation
    # Top nodes are level 0
    tree = []
    level_map = {}
    
    for node in nodes:
        key = (node.demand_source_name, node.child_item, node.bom_level)
        node_dict = dict(node)
        node_dict["children"] = []
        level_map[key] = node_dict
        
        if node.bom_level == 0:
            tree.append(node_dict)
        else:
            # Attach to parent if found
            parent_key = (node.demand_source_name, node.parent_item, node.bom_level - 1)
            parent = level_map.get(parent_key)
            if parent:
                parent["children"].append(node_dict)
            else:
                tree.append(node_dict)
                
    return tree

@frappe.whitelist()
def get_ticket_dashboard_metrics(ticket_name):
    """Returns high-level KPI cards data for the workbench."""
    ticket = frappe.get_doc("MRP Ticket", ticket_name)
    
    total_shortages = frappe.db.count("MRP Timeline", {"mrp_ticket": ticket_name, "has_shortage": 1})
    pending_approvals = frappe.db.count("MRP Result", {"mrp_ticket": ticket_name, "status": "Pendente"})
    transfers_count = frappe.db.count("MRP Result", {"mrp_ticket": ticket_name, "supply_type": "Transferência"})
    inconsistencies = frappe.db.count("MRP Log", {"mrp_ticket": ticket_name})
    
    return {
        "status": ticket.status,
        "total_demands": ticket.total_demands or 0,
        "total_suggestions": ticket.total_suggestions or 0,
        "total_produced": ticket.total_produced or 0,
        "total_purchased": ticket.total_purchased or 0,
        "total_transferred": ticket.total_transferred or 0,
        "total_inconsistencies": inconsistencies,
        "pending_approvals": pending_approvals,
        "total_shortages": total_shortages,
        "execution_time": ticket.execution_time_seconds or 0
    }
