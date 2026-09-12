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
