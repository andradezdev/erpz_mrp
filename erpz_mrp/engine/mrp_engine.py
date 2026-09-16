# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

import time
import math
from collections import defaultdict
from datetime import datetime, timedelta
import frappe
from frappe.utils import getdate, now_datetime, cint, flt
from erpz_mrp.engine.calendar_utils import get_working_days_prior, calculate_delay_days
from erpz_mrp.engine.multi_company import evaluate_multi_company_supply
from erpz_mrp.engine.aglutination import aglutinate_results

class StockCache:
    """In-memory cache for fast stock lookups and simulated allocations."""
    def __init__(self):
        self.stock = defaultdict(float) # (item_code, company, warehouse) -> actual_qty - reserved_qty
        self.raw_actual = defaultdict(float)
        self.raw_reserved = defaultdict(float)
        self.primary_warehouse = {} # (item_code, company) -> warehouse

    def load_bins(self, item_codes=None, companies=None):
        conditions = ["1=1"]
        values = []
        if item_codes:
            conditions.append("bin.item_code IN %s")
            values.append(tuple(item_codes))
            
        sql = f"""
            SELECT bin.item_code, bin.warehouse, bin.actual_qty, bin.reserved_qty,
                   bin.reserved_qty_for_production, bin.reserved_qty_for_production_plan,
                   wh.company
            FROM `tabBin` bin
            INNER JOIN `tabWarehouse` wh ON bin.warehouse = wh.name
            WHERE {" AND ".join(conditions)}
        """
        if values:
            rows = frappe.db.sql(sql, tuple(values), as_dict=True)
        else:
            rows = frappe.db.sql(sql, as_dict=True)
        for r in rows:
            company = r.company
            item = r.item_code
            wh = r.warehouse
            
            # Reserved = sales reservation + production reservation
            total_reserved = flt(r.reserved_qty) + flt(r.reserved_qty_for_production) + flt(r.reserved_qty_for_production_plan)
            avail = max(0.0, flt(r.actual_qty))
            
            key = (item, company, wh)
            self.stock[key] = avail
            self.raw_actual[key] = flt(r.actual_qty)
            self.raw_reserved[key] = total_reserved
            
            if (item, company) not in self.primary_warehouse:
                self.primary_warehouse[(item, company)] = wh

    def get_available_qty(self, item_code, company, warehouse=None):
        if warehouse:
            return self.stock.get((item_code, company, warehouse), 0.0)
        # Sum across all warehouses of company
        total = 0.0
        for (i, c, w), qty in self.stock.items():
            if i == item_code and c == company:
                total += qty
        return total

    def consume_stock(self, item_code, company, qty, warehouse=None):
        if warehouse:
            key = (item_code, company, warehouse)
            avail = self.stock.get(key, 0.0)
            deduct = min(avail, qty)
            self.stock[key] = avail - deduct
            return deduct
            
        # Deduct across warehouses
        remaining = qty
        for (i, c, w) in list(self.stock.keys()):
            if i == item_code and c == company and remaining > 0:
                avail = self.stock[(i, c, w)]
                deduct = min(avail, remaining)
                self.stock[(i, c, w)] = avail - deduct
                remaining -= deduct
        return qty - remaining

    def get_primary_warehouse(self, item_code, company):
        return self.primary_warehouse.get((item_code, company))

class BOMCache:
    """Loads BOM details, explodes components, and detects recursion cycles."""
    def __init__(self):
        self.boms = {} # item_code -> BOM header dict
        self.bom_items = defaultdict(list) # bom_no -> list of items
        self.cycles_detected = []

    def load_boms(self):
        active_boms = frappe.db.sql("""
            SELECT name, item, quantity, is_default, is_active, company, with_operations, process_loss_percentage
            FROM `tabBOM`
            WHERE is_active = 1 AND is_default = 1 AND docstatus = 1
        """, as_dict=True)
        
        for b in active_boms:
            # Can have one default per company or global default
            if b.company:
                self.boms[(b.item, b.company)] = b
            if b.item not in self.boms:
                self.boms[b.item] = b
                
        # Load items
        items = frappe.db.sql("""
            SELECT parent, item_code, item_name, qty, stock_qty, stock_uom, qty_consumed_per_unit
            FROM `tabBOM Item`
            WHERE docstatus = 1
        """, as_dict=True)
        for it in items:
            self.bom_items[it.parent].append(it)

    def get_bom(self, item_code, company=None):
        if company and (item_code, company) in self.boms:
            return self.boms[(item_code, company)]
        return self.boms.get(item_code)

    def get_components(self, bom_name):
        return self.bom_items.get(bom_name, [])

    def check_cycle(self, item_code, call_chain):
        if item_code in call_chain:
            cycle_str = " -> ".join(call_chain + [item_code])
            if cycle_str not in self.cycles_detected:
                self.cycles_detected.append(cycle_str)
            return True
        return False

class MRPEngine:
    def __init__(self, ticket_name):
        self.ticket_name = ticket_name
        self.ticket = frappe.get_doc("MRP Ticket", ticket_name)
        self.settings = frappe.get_single("MRP Settings")
        
        self.stock_cache = StockCache()
        self.bom_cache = BOMCache()
        
        # Memory structures
        self.items_meta = {} # item_code -> dict
        self.demands = []    # list of demand dicts
        self.planned_inflows = [] # list of inflow dicts
        self.results = []    # list of suggestion result dicts
        self.timelines = []  # list of daily timeline dicts
        self.traceability = [] # list of hierarchical traceability nodes
        self.logs = []       # list of log dicts
        self.aglutination_links = []
        
        # Pre-calculated company holiday lists
        self.company_holiday_lists = {}

    def log(self, log_type, message, item_code=None, details=None):
        self.logs.append({
            "mrp_ticket": self.ticket_name,
            "log_type": log_type,
            "item_code": item_code,
            "message": message,
            "details": details or "",
            "logged_at": now_datetime()
        })

    def run(self):
        start_time = time.time()
        self.ticket.db_set("status", "Processando")
        frappe.db.commit()

        try:
            # 1. Parameter Validation
            if not self.ticket.from_date or not self.ticket.to_date:
                raise frappe.ValidationError("Datas inicial e final do horizonte são obrigatórias.")
            if getdate(self.ticket.to_date) < getdate(self.ticket.from_date):
                raise frappe.ValidationError("Data final não pode ser menor que a data inicial.")
                
            # 2. Clear previous results for this ticket if re-running (preserve Manual demands)
            frappe.db.delete("MRP Demand", {"mrp_ticket": self.ticket_name, "source_type": ["!=", "Manual"]})
            frappe.db.delete("MRP Stock", {"mrp_ticket": self.ticket_name})
            frappe.db.delete("MRP Planned Inflow", {"mrp_ticket": self.ticket_name})
            frappe.db.delete("MRP Result", {"mrp_ticket": self.ticket_name})
            frappe.db.delete("MRP Timeline", {"mrp_ticket": self.ticket_name})
            frappe.db.delete("MRP Traceability", {"mrp_ticket": self.ticket_name})
            frappe.db.delete("MRP Log", {"mrp_ticket": self.ticket_name})
            frappe.db.delete("MRP Aglutination Link", {"mrp_ticket": self.ticket_name})

            # 3. Load Item Master Parameters
            self.load_items_master()
            
            # 4. Load BOM structures
            self.bom_cache.load_boms()
            
            # 5. Load Stock Snapshots
            self.stock_cache.load_bins()
            self.record_stock_snapshots()
            
            # 6. Load Demands
            self.load_demands()
            
            # 7. Load Scheduled Inflows
            self.load_scheduled_inflows()
            
            # 7. Process Timeline and Calculate Net Requirements
            self.calculate_requirements()
            
            # 8. Aglutination if enabled
            if self.ticket.aglutinate_demands:
                self.results, self.aglutination_links = aglutinate_results(
                    self.results,
                    self.ticket.aglutination_period or "Semanal",
                    apply_lot_sizing_callback=self.apply_lot_sizing
                )
                
            # 9. Persist all generated records to database
            self.persist_all()
            
            # 10. Update Ticket status and metrics
            exec_time = round(time.time() - start_time, 2)
            total_suggestions = len(self.results)
            total_produced = sum(1 for r in self.results if r.get("supply_type") == "Produção")
            total_purchased = sum(1 for r in self.results if r.get("supply_type") == "Compra")
            total_transferred = sum(1 for r in self.results if r.get("supply_type") == "Transferência")
            has_errors = any(l["log_type"] in ("Erro", "Ciclo Circular") for l in self.logs)
            
            final_status = "Com Inconsistências" if has_errors else ("Calculado" if not self.ticket.is_simulation else "Calculado (Simulação)")
            
            self.ticket.db_set({
                "status": final_status,
                "total_demands": len(self.demands),
                "total_suggestions": total_suggestions,
                "total_produced": total_produced,
                "total_purchased": total_purchased,
                "total_transferred": total_transferred,
                "total_inconsistencies": len(self.logs),
                "execution_time_seconds": exec_time,
                "calculated_on": now_datetime(),
                "calculated_by": frappe.session.user
            })
            frappe.db.commit()
            
            return {
                "status": final_status,
                "total_suggestions": total_suggestions,
                "execution_time": exec_time
            }
            
        except Exception as e:
            frappe.db.rollback()
            self.log("Erro", f"Falha na execução do cálculo MRP: {str(e)}", details=frappe.get_traceback())
            self.persist_logs()
            self.ticket.db_set("status", "Com Inconsistências")
            frappe.db.commit()
            raise e

    def load_items_master(self):
        conditions = ["disabled = 0"]
        values = []
        if self.ticket.item_filter:
            conditions.append("name = %s")
            values.append(self.ticket.item_filter)
        if self.ticket.item_group_filter:
            conditions.append("item_group = %s")
            values.append(self.ticket.item_group_filter)
            
        extra_cols = ""
        if frappe.db.has_column("Item", "custom_mrp_min_stock"):
            extra_cols += ", custom_mrp_min_stock"
        if frappe.db.has_column("Item", "custom_mrp_reorder_point"):
            extra_cols += ", custom_mrp_reorder_point"
        if frappe.db.has_column("Item", "custom_mrp_safety_stock"):
            extra_cols += ", custom_mrp_safety_stock"
        if frappe.db.has_column("Item", "custom_mrp_total_safety_threshold"):
            extra_cols += ", custom_mrp_total_safety_threshold"

        sql = f"""
            SELECT name, item_name, description, stock_uom, item_group,
                   is_stock_item, is_purchase_item, is_sub_contracted_item,
                   min_order_qty, safety_stock, lead_time_days, default_bom
                   {extra_cols}
            FROM `tabItem`
            WHERE {" AND ".join(conditions)}
        """
        if values:
            items = frappe.db.sql(sql, tuple(values), as_dict=True)
        else:
            items = frappe.db.sql(sql, as_dict=True)
        
        for it in items:
            self.items_meta[it.name] = it

    def record_stock_snapshots(self):
        """Persists the initial stock position considered in the MRP run."""
        records = []
        for (item_code, company, wh), qty in self.stock_cache.stock.items():
            if item_code in self.items_meta:
                records.append([
                    frappe.generate_hash(length=12),
                    self.ticket_name,
                    item_code,
                    company,
                    wh,
                    self.stock_cache.raw_actual[(item_code, company, wh)],
                    self.stock_cache.raw_reserved[(item_code, company, wh)],
                    qty,
                    flt(self.items_meta[item_code].get("safety_stock", 0.0))
                ])
        if records:
            cols = ["name", "mrp_ticket", "item_code", "company", "warehouse", "actual_qty", "reserved_qty", "available_qty", "safety_stock"]
            frappe.db.bulk_insert("MRP Stock", cols, records)

    def load_demands(self):
        from_d = self.ticket.from_date
        to_d = self.ticket.to_date
        company = self.ticket.company
        
        # 1. Sales Orders
        if self.ticket.consider_sales_orders:
            so_rows = frappe.db.sql("""
                SELECT so.name as so_name, so.company, so.transaction_date,
                       soi.item_code, soi.item_name, soi.delivery_date,
                       soi.qty, soi.delivered_qty, soi.warehouse, soi.stock_uom, soi.name as row_name
                FROM `tabSales Order` so
                INNER JOIN `tabSales Order Item` soi ON soi.parent = so.name
                WHERE so.docstatus = 1 AND so.status NOT IN ('Closed', 'Completed', 'Cancelled')
                  AND (so.company = %s OR %s = 1)
                  AND soi.delivery_date <= %s
                  AND soi.delivered_qty < soi.qty
            """, (company, 1 if self.ticket.allow_multi_company else 0, to_d), as_dict=True)
            
            for r in so_rows:
                pending_qty = flt(r.qty) - flt(r.delivered_qty)
                d_date = max(getdate(r.delivery_date), getdate(from_d))
                self.demands.append({
                    "item_code": r.item_code,
                    "item_name": r.item_name,
                    "company": r.company,
                    "warehouse": r.warehouse,
                    "demand_date": d_date,
                    "quantity": pending_qty,
                    "uom": r.stock_uom,
                    "source_type": "Sales Order",
                    "source_name": r.so_name,
                    "source_item_row": r.row_name,
                    "origin_item": r.item_code,
                    "bom_level": 0
                })

        # 2. Material Requests (Material Issue)
        if self.ticket.consider_material_requests:
            mr_rows = frappe.db.sql("""
                SELECT mr.name as mr_name, mr.company,
                       mri.item_code, mri.item_name, mri.schedule_date,
                       mri.qty, mri.ordered_qty, mri.warehouse, mri.uom, mri.name as row_name
                FROM `tabMaterial Request` mr
                INNER JOIN `tabMaterial Request Item` mri ON mri.parent = mr.name
                WHERE mr.docstatus = 1 AND mr.status NOT IN ('Stopped', 'Cancelled', 'Transferred')
                  AND mr.material_request_type = 'Material Issue'
                  AND (mr.company = %s OR %s = 1)
                  AND mri.schedule_date <= %s
                  AND mri.ordered_qty < mri.qty
            """, (company, 1 if self.ticket.allow_multi_company else 0, to_d), as_dict=True)
            
            for r in mr_rows:
                pending_qty = flt(r.qty) - flt(r.ordered_qty)
                d_date = max(getdate(r.schedule_date), getdate(from_d))
                self.demands.append({
                    "item_code": r.item_code,
                    "item_name": r.item_name,
                    "company": r.company,
                    "warehouse": r.warehouse,
                    "demand_date": d_date,
                    "quantity": pending_qty,
                    "uom": r.uom,
                    "source_type": "Material Request",
                    "source_name": r.mr_name,
                    "source_item_row": r.row_name,
                    "origin_item": r.item_code,
                    "bom_level": 0
                })

        # 3. Manual Demands (Imported via Excel or added manually)
        manual_rows = frappe.get_all(
            "MRP Demand",
            filters={"mrp_ticket": self.ticket_name, "source_type": "Manual"},
            fields=["item_code", "item_name", "company", "warehouse", "demand_date", "quantity", "uom", "source_type", "source_name", "source_item_row", "origin_item"]
        )
        for m in manual_rows:
            d_date = max(getdate(m.demand_date), getdate(from_d))
            self.demands.append({
                "item_code": m.item_code,
                "item_name": m.item_name,
                "company": m.company or company,
                "warehouse": m.warehouse,
                "demand_date": d_date,
                "quantity": flt(m.quantity),
                "uom": m.uom,
                "source_type": "Manual",
                "source_name": m.source_name or "Demanda Manual",
                "source_item_row": m.get("source_item_row"),
                "origin_item": m.item_code,
                "bom_level": 0
            })

    def load_scheduled_inflows(self):
        from_d = self.ticket.from_date
        to_d = self.ticket.to_date
        company = self.ticket.company

        # 1. Purchase Orders pending receipt
        if self.ticket.consider_purchase_orders:
            po_rows = frappe.db.sql("""
                SELECT po.name as po_name, po.company,
                       poi.item_code, poi.item_name, poi.schedule_date,
                       poi.qty, poi.received_qty, poi.warehouse
                FROM `tabPurchase Order` po
                INNER JOIN `tabPurchase Order Item` poi ON poi.parent = po.name
                WHERE po.docstatus = 1 AND po.status NOT IN ('Closed', 'Completed', 'Cancelled')
                  AND (po.company = %s OR %s = 1)
                  AND poi.schedule_date <= %s
                  AND poi.received_qty < poi.qty
            """, (company, 1 if self.ticket.allow_multi_company else 0, to_d), as_dict=True)
            
            for r in po_rows:
                pending_qty = flt(r.qty) - flt(r.received_qty)
                in_date = max(getdate(r.schedule_date), getdate(from_d))
                self.planned_inflows.append({
                    "item_code": r.item_code,
                    "company": r.company,
                    "warehouse": r.warehouse,
                    "expected_date": in_date,
                    "quantity": pending_qty,
                    "source_type": "Purchase Order",
                    "source_name": r.po_name
                })

        # 2. Work Orders pending completion
        if self.ticket.consider_work_orders:
            wo_rows = frappe.db.sql("""
                SELECT name as wo_name, company, production_item, planned_start_date,
                       expected_delivery_date, qty, produced_qty, fg_warehouse
                FROM `tabWork Order`
                WHERE docstatus = 1 AND status NOT IN ('Completed', 'Stopped', 'Cancelled')
                  AND (company = %s OR %s = 1)
                  AND (expected_delivery_date <= %s OR planned_start_date <= %s)
                  AND produced_qty < qty
            """, (company, 1 if self.ticket.allow_multi_company else 0, to_d, to_d), as_dict=True)
            
            for r in wo_rows:
                pending_qty = flt(r.qty) - flt(r.produced_qty)
                in_date = max(getdate(r.expected_delivery_date or r.planned_start_date), getdate(from_d))
                self.planned_inflows.append({
                    "item_code": r.production_item,
                    "company": r.company,
                    "warehouse": r.fg_warehouse,
                    "expected_date": in_date,
                    "quantity": pending_qty,
                    "source_type": "Work Order",
                    "source_name": r.wo_name
                })

    def apply_lot_sizing(self, item_code, net_qty):
        meta = self.items_meta.get(item_code, {})
        min_order_qty = flt(meta.get("min_order_qty", 0.0))
        qty = net_qty
        
        # Rule 10: Minimum Lot (Lote Mínimo)
        if min_order_qty > 0 and qty < min_order_qty:
            qty = min_order_qty
            
        # Rule 12: Multiples (Múltiplo de Abastecimento)
        # In ERPNext, batch size or custom multiple
        return qty

    def calculate_requirements(self):
        """
        Step-by-step MRP core calculation:
        1. Explode demands level-by-level (topological BOM hierarchy 0, 1, 2...).
        2. Construct daily timeline per item, company, and warehouse.
        3. Project balance: Saldo Projetado = Saldo Anterior + Entradas - Demandas.
        4. Detect shortage when Saldo < Safety Stock.
        5. Generate suggested orders (Produce, Buy, Transfer) with lead times.
        6. Feed component demands back into subsequent BOM levels.
        """
        pending_demands = list(self.demands)
        current_level = 0
        max_levels = 20 # Protection against deeply nested BOM explosions
        
        while pending_demands and current_level <= max_levels:
            # Group demands by item, company, warehouse
            level_demands = [d for d in pending_demands if d.get("bom_level", 0) == current_level]
            if not level_demands:
                # If there are remaining demands at higher levels, process next
                remaining_levels = [d.get("bom_level", 0) for d in pending_demands]
                if not remaining_levels:
                    break
                current_level = min(remaining_levels)
                level_demands = [d for d in pending_demands if d.get("bom_level", 0) == current_level]
                
            # Remove processed demands from queue
            pending_demands = [d for d in pending_demands if d not in level_demands]
            
            # Map items to process
            items_to_calc = set(d["item_code"] for d in level_demands)
            
            for item_code in items_to_calc:
                item_meta = self.items_meta.get(item_code)
                if not item_meta:
                    continue
                    
                item_dems = [d for d in level_demands if d["item_code"] == item_code]
                self.process_item_timeline(item_code, item_dems, pending_demands, current_level)
                
            current_level += 1

    def process_item_timeline(self, item_code, item_demands, pending_demands_queue, current_level):
        item_meta = self.items_meta.get(item_code, {})
        min_stock = flt(item_meta.get("custom_mrp_min_stock") or 0.0)
        reorder_point = flt(item_meta.get("custom_mrp_reorder_point") or 0.0)
        safety_stock_val = flt(item_meta.get("custom_mrp_safety_stock") or item_meta.get("safety_stock") or 0.0)
        critical_safety_threshold = reorder_point + safety_stock_val
        effective_safety_target = max(min_stock, critical_safety_threshold)
        if effective_safety_target <= 0 and self.ticket.consider_safety_stock:
            effective_safety_target = safety_stock_val

        lead_time = cint(item_meta.get("lead_time_days", 0))
        min_order_qty = flt(item_meta.get("min_order_qty", 0.0))
        
        # Check missing lead time setting
        if lead_time <= 0:
            act = self.settings.missing_lead_time_action or "Utilizar Lead Time Padrão"
            if act == "Utilizar Lead Time Padrão":
                lead_time = cint(self.settings.default_lead_time_days or 0)
            elif act == "Gerar Alerta":
                self.log("Sem Lead Time", f"Item {item_code} não possui Lead Time cadastrado.", item_code=item_code)
            elif act == "Bloquear Processamento":
                raise frappe.ValidationError(f"Item {item_code} não possui Lead Time cadastrado e a configuração exige bloqueio.")
                
        # Group demands and scheduled inflows by date and warehouse
        company = self.ticket.company
        primary_wh = self.stock_cache.get_primary_warehouse(item_code, company)
        
        # Initial stock available
        initial_avail = self.stock_cache.get_available_qty(item_code, company)
        running_balance = initial_avail
        
        # Dates in planning horizon
        from_d = getdate(self.ticket.from_date)
        to_d = getdate(self.ticket.to_date)
        num_days = (to_d - from_d).days + 1
        
        # Map inflows by date
        inflows_by_date = defaultdict(float)
        for inf in self.planned_inflows:
            if inf["item_code"] == item_code and inf["company"] == company:
                inflows_by_date[getdate(inf["expected_date"])] += flt(inf["quantity"])
                
        # Map demands by date
        demands_by_date = defaultdict(list)
        for dem in item_demands:
            demands_by_date[getdate(dem["demand_date"])].append(dem)
            
        for day_offset in range(num_days):
            cur_date = from_d + timedelta(days=day_offset)
            day_inflows = inflows_by_date.get(cur_date, 0.0)
            day_dem_list = demands_by_date.get(cur_date, [])
            day_outflows = sum(flt(d["quantity"]) for d in day_dem_list)
            
            day_initial_balance = running_balance
            projected = day_initial_balance + day_inflows - day_outflows
            
            has_shortage = False
            shortage_type = "Normal"
            shortage = 0.0
            suggested_inflow = 0.0
            
            # Check Rupturas e Níveis Críticos
            if projected < 0:
                has_shortage = True
                shortage_type = "Ruptura Total (Saldo Negativo)"
                shortage = (effective_safety_target - projected) if effective_safety_target > 0 else abs(projected)
            elif min_stock > 0 and projected <= min_stock:
                has_shortage = True
                shortage_type = "Abaixo do Estoque Mínimo"
                shortage = max(min_stock, effective_safety_target) - projected
            elif critical_safety_threshold > 0 and projected <= critical_safety_threshold:
                has_shortage = True
                shortage_type = "Abaixo do Ponto de Pedido + Segurança"
                shortage = critical_safety_threshold - projected
            elif self.ticket.consider_safety_stock and safety_stock_val > 0 and projected < safety_stock_val:
                has_shortage = True
                shortage_type = "Abaixo do Estoque de Segurança"
                shortage = safety_stock_val - projected

            if has_shortage:
                suggested_qty = self.apply_lot_sizing(item_code, shortage)
                suggested_inflow = suggested_qty
                running_balance = projected + suggested_inflow
                
                self.handle_shortage_suggestion(
                    item_code=item_code,
                    need_date=cur_date,
                    gross_demand=day_outflows,
                    net_qty=shortage,
                    suggested_qty=suggested_qty,
                    day_dem_list=day_dem_list,
                    lead_time=lead_time,
                    current_level=current_level,
                    pending_demands_queue=pending_demands_queue,
                    initial_stock=day_initial_balance,
                    planned_inflows=day_inflows,
                    projected_balance=projected,
                    safety_stock=safety_stock_val,
                    min_stock=min_stock,
                    reorder_point=reorder_point,
                    critical_threshold=critical_safety_threshold,
                    shortage_type=shortage_type
                )
            else:
                running_balance = projected
                
            # Record day in timeline
            self.timelines.append({
                "mrp_ticket": self.ticket_name,
                "item_code": item_code,
                "item_name": item_meta.get("item_name"),
                "company": company,
                "warehouse": primary_wh,
                "timeline_date": cur_date,
                "initial_balance": day_initial_balance,
                "inflows": day_inflows,
                "outflows": day_outflows,
                "projected_balance": projected,
                "safety_stock": safety_stock_val,
                "min_stock": min_stock,
                "reorder_point": reorder_point,
                "critical_threshold": critical_safety_threshold,
                "shortage_qty": shortage,
                "suggested_inflow": suggested_inflow,
                "has_shortage": 1 if has_shortage else 0,
                "shortage_type": shortage_type if has_shortage else ""
            })

    def handle_shortage_suggestion(self, item_code, need_date, gross_demand, net_qty, suggested_qty,
                                   day_dem_list, lead_time, current_level, pending_demands_queue,
                                   initial_stock, planned_inflows, projected_balance, safety_stock,
                                   min_stock=0.0, reorder_point=0.0, critical_threshold=0.0, shortage_type="Normal"):
        item_meta = self.items_meta.get(item_code, {})
        company = self.ticket.company
        primary_wh = self.stock_cache.get_primary_warehouse(item_code, company)
        
        # Check Local BOM
        bom = self.bom_cache.get_bom(item_code, company)
        has_local_bom = bool(bom)

        # 1. Multi-Company Evaluation
        multi_supply = None
        if self.ticket.allow_multi_company and self.ticket.company_group:
            multi_supply = evaluate_multi_company_supply(
                item_code=item_code,
                target_company=company,
                target_warehouse=primary_wh,
                net_qty=net_qty,
                need_date=need_date,
                company_group=self.ticket.company_group,
                stock_cache=self.stock_cache,
                horizon_start=self.ticket.from_date,
                allow_partial=self.ticket.allow_partial_supply,
                has_local_bom=has_local_bom
            )
            
        if multi_supply:
            # Transfer suggested from partner company
            supply_type = "Transferência"
            supply_date = multi_supply["supply_date"]
            from_company = multi_supply["from_company"]
            from_warehouse = multi_supply["from_warehouse"]
            situation = multi_supply["situation"]
            bom_no = multi_supply.get("bom_no")
            eff_lead_time = multi_supply["lead_time_days"]
        else:
            # Local Sourcing: Check if Produced (has BOM) or Purchased
            bom = self.bom_cache.get_bom(item_code, company)
            
            if bom:
                supply_type = "Produção"
                bom_no = bom.name
                if shortage_type and shortage_type != "Normal":
                    situation = f"{shortage_type} (Mín: {min_stock}, Gatilho: {critical_threshold})"
                elif gross_demand > 0:
                    situation = "Demanda de Pedido / Necessidade Líquida"
                else:
                    situation = "Manutenção dos Níveis de Segurança"
            else:
                # When item has NO valid BOM -> Automatically generate Purchase (Compra) via ERPNext Buying API
                supply_type = "Compra"
                bom_no = None
                if not item_meta.get("is_purchase_item") and item_meta.get("is_stock_item"):
                    situation = "Item sem estrutura (BOM) ativa -> Sugestão de Compra"
                    self.log("Sem Estrutura", f"Item {item_code} não possui BOM padrão ativa. Gerada sugestão de Compra no ERPNext.", item_code=item_code)
                elif shortage_type and shortage_type != "Normal":
                    situation = f"{shortage_type} (Mín: {min_stock}, Gatilho: {critical_threshold})"
                else:
                    situation = "Item de Compra / Matéria-prima"
                
            eff_lead_time = lead_time
            supply_date = get_working_days_prior(
                need_date,
                eff_lead_time,
                company=company,
                use_working_days=self.settings.use_working_days
            )
            from_company = None
            from_warehouse = None
            
        # Origin details
        origin_doc = day_dem_list[0] if day_dem_list else {}
        origin_doctype = origin_doc.get("source_type", "Manual")
        origin_name = origin_doc.get("source_name", "Planejamento")
        origin_item = origin_doc.get("origin_item", item_code)
        
        # Check delay
        delay = calculate_delay_days(supply_date)
        status = "Atrasado" if delay > 0 else "Pendente"
        
        result_dict = {
            "mrp_ticket": self.ticket_name,
            "item_code": item_code,
            "item_name": item_meta.get("item_name"),
            "company": company,
            "warehouse": primary_wh,
            "need_date": need_date,
            "supply_date": supply_date,
            "gross_demand": gross_demand,
            "initial_stock": initial_stock,
            "planned_inflows": planned_inflows,
            "projected_balance": projected_balance,
            "safety_stock": safety_stock,
            "min_stock": min_stock,
            "reorder_point": reorder_point,
            "critical_threshold": critical_threshold,
            "shortage_type": shortage_type,
            "net_requirement": net_qty,
            "suggested_qty": suggested_qty,
            "min_order_qty": flt(item_meta.get("min_order_qty", 0.0)),
            "lot_multiple": 0.0,
            "economic_order_qty": 0.0,
            "supply_type": supply_type,
            "origin_item": origin_item,
            "origin_doctype": origin_doctype,
            "origin_name": origin_name,
            "origin_date": origin_doc.get("demand_date", need_date),
            "bom_no": bom_no,
            "bom_level": current_level,
            "lead_time_days": eff_lead_time,
            "from_company": from_company,
            "from_warehouse": from_warehouse,
            "status": status,
            "situation": situation,
            "is_aglutinated": 0,
            "aglutinated_items_count": 1
        }
        self.results.append(result_dict)
        
        # Add to Traceability node
        self.traceability.append({
            "mrp_ticket": self.ticket_name,
            "demand_source_doctype": origin_doctype,
            "demand_source_name": origin_name,
            "root_item": origin_item,
            "parent_item": origin_item if origin_item != item_code else None,
            "child_item": item_code,
            "bom_level": current_level,
            "required_qty": net_qty,
            "allocated_qty": suggested_qty,
            "supply_type": supply_type,
            "from_company": from_company or company,
            "to_company": company,
            "need_date": need_date,
            "planned_start_date": supply_date,
            "target_doctype": "Work Order" if supply_type == "Produção" else ("Material Request" if supply_type == "Compra" else "Stock Entry"),
            "target_docname": "Sugestão",
            "status": "Planejado"
        })
        
        # 3. Explosão Multinível da Estrutura (BOM Recursion)
        # If Produced, explode components and push into queue for next level
        if supply_type == "Produção" and bom_no:
            components = self.bom_cache.get_components(bom_no)
            for comp in components:
                child_code = comp.item_code
                
                # Cycle Detection
                call_chain = [origin_item, item_code]
                if self.bom_cache.check_cycle(child_code, call_chain):
                    self.log("Ciclo Circular", f"Ciclo circular detectado ao explodir BOM: {' -> '.join(call_chain + [child_code])}", item_code=child_code)
                    continue
                    
                # Loss calculation (Section 19: Perdas / Scrap)
                bom_header = self.bom_cache.get_bom(item_code, company)
                scrap_pct = flt(bom_header.process_loss_percentage if bom_header else 0.0)
                qty_per = flt(comp.qty_consumed_per_unit or comp.qty or 1.0)
                component_need_qty = suggested_qty * qty_per * (1.0 + (scrap_pct / 100.0))
                
                # The component must be ready at the start of parent production
                component_need_date = supply_date
                
                pending_demands_queue.append({
                    "item_code": child_code,
                    "item_name": comp.item_name,
                    "company": company,
                    "warehouse": primary_wh,
                    "demand_date": component_need_date,
                    "quantity": component_need_qty,
                    "uom": comp.stock_uom,
                    "source_type": "BOM Dependent",
                    "source_name": f"Sugestão OP: {item_code}",
                    "source_item_row": comp.name,
                    "origin_item": origin_item,
                    "bom_level": current_level + 1
                })

    def persist_all(self):
        # 1. Demands (insert only auto-generated demands; manual demands are already saved)
        new_demands = [d for d in self.demands if d.get("source_type") != "Manual"]
        if new_demands:
            frappe.db.bulk_insert(
                "MRP Demand",
                ["name", "mrp_ticket", "item_code", "item_name", "company", "warehouse", "demand_date", "quantity", "uom", "source_type", "source_name", "source_item_row", "origin_item"],
                [[frappe.generate_hash(length=12), self.ticket_name, d["item_code"], d.get("item_name"), d["company"], d.get("warehouse"), d["demand_date"], d["quantity"], d.get("uom"), d["source_type"], d.get("source_name"), d.get("source_item_row"), d.get("origin_item")] for d in new_demands]
            )
            
        # 2. Planned Inflows
        if self.planned_inflows:
            frappe.db.bulk_insert(
                "MRP Planned Inflow",
                ["name", "mrp_ticket", "item_code", "company", "warehouse", "expected_date", "quantity", "source_type", "source_name"],
                [[frappe.generate_hash(length=12), self.ticket_name, inf["item_code"], inf["company"], inf.get("warehouse"), inf["expected_date"], inf["quantity"], inf["source_type"], inf.get("source_name")] for inf in self.planned_inflows]
            )
            
        # 3. Results
        if self.results:
            cols = [
                "name", "mrp_ticket", "item_code", "item_name", "company", "warehouse", "need_date", "supply_date",
                "gross_demand", "initial_stock", "planned_inflows", "projected_balance", "safety_stock",
                "min_stock", "reorder_point", "critical_threshold", "shortage_type",
                "net_requirement", "suggested_qty", "min_order_qty", "lot_multiple", "economic_order_qty",
                "supply_type", "origin_item", "origin_doctype", "origin_name", "origin_date", "bom_no",
                "bom_level", "lead_time_days", "from_company", "from_warehouse", "status", "situation",
                "is_aglutinated", "aglutinated_items_count"
            ]
            rows = []
            for r in self.results:
                rows.append([
                    frappe.generate_hash(length=12), self.ticket_name, r["item_code"], r.get("item_name"), r["company"], r.get("warehouse"),
                    r["need_date"], r["supply_date"], flt(r.get("gross_demand")), flt(r.get("initial_stock")),
                    flt(r.get("planned_inflows")), flt(r.get("projected_balance")), flt(r.get("safety_stock")),
                    flt(r.get("min_stock")), flt(r.get("reorder_point")), flt(r.get("critical_threshold")), r.get("shortage_type", ""),
                    flt(r.get("net_requirement")), flt(r.get("suggested_qty")), flt(r.get("min_order_qty")),
                    flt(r.get("lot_multiple")), flt(r.get("economic_order_qty")), r["supply_type"],
                    r.get("origin_item"), r.get("origin_doctype"), r.get("origin_name"), r.get("origin_date"),
                    r.get("bom_no"), cint(r.get("bom_level")), cint(r.get("lead_time_days")),
                    r.get("from_company"), r.get("from_warehouse"), r.get("status", "Pendente"),
                    r.get("situation"), cint(r.get("is_aglutinated")), cint(r.get("aglutinated_items_count", 1))
                ])
            frappe.db.bulk_insert("MRP Result", cols, rows)
            
        # 4. Timelines
        if self.timelines:
            t_cols = [
                "name", "mrp_ticket", "item_code", "item_name", "company", "warehouse", "timeline_date",
                "initial_balance", "inflows", "outflows", "projected_balance", "safety_stock",
                "min_stock", "reorder_point", "critical_threshold", "shortage_type",
                "shortage_qty", "suggested_inflow", "has_shortage"
            ]
            t_rows = []
            for t in self.timelines:
                t_rows.append([
                    frappe.generate_hash(length=12), self.ticket_name, t["item_code"], t.get("item_name"), t["company"], t.get("warehouse"),
                    t["timeline_date"], flt(t.get("initial_balance")), flt(t.get("inflows")), flt(t.get("outflows")),
                    flt(t.get("projected_balance")), flt(t.get("safety_stock")),
                    flt(t.get("min_stock")), flt(t.get("reorder_point")), flt(t.get("critical_threshold")), t.get("shortage_type", ""),
                    flt(t.get("shortage_qty")),
                    flt(t.get("suggested_inflow")), cint(t.get("has_shortage"))
                ])
            frappe.db.bulk_insert("MRP Timeline", t_cols, t_rows)
            
        # 5. Traceability
        if self.traceability:
            tr_cols = [
                "name", "mrp_ticket", "demand_source_doctype", "demand_source_name", "root_item", "parent_item",
                "child_item", "bom_level", "required_qty", "allocated_qty", "supply_type",
                "from_company", "to_company", "need_date", "planned_start_date", "target_doctype",
                "target_docname", "status"
            ]
            tr_rows = []
            for tr in self.traceability:
                tr_rows.append([
                    frappe.generate_hash(length=12), self.ticket_name, tr.get("demand_source_doctype"), tr.get("demand_source_name"),
                    tr.get("root_item"), tr.get("parent_item"), tr["child_item"], cint(tr.get("bom_level")),
                    flt(tr.get("required_qty")), flt(tr.get("allocated_qty")), tr.get("supply_type"),
                    tr.get("from_company"), tr.get("to_company"), tr.get("need_date"), tr.get("planned_start_date"),
                    tr.get("target_doctype"), tr.get("target_docname"), tr.get("status", "Planejado")
                ])
            frappe.db.bulk_insert("MRP Traceability", tr_cols, tr_rows)
            
        # 6. Aglutination Links
        if self.aglutination_links:
            # Query back generated MRP Results for this ticket to link IDs
            res_map = {}
            for r in frappe.db.get_all("MRP Result", filters={"mrp_ticket": self.ticket_name}, fields=["name", "item_code"]):
                res_map[r.item_code] = r.name
                
            ag_cols = ["name", "mrp_ticket", "mrp_result", "demand_source_doctype", "demand_source_name", "item_code", "allocated_qty", "demand_date"]
            ag_rows = []
            for ag in self.aglutination_links:
                ag_rows.append([
                    frappe.generate_hash(length=12),
                    self.ticket_name,
                    res_map.get(ag["item_code"]),
                    ag["demand_source_doctype"],
                    ag["demand_source_name"],
                    ag["item_code"],
                    flt(ag["allocated_qty"]),
                    ag["demand_date"]
                ])
            frappe.db.bulk_insert("MRP Aglutination Link", ag_cols, ag_rows)
            
        # 7. Logs
        self.persist_logs()

    def persist_logs(self):
        if self.logs:
            l_cols = ["name", "mrp_ticket", "log_type", "item_code", "message", "details", "logged_at"]
            l_rows = [[frappe.generate_hash(length=12), l["mrp_ticket"], l["log_type"], l.get("item_code"), l["message"], l.get("details", ""), l["logged_at"]] for l in self.logs]
            frappe.db.bulk_insert("MRP Log", l_cols, l_rows)
