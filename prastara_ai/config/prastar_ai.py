from frappe import _


def get_data():
	return [
		{
			"label": _("Workspace"),
			"items": [
				{
					"type": "url",
					"name": _("Sales Workspace"),
					"url": "/sales-workspace",
					"description": _("Open the custom Prastar AI sales workspace."),
				},
			],
		},
		{
			"label": _("Configuration"),
			"items": [
				{
					"type": "doctype",
					"name": "AI Estimation Settings",
					"description": _("Store the OpenAI API key and default AI model securely."),
				},
			],
		},
		{
			"label": _("Operations"),
			"items": [
				{
					"type": "doctype",
					"name": "AI Estimation",
					"description": _("Manage AI-generated estimation drafts."),
				},
			],
		},
	]
