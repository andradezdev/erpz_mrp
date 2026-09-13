# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, flt, getdate

def execute_ticket_abastecimento(ticket_name, selected_result_ids=None):
    """
    Transforms approved MRP Results into real ERPNext documents:
    - Produção -> Work Order
    - Compra -> Material Request (Purpose: Purchase)
    - Transferência -> Material Request (Purpose: Material Transfer) or Stock Entry
    """
    ticket = frappe.get_doc("MRP Ticket", ticket_name)
    if ticket.status == "Efetivado":
        frappe.msgprint(
            title="Ticket Já Efetivado",
            indicator="blue",
            message=f"O Ticket {ticket_name} já foi efetivado anteriormente. Todos os documentos operacionais (Ordens de Produção, Requisições) já foram gerados e estão disponíveis para consulta."
        )
        return {"status": "already_executed", "created_count": 0, "documents": []}

    if ticket.status not in ("Aprovado", "Calculado", "Em Análise"):
        frappe.throw(f"O Ticket {ticket_name} deve estar em status 'Aprovado' para efetivação.")

    settings = frappe.get_single("MRP Settings")
    purchase_doc_type = settings.purchase_doc_type or "Material Request"
    auto_submit_wo = settings.auto_submit_work_order or False

    filters = {"mrp_ticket": ticket_name, "status": ["in", ["Pendente", "Aprovado"]]}
    if selected_result_ids:
        filters["name"] = ["in", selected_result_ids]

    results = frappe.get_all(
        "MRP Result",
        filters=filters,
        fields=[
            "name", "item_code", "item_name", "company", "warehouse",
            "need_date", "supply_date", "suggested_qty", "supply_type",
            "origin_doctype", "origin_name", "origin_item", "bom_no",
            "from_company", "from_warehouse"
        ]
    )

    if not results:
        frappe.msgprint(
            title="Nenhuma Sugestão Pendente",
            indicator="blue",
            message=f"Todas as necessidades calculadas do Ticket {ticket_name} já foram efetivadas ou atendidas."
        )
        return {"status": "already_executed", "created_count": 0, "documents": []}

    created_docs = []

    # 1. Group purchase suggestions by Company and Required Date to avoid spamming 1 document per line
    purchase_items_by_company = {}

    for res in results:
        supply_type = res.supply_type
        
        # A. Produção -> Work Order
        if supply_type == "Produção":
            if not res.bom_no:
                bom = frappe.db.get_value("BOM", {"item": res.item_code, "is_active": 1, "is_default": 1}, "name")
            else:
                bom = res.bom_no

            if not bom:
                frappe.msgprint(f"Não foi possível criar Ordem de Produção para {res.item_code}: BOM não encontrada.")
                continue

            wo = frappe.new_doc("Work Order")
            wo.company = res.company
            wo.production_item = res.item_code
            wo.bom_no = bom
            wo.qty = res.suggested_qty
            wo.planned_start_date = res.supply_date
            wo.expected_delivery_date = res.need_date
            wo.fg_warehouse = res.warehouse
            
            # Link back to MRP Ticket & Origin
            if hasattr(wo, "custom_mrp_ticket"):
                wo.custom_mrp_ticket = ticket_name
            if hasattr(wo, "custom_mrp_origin_demand"):
                wo.custom_mrp_origin_demand = res.origin_name
                
            if res.origin_doctype == "Sales Order":
                wo.sales_order = res.origin_name

            wo.insert(ignore_permissions=True)
            if auto_submit_wo:
                wo.submit()

            record_execution(
                ticket_name=ticket_name,
                doc_type="Work Order",
                doc_name=wo.name,
                item_code=res.item_code,
                qty=res.suggested_qty,
                company=res.company,
                status=wo.status or "Draft",
                origin_doctype=res.origin_doctype,
                origin_name=res.origin_name
            )

            frappe.db.set_value("MRP Result", res.name, {
                "generated_doctype": "Work Order",
                "generated_docname": wo.name,
                "status": "Efetivado"
            })
            created_docs.append({"doctype": "Work Order", "name": wo.name, "item": res.item_code})

        # B. Transferência -> Material Request (Material Transfer)
        elif supply_type == "Transferência":
            is_intercompany = bool(res.from_company and res.from_company != res.company)
            
            mr = frappe.new_doc("Material Request")
            mr.material_request_type = "Material Transfer"
            mr.company = res.company
            mr.schedule_date = res.need_date
            
            if hasattr(mr, "custom_mrp_ticket"):
                mr.custom_mrp_ticket = ticket_name
            if hasattr(mr, "custom_mrp_origin_demand"):
                mr.custom_mrp_origin_demand = f"Transferência de {res.from_company or ''} ({res.from_warehouse or ''}) -> {res.company}"

            # Validate from_warehouse against mr.company
            # ERPNext requires all warehouses in a document to belong to that document's company.
            from_wh = None
            if not is_intercompany and res.from_warehouse:
                wh_company = frappe.db.get_value("Warehouse", res.from_warehouse, "company")
                if wh_company == res.company:
                    from_wh = res.from_warehouse

            mr_item = {
                "item_code": res.item_code,
                "qty": res.suggested_qty,
                "schedule_date": res.need_date,
                "warehouse": res.warehouse
            }
            if from_wh:
                mr_item["from_warehouse"] = from_wh

            mr.append("items", mr_item)
            mr.insert(ignore_permissions=True)

            record_execution(
                ticket_name=ticket_name,
                doc_type="Material Request",
                doc_name=mr.name,
                item_code=res.item_code,
                qty=res.suggested_qty,
                company=res.company,
                status=mr.status or "Draft",
                origin_doctype=res.origin_doctype,
                origin_name=res.origin_name
            )

            # In intercompany transfers, also create dispatch Material Request in supplying company
            if is_intercompany and res.from_company:
                try:
                    mr_from = frappe.new_doc("Material Request")
                    mr_from.material_request_type = "Material Transfer"
                    mr_from.company = res.from_company
                    mr_from.schedule_date = res.supply_date or res.need_date
                    if hasattr(mr_from, "custom_mrp_ticket"):
                        mr_from.custom_mrp_ticket = ticket_name
                    if hasattr(mr_from, "custom_mrp_origin_demand"):
                        mr_from.custom_mrp_origin_demand = f"Fornecimento para {res.company} ({res.warehouse or ''})"
                    mr_from.append("items", {
                        "item_code": res.item_code,
                        "qty": res.suggested_qty,
                        "schedule_date": res.supply_date or res.need_date,
                        "warehouse": res.from_warehouse
                    })
                    mr_from.insert(ignore_permissions=True)
                    record_execution(
                        ticket_name=ticket_name,
                        doc_type="Material Request",
                        doc_name=mr_from.name,
                        item_code=res.item_code,
                        qty=res.suggested_qty,
                        company=res.from_company,
                        status=mr_from.status or "Draft",
                        origin_doctype="MRP Ticket",
                        origin_name=ticket_name
                    )
                except Exception as e:
                    frappe.log_error(title="Erro ao criar Material Request fornecedor", message=str(e))

            frappe.db.set_value("MRP Result", res.name, {
                "generated_doctype": "Material Request",
                "generated_docname": mr.name,
                "status": "Efetivado"
            })
            created_docs.append({"doctype": "Material Request", "name": mr.name, "item": res.item_code})

        # C. Compra -> Agrupar para Material Request (Purchase)
        elif supply_type == "Compra":
            key = (res.company, res.need_date)
            if key not in purchase_items_by_company:
                purchase_items_by_company[key] = []
            purchase_items_by_company[key].append(res)

    # Process grouped purchase items
    for (comp, need_d), items in purchase_items_by_company.items():
        mr = frappe.new_doc("Material Request")
        mr.material_request_type = "Purchase"
        mr.company = comp
        mr.schedule_date = need_d
        
        if hasattr(mr, "custom_mrp_ticket"):
            mr.custom_mrp_ticket = ticket_name

        for it in items:
            uom = frappe.db.get_value("Item", it.item_code, "stock_uom")
            mr.append("items", {
                "item_code": it.item_code,
                "qty": it.suggested_qty,
                "schedule_date": it.need_date,
                "warehouse": it.warehouse,
                "uom": uom
            })

        mr.insert(ignore_permissions=True)

        for it in items:
            record_execution(
                ticket_name=ticket_name,
                doc_type="Material Request",
                doc_name=mr.name,
                item_code=it.item_code,
                qty=it.suggested_qty,
                company=comp,
                status=mr.status or "Draft",
                origin_doctype=it.origin_doctype,
                origin_name=it.origin_name
            )

            frappe.db.set_value("MRP Result", it.name, {
                "generated_doctype": "Material Request",
                "generated_docname": mr.name,
                "status": "Efetivado"
            })
            created_docs.append({"doctype": "Material Request", "name": mr.name, "item": it.item_code})

    # Update Ticket Status
    ticket.db_set({
        "status": "Efetivado",
        "executed_on": now_datetime(),
        "executed_by": frappe.session.user
    })
    frappe.db.commit()

    return {
        "status": "success",
        "created_count": len(created_docs),
        "documents": created_docs
    }

def record_execution(ticket_name, doc_type, doc_name, item_code, qty, company, status, origin_doctype, origin_name):
    doc = frappe.new_doc("MRP Executed Document")
    doc.mrp_ticket = ticket_name
    doc.document_type = doc_type
    doc.document_name = doc_name
    doc.item_code = item_code
    doc.quantity = qty
    doc.company = company
    doc.status = status
    doc.origin_doctype = origin_doctype
    doc.origin_name = origin_name
    doc.insert(ignore_permissions=True)
