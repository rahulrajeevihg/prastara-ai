from __future__ import annotations
import frappe


def create_custom_fields():
	"""Create the cp_custom_pin custom field on the Customer doctype."""
	if frappe.db.exists("Custom Field", {"dt": "Customer", "fieldname": "cp_custom_pin"}):
		print("cp_custom_pin custom field already exists — skipping.")
		return

	frappe.get_doc({
		"doctype": "Custom Field",
		"dt": "Customer",
		"fieldname": "cp_custom_pin",
		"label": "Portal Custom PIN",
		"fieldtype": "Small Text",
		"insert_after": "tax_id",
		"description": "If set, overrides the rule-based portal password for this customer. Leave blank to use the global Customer Portal Settings rules.",
		"permlevel": 0,
	}).insert(ignore_permissions=True)

	frappe.db.commit()
	print("Created cp_custom_pin custom field on Customer.")
