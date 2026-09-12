# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import now_datetime, getdate, flt, cint
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
    if supply_type:
        filters["supply_type"] = supply_type
    if status:
        filters["status"] = status
        
    or_filters = None
    if item_code:
        # Search across item_code, item_name, origin_name, or generated_docname
        or_filters = [
            ["item_code", "like", f"%{item_code}%"],
            ["item_name", "like", f"%{item_code}%"],
            ["origin_name", "like", f"%{item_code}%"],
            ["generated_docname", "like", f"%{item_code}%"]
        ]
        
    total_count = frappe.db.count("MRP Result", filters=filters, or_filters=or_filters)
    results = frappe.get_all(
        "MRP Result",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "item_code", "item_name", "company", "warehouse",
            "need_date", "supply_date", "gross_demand", "initial_stock",
            "planned_inflows", "projected_balance", "safety_stock",
            "net_requirement", "suggested_qty", "supply_type",
            "origin_item", "origin_doctype", "origin_name", "bom_no",
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
    """
    Builds a true hierarchical tree structure matching Sections 71, 72, 88, 92 of the MRP specification:
    Level Root: Demand Document (ex: Pedido de Venda SAL-ORD-2026-00009)
      └── Level 0: Produto Acabado (TEST-MRP-A) - Sugestão de Produção
          ├── Level 1: Componente B (TEST-MRP-B) - Produção
          └── Level 1: Componente C (TEST-MRP-C) - Transferência / Compra
    """
    from collections import defaultdict
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
    
    # 1. Deduplicate nodes to avoid duplicate branches
    unique_nodes = []
    seen = set()
    for n in nodes:
        key = (n.demand_source_doctype, n.demand_source_name, n.parent_item, n.child_item, n.bom_level, flt(n.required_qty), n.supply_type)
        if key not in seen:
            seen.add(key)
            node_dict = dict(n)
            node_dict["item_name"] = frappe.db.get_value("Item", n.child_item, "item_name") or n.child_item
            node_dict["children"] = []
            unique_nodes.append(node_dict)

    # 2. Build tree by attaching Level 1 to Level 0, Level 2 to Level 1, etc.
    level_0 = [n for n in unique_nodes if n["bom_level"] == 0]
    
    def attach_children(parent_node):
        p_item = parent_node["child_item"]
        p_level = parent_node["bom_level"]
        for candidate in unique_nodes:
            if candidate["bom_level"] == p_level + 1 and candidate.get("parent_item") == p_item:
                candidate_copy = dict(candidate)
                candidate_copy["children"] = []
                attach_children(candidate_copy)
                parent_node["children"].append(candidate_copy)

    # Group Level 0 by Demand Source (e.g. Sales Order)
    demands_group = defaultdict(list)
    for n0 in level_0:
        attach_children(n0)
        group_key = (n0.get("demand_source_doctype") or "Demanda", n0.get("demand_source_name") or "Manual")
        demands_group[group_key].append(n0)

    tree = []
    for (src_type, src_name), items in demands_group.items():
        tree.append({
            "is_root_demand": True,
            "demand_source_doctype": src_type,
            "demand_source_name": src_name,
            "label": f"{src_type}: {src_name}",
            "children": items
        })

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
