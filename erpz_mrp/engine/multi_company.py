# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import getdate
from erpz_mrp.engine.calendar_utils import get_working_days_prior

def get_company_group_participants(group_name, exclude_company=None):
    """
    Returns list of companies ordered by priority ascending.
    """
    if not group_name:
        return []
        
    doc = frappe.get_doc("MRP Company Group", group_name)
    if not doc.is_active:
        return []
        
    participants = []
    for row in doc.companies:
        if exclude_company and row.company == exclude_company:
            continue
        participants.append({
            "company": row.company,
            "priority": row.priority or 999,
            "allow_transfer": row.allow_transfer,
            "allow_production": row.allow_production,
            "allow_purchase": row.allow_purchase,
            "holiday_list": row.holiday_list,
            "default_warehouse": row.default_warehouse
        })
        
    participants.sort(key=lambda x: x["priority"])
    return participants

def get_intercompany_lead_time(from_company, to_company, item_code=None):
    """
    Looks up lead time between two companies. Specific item takes precedence over generic.
    """
    # 1. Try specific item
    if item_code:
        record = frappe.db.get_value(
            "MRP Inter Company Lead Time",
            {"from_company": from_company, "to_company": to_company, "item_code": item_code, "is_active": 1},
            ["lead_time_days", "day_type"],
            as_dict=True
        )
        if record:
            return record.lead_time_days or 2, record.day_type == "Dias Úteis"
            
    # 2. Try generic route (item_code is null or empty)
    records = frappe.db.sql("""
        SELECT lead_time_days, day_type FROM `tabMRP Inter Company Lead Time`
        WHERE from_company = %s AND to_company = %s AND (item_code IS NULL OR item_code = '') AND is_active = 1
        ORDER BY priority ASC LIMIT 1
    """, (from_company, to_company), as_dict=True)
    
    if records:
        return records[0].lead_time_days or 2, records[0].day_type == "Dias Úteis"
        
    return 2, True  # Default 2 working days fallback

def evaluate_multi_company_supply(item_code, target_company, target_warehouse, net_qty, need_date, company_group, stock_cache, horizon_start, allow_partial=True, has_local_bom=False):
    """
    Evaluates multi-company sourcing:
    1. First check available stock in partner companies.
    2. If stock exists and transfer can arrive in time -> Suggest Transfer.
    3. If no stock and target company has no local BOM, but partner can produce (has BOM) -> Suggest Partner Production + Transfer.
    
    Returns dict with decision or None.
    """
    if not company_group:
        return None
        
    participants = get_company_group_participants(company_group, exclude_company=target_company)
    if not participants:
        return None
        
    for partner in participants:
        p_company = partner["company"]
        
        # 1. Check Transfer from partner stock
        if partner["allow_transfer"]:
            avail_stock = stock_cache.get_available_qty(item_code, p_company)
            if avail_stock > 0:
                lead_time, is_working = get_intercompany_lead_time(p_company, target_company, item_code)
                transfer_date = get_working_days_prior(need_date, lead_time, p_company, partner["holiday_list"], is_working)
                
                # Check if transfer date is viable within planning window
                transfer_qty = min(avail_stock, net_qty) if allow_partial else (avail_stock if avail_stock >= net_qty else 0)
                if transfer_qty > 0 and getdate(transfer_date) >= getdate(horizon_start):
                    # Deduct from stock cache
                    stock_cache.consume_stock(item_code, p_company, transfer_qty)
                    p_warehouse = partner["default_warehouse"] or stock_cache.get_primary_warehouse(item_code, p_company)
                    
                    return {
                        "supply_type": "Transferência",
                        "from_company": p_company,
                        "from_warehouse": p_warehouse,
                        "to_company": target_company,
                        "to_warehouse": target_warehouse,
                        "suggested_qty": transfer_qty,
                        "lead_time_days": lead_time,
                        "supply_date": transfer_date,
                        "need_date": need_date,
                        "partner_production_needed": False,
                        "situation": f"Transferência de estoque disponível da empresa {p_company}"
                    }
                    
        # 2. Check Partner Production + Transfer (Section 63: only when local company has no productive structure)
        if partner["allow_production"] and not has_local_bom:
            # Check if partner company has an active BOM for this item
            bom = frappe.db.get_value("BOM", {"item": item_code, "is_active": 1, "is_default": 1, "company": p_company}, "name")
            if not bom:
                bom = frappe.db.get_value("BOM", {"item": item_code, "is_active": 1, "is_default": 1}, "name")
                
            if bom:
                trans_lead, trans_working = get_intercompany_lead_time(p_company, target_company, item_code)
                transfer_date = get_working_days_prior(need_date, trans_lead, p_company, partner["holiday_list"], trans_working)
                
                prod_lead = frappe.db.get_value("Item", item_code, "lead_time_days") or 1
                prod_start_date = get_working_days_prior(transfer_date, prod_lead, p_company, partner["holiday_list"], True)
                
                p_warehouse = partner["default_warehouse"] or stock_cache.get_primary_warehouse(item_code, p_company)
                
                return {
                    "supply_type": "Transferência",
                    "from_company": p_company,
                    "from_warehouse": p_warehouse,
                    "to_company": target_company,
                    "to_warehouse": target_warehouse,
                    "suggested_qty": net_qty,
                    "lead_time_days": trans_lead + prod_lead,
                    "supply_date": prod_start_date,
                    "transfer_date": transfer_date,
                    "need_date": need_date,
                    "bom_no": bom,
                    "partner_production_needed": True,
                    "producing_company": p_company,
                    "situation": f"Produção na parceira {p_company} seguida de Transferência"
                }
                
    return None
