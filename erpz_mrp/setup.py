# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def setup_mrp_custom_fields():
    custom_fields = {
        "Work Order": [
            {
                "fieldname": "custom_mrp_ticket",
                "label": "Ticket MRP",
                "fieldtype": "Link",
                "options": "MRP Ticket",
                "insert_after": "naming_series",
                "read_only": 1
            },
            {
                "fieldname": "custom_mrp_origin_demand",
                "label": "Origem MRP",
                "fieldtype": "Data",
                "insert_after": "custom_mrp_ticket",
                "read_only": 1
            }
        ],
        "Material Request": [
            {
                "fieldname": "custom_mrp_ticket",
                "label": "Ticket MRP",
                "fieldtype": "Link",
                "options": "MRP Ticket",
                "insert_after": "naming_series",
                "read_only": 1
            },
            {
                "fieldname": "custom_mrp_origin_demand",
                "label": "Origem MRP",
                "fieldtype": "Data",
                "insert_after": "custom_mrp_ticket",
                "read_only": 1
            }
        ],
        "Purchase Order": [
            {
                "fieldname": "custom_mrp_ticket",
                "label": "Ticket MRP",
                "fieldtype": "Link",
                "options": "MRP Ticket",
                "insert_after": "naming_series",
                "read_only": 1
            }
        ],
        "Stock Entry": [
            {
                "fieldname": "custom_mrp_ticket",
                "label": "Ticket MRP",
                "fieldtype": "Link",
                "options": "MRP Ticket",
                "insert_after": "naming_series",
                "read_only": 1
            },
            {
                "fieldname": "custom_mrp_origin_demand",
                "label": "Origem MRP",
                "fieldtype": "Data",
                "insert_after": "custom_mrp_ticket",
                "read_only": 1
            }
        ]
    }
    
    create_custom_fields(custom_fields, update=True)
    print("MRP Custom fields successfully registered in ERPNext!")

def setup_mrp_desktop_and_sidebar():
    """Automatically ensures Desktop Icon and Workspace Sidebar are created and visible on /desk."""
    try:
        from frappe.desk.doctype.workspace_sidebar.workspace_sidebar import create_workspace_sidebar_for_workspaces
        from frappe.desk.doctype.desktop_icon.desktop_icon import create_desktop_icons
        create_workspace_sidebar_for_workspaces()
        create_desktop_icons()
    except Exception as e:
        print(f"Warning during auto icon generation: {e}")

    # Ensure Desktop Icon ERPZ MRP is configured to show on the main Desk
    icon_name = frappe.db.get_value("Desktop Icon", {"link_to": "ERPZ MRP"}, "name")
    if not icon_name:
        icon_name = frappe.db.get_value("Desktop Icon", {"label": "Planejamento MRP"}, "name")
    if not icon_name:
        icon_name = frappe.db.get_value("Desktop Icon", {"label": "ERPZ MRP"}, "name")

    if icon_name:
        frappe.db.set_value("Desktop Icon", icon_name, {
            "label": "ERPZ MRP",
            "icon": "project",
            "icon_type": "Link",
            "link_type": "Workspace Sidebar",
            "link_to": "ERPZ MRP",
            "parent_icon": "",
            "hidden": 0,
            "standard": 1,
            "app": "erpz_mrp",
            "idx": 7
        })
    else:
        new_icon = frappe.new_doc("Desktop Icon")
        new_icon.name = "ERPZ MRP"
        new_icon.label = "ERPZ MRP"
        new_icon.icon = "project"
        new_icon.icon_type = "Link"
        new_icon.link_type = "Workspace Sidebar"
        new_icon.link_to = "ERPZ MRP"
        new_icon.parent_icon = ""
        new_icon.hidden = 0
        new_icon.standard = 1
        new_icon.app = "erpz_mrp"
        new_icon.idx = 7
        new_icon.insert(ignore_permissions=True)

    # Ensure Workspace Sidebar ERPZ MRP exists with items
    if not frappe.db.exists("Workspace Sidebar", "ERPZ MRP"):
        sb = frappe.new_doc("Workspace Sidebar")
        sb.title = "ERPZ MRP"
        sb.header_icon = "project"
        sb.app = "erpz_mrp"
        sb.standard = 1
        sb.append("items", {"label": "Home", "link_to": "ERPZ MRP", "link_type": "Workspace", "type": "Link", "idx": 0})
        sb.append("items", {"label": "Painel de Planejamento MRP", "link_to": "mrp-workbench", "link_type": "Page", "type": "Link", "idx": 1})
        sb.append("items", {"label": "Tickets de Cálculo (MRP)", "link_to": "MRP Ticket", "link_type": "DocType", "type": "Link", "idx": 2})
        sb.append("items", {"label": "Resultados e Consultas", "type": "Section Break", "idx": 3})
        sb.append("items", {"label": "Sugestões de Abastecimento", "link_to": "MRP Result", "link_type": "DocType", "type": "Link", "child": 1, "idx": 4})
        sb.append("items", {"label": "Linha do Tempo de Saldos", "link_to": "MRP Timeline", "link_type": "DocType", "type": "Link", "child": 1, "idx": 5})
        sb.append("items", {"label": "Rastreabilidade de Demandas", "link_to": "MRP Traceability", "link_type": "DocType", "type": "Link", "child": 1, "idx": 6})
        sb.append("items", {"label": "Documentos Efetivados", "link_to": "MRP Executed Document", "link_type": "DocType", "type": "Link", "child": 1, "idx": 7})
        sb.append("items", {"label": "Auditoria e Logs", "link_to": "MRP Log", "link_type": "DocType", "type": "Link", "child": 1, "idx": 8})
        sb.append("items", {"label": "Cadastros e Parâmetros", "type": "Section Break", "idx": 9})
        sb.append("items", {"label": "Parâmetros do MRP", "link_to": "MRP Settings", "link_type": "DocType", "type": "Link", "child": 1, "idx": 10})
        sb.append("items", {"label": "Grupos de Empresas Multiempresa", "link_to": "MRP Company Group", "link_type": "DocType", "type": "Link", "child": 1, "idx": 11})
        sb.append("items", {"label": "Lead Time entre Empresas", "link_to": "MRP Inter Company Lead Time", "link_type": "DocType", "type": "Link", "child": 1, "idx": 12})
        sb.insert(ignore_permissions=True)
    else:
        # Update sidebar title, app and items
        sb = frappe.get_doc("Workspace Sidebar", "ERPZ MRP")
        sb.items = []
        sb.append("items", {"label": "Home", "link_to": "ERPZ MRP", "link_type": "Workspace", "type": "Link", "idx": 0})
        sb.append("items", {"label": "Painel de Planejamento MRP", "link_to": "mrp-workbench", "link_type": "Page", "type": "Link", "idx": 1})
        sb.append("items", {"label": "Tickets de Cálculo (MRP)", "link_to": "MRP Ticket", "link_type": "DocType", "type": "Link", "idx": 2})
        sb.append("items", {"label": "Resultados e Consultas", "type": "Section Break", "idx": 3})
        sb.append("items", {"label": "Sugestões de Abastecimento", "link_to": "MRP Result", "link_type": "DocType", "type": "Link", "child": 1, "idx": 4})
        sb.append("items", {"label": "Linha do Tempo de Saldos", "link_to": "MRP Timeline", "link_type": "DocType", "type": "Link", "child": 1, "idx": 5})
        sb.append("items", {"label": "Rastreabilidade de Demandas", "link_to": "MRP Traceability", "link_type": "DocType", "type": "Link", "child": 1, "idx": 6})
        sb.append("items", {"label": "Documentos Efetivados", "link_to": "MRP Executed Document", "link_type": "DocType", "type": "Link", "child": 1, "idx": 7})
        sb.append("items", {"label": "Auditoria e Logs", "link_to": "MRP Log", "link_type": "DocType", "type": "Link", "child": 1, "idx": 8})
        sb.append("items", {"label": "Cadastros e Parâmetros", "type": "Section Break", "idx": 9})
        sb.append("items", {"label": "Parâmetros do MRP", "link_to": "MRP Settings", "link_type": "DocType", "type": "Link", "child": 1, "idx": 10})
        sb.append("items", {"label": "Grupos de Empresas Multiempresa", "link_to": "MRP Company Group", "link_type": "DocType", "type": "Link", "child": 1, "idx": 11})
        sb.append("items", {"label": "Lead Time entre Empresas", "link_to": "MRP Inter Company Lead Time", "link_type": "DocType", "type": "Link", "child": 1, "idx": 12})
        sb.app = "erpz_mrp"
        sb.header_icon = "project"
        sb.standard = 1
        sb.save(ignore_permissions=True)

    # Ensure Workspace ERPZ MRP has valid content blocks
    if frappe.db.exists("Workspace", "ERPZ MRP"):
        import json
        ws = frappe.get_doc("Workspace", "ERPZ MRP")
        ws.type = "Workspace"
        for l in ws.links:
            if l.type == "Card Break":
                l.link_type = ""
                l.link_to = ""
            elif l.link_to in ("mrp_workbench", "mrp-workbench"):
                l.link_to = "mrp-workbench"
                l.link_type = "Page"
        for s in ws.shortcuts:
            if s.link_to in ("mrp_workbench", "mrp-workbench"):
                s.link_to = "mrp-workbench"
                
        content_blocks = [
            {"id": "h_shortcuts", "type": "header", "data": {"text": "<span class=\"h4\"><b>Atalhos Rápidos</b></span>", "col": 12}},
            {"id": "sc_workbench", "type": "shortcut", "data": {"shortcut_name": "Painel de Planejamento", "col": 4}},
            {"id": "sc_ticket", "type": "shortcut", "data": {"shortcut_name": "Tickets de Cálculo", "col": 4}},
            {"id": "sc_result", "type": "shortcut", "data": {"shortcut_name": "Sugestões de Abastecimento", "col": 4}},
            {"id": "spacer_1", "type": "spacer", "data": {"col": 12}},
            {"id": "h_cards", "type": "header", "data": {"text": "<span class=\"h4\"><b>Módulos e Consultas</b></span>", "col": 12}},
            {"id": "card_ops", "type": "card", "data": {"card_name": "Central e Operações", "col": 4}},
            {"id": "card_res", "type": "card", "data": {"card_name": "Resultados e Consultas", "col": 4}},
            {"id": "card_param", "type": "card", "data": {"card_name": "Cadastros e Parâmetros", "col": 4}}
        ]
        ws.content = json.dumps(content_blocks)
        ws.save(ignore_permissions=True)

    # Clear caches
    frappe.cache.delete_keys("desktop_icons")
    frappe.clear_cache()
    frappe.db.commit()
    print("Desktop Icon and Workspace Sidebar successfully configured for ERPZ MRP!")

def after_install():
    setup_mrp_custom_fields()
    setup_mrp_desktop_and_sidebar()

def after_migrate():
    setup_mrp_custom_fields()
    setup_mrp_desktop_and_sidebar()
