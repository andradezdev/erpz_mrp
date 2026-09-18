# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

from datetime import date
from frappe.utils import getdate
from collections import defaultdict

def get_bucket_key(dt, periodicity="Semanal"):
    """
    Returns grouping key for a given date based on periodicity:
    - Diária: (YYYY-MM-DD)
    - Semanal: (YYYY, ISO-Week)
    - Quinzenal: (YYYY, MM, 1 if day <= 15 else 2)
    - Mensal: (YYYY, MM)
    """
    d = getdate(dt)
    if periodicity == "Diária":
        return ("DAY", d.strftime("%Y-%m-%d"))
    elif periodicity == "Semanal":
        iso_year, iso_week, _ = d.isocalendar()
        return ("WEEK", f"{iso_year}-W{iso_week:02d}")
    elif periodicity == "Quinzenal":
        fortnight = 1 if d.day <= 15 else 2
        return ("FORTNIGHT", f"{d.year}-{d.month:02d}-Q{fortnight}")
    elif periodicity == "Mensal":
        return ("MONTH", f"{d.year}-{d.month:02d}")
    return ("ALL", "all")

def aglutinate_results(results_list, periodicity="Semanal", apply_lot_sizing_callback=None):
    """
    Consolida sugestões de suprimento. Se configurado para Não Aglutinar, mantém a relação 1:1 estrita
    entre cada Pedido de Venda e sua respectiva Ordem de Produção/Compra.
    """
    if "Não Aglutinar" in periodicity or "Sem Aglutinação" in periodicity or periodicity == "Não Aglutinar":
        for r in results_list:
            r["is_aglutinated"] = 0
            r["aglutinated_items_count"] = 1
        return results_list, []
    grouped = defaultdict(list)
    
    for res in results_list:
        # Group by item, company, warehouse, supply_type, bom_no, and time bucket
        bucket = get_bucket_key(res.get("supply_date") or res.get("need_date"), periodicity)
        group_key = (
            res.get("item_code"),
            res.get("company"),
            res.get("warehouse"),
            res.get("supply_type"),
            res.get("bom_no"),
            bucket
        )
        grouped[group_key].append(res)
        
    consolidated_results = []
    aglutination_links = []
    
    for group_key, items in grouped.items():
        if len(items) == 1:
            # Only one demand in this period, no need to aglutinate
            item = items[0]
            item["is_aglutinated"] = 0
            item["aglutinated_items_count"] = 1
            consolidated_results.append(item)
            continue
            
        # Multiple demands in the same period -> Aglutinate into one single Order Suggestion!
        first = items[0]
        total_demand = sum(x.get("gross_demand", 0) for x in items)
        total_net = sum(x.get("net_requirement", 0) for x in items)
        
        # Base suggested qty
        total_suggested = sum(x.get("suggested_qty", 0) for x in items)
        
        # If lot sizing callback provided, re-evaluate on total net requirement
        if apply_lot_sizing_callback:
            total_suggested = apply_lot_sizing_callback(first["item_code"], total_net)
            
        # Earliest supply date and earliest need date to ensure zero delays
        earliest_supply_date = min(getdate(x["supply_date"]) for x in items if x.get("supply_date"))
        earliest_need_date = min(getdate(x["need_date"]) for x in items if x.get("need_date"))
        
        # Combined situation message
        origins_summary = ", ".join(filter(None, [x.get("origin_name") for x in items[:3]]))
        if len(items) > 3:
            origins_summary += f" +{len(items)-3} outros"
            
        consolidated_doc = dict(first)
        consolidated_doc.update({
            "gross_demand": total_demand,
            "net_requirement": total_net,
            "suggested_qty": total_suggested,
            "need_date": earliest_need_date,
            "supply_date": earliest_supply_date,
            "is_aglutinated": 1,
            "aglutinated_items_count": len(items),
            "origin_doctype": "Aglutinado",
            "origin_name": f"Aglutinação {periodicity}: {origins_summary}",
            "situation": f"Ordem consolidada ({periodicity}) atendendo {len(items)} demandas ({origins_summary})"
        })
        
        consolidated_results.append(consolidated_doc)
        
        # Record aglutination links for each individual origin
        for it in items:
            aglutination_links.append({
                "item_code": it.get("item_code"),
                "demand_source_doctype": it.get("origin_doctype"),
                "demand_source_name": it.get("origin_name"),
                "allocated_qty": it.get("suggested_qty"),
                "demand_date": it.get("need_date"),
                "temp_group_id": id(consolidated_doc)
            })
            
    return consolidated_results, aglutination_links
