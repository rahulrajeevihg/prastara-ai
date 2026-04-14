frappe.ui.form.on("AI Estimation Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test OpenAI Connection"), () => {
			frappe.call({
				method: "prastar_ai.prastar_ai.doctype.ai_estimation_settings.ai_estimation_settings.test_openai_connection",
				freeze: true,
				freeze_message: __("Testing OpenAI connection..."),
				callback: (response) => {
					if (response.exc) {
						frappe.msgprint({
							title: __("Connection Error"),
							message: __("An unexpected server error occurred. Check the error log."),
							indicator: "red",
						});
						return;
					}
					const result = response.message;
					if (result.status === "success") {
						frappe.show_alert({
							message: result.message || __("Connected to OpenAI successfully!"),
							indicator: "green",
						});
					} else {
						frappe.msgprint({
							title: __("OpenAI Connection Failed"),
							message: result.message || __("Unknown error"),
							indicator: "red",
						});
					}
				},
			});
		});
	},
});
