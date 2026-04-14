frappe.ui.form.on("AI Estimation Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test OpenAI Connection"), () => {
			frappe.call({
				method: "prastar_ai.prastar_ai.doctype.ai_estimation_settings.ai_estimation_settings.test_openai_connection",
				freeze: true,
				freeze_message: __("Testing OpenAI connection..."),
				callback: (response) => {
					if (!response.exc) {
						frappe.show_alert({
							message: response.message.message || __("Connection successful"),
							indicator: "green",
						});
					}
				},
			});
		});
	},
});
