# Copyright (c) 2026, ERPZ and contributors
# For license information, please see license.txt

from datetime import datetime, date, timedelta
import frappe
from frappe.utils import getdate, add_days

def get_holiday_list_for_company(company=None):
    if company:
        holidays_list = frappe.db.get_value("Company", company, "default_holiday_list")
        if holidays_list:
            return holidays_list
    
    # Check default in MRP Settings
    settings = frappe.get_single("MRP Settings")
    if settings.default_holiday_list:
        return settings.default_holiday_list
        
    return None

def get_holidays_set(holiday_list_name):
    if not holiday_list_name:
        return set()
    
    holidays = frappe.db.sql_list("""
        SELECT holiday_date FROM `tabHoliday`
        WHERE parent = %s
    """, holiday_list_name)
    
    return set(getdate(h) for h in holidays)

def get_working_days_prior(target_date, days, company=None, holiday_list_name=None, use_working_days=True):
    """
    Returns the date N working days prior to target_date.
    Skips weekends (Saturday, Sunday) and holidays if use_working_days is True.
    """
    current_date = getdate(target_date)
    if days <= 0:
        return current_date
        
    if not use_working_days:
        return current_date - timedelta(days=days)
        
    if not holiday_list_name:
        holiday_list_name = get_holiday_list_for_company(company)
        
    holidays = get_holidays_set(holiday_list_name)
    
    remaining_days = int(days)
    while remaining_days > 0:
        current_date -= timedelta(days=1)
        # Saturday is 5, Sunday is 6
        is_weekend = current_date.weekday() in (5, 6)
        is_holiday = current_date in holidays
        if not is_weekend and not is_holiday:
            remaining_days -= 1
            
    return current_date

def get_working_days_ahead(start_date, days, company=None, holiday_list_name=None, use_working_days=True):
    """
    Returns the date N working days after start_date.
    """
    current_date = getdate(start_date)
    if days <= 0:
        return current_date
        
    if not use_working_days:
        return current_date + timedelta(days=days)
        
    if not holiday_list_name:
        holiday_list_name = get_holiday_list_for_company(company)
        
    holidays = get_holidays_set(holiday_list_name)
    
    remaining_days = int(days)
    while remaining_days > 0:
        current_date += timedelta(days=1)
        is_weekend = current_date.weekday() in (5, 6)
        is_holiday = current_date in holidays
        if not is_weekend and not is_holiday:
            remaining_days -= 1
            
    return current_date

def calculate_delay_days(planned_date):
    """
    Returns the number of days delayed if planned_date is before today.
    """
    today = getdate()
    p_date = getdate(planned_date)
    if p_date < today:
        return (today - p_date).days
    return 0
