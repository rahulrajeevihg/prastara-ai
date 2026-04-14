/* ============================================================
   Prastar AI — Import from Email  (Opportunity)
   Complete UI rewrite. Backend API calls are unchanged.
   ============================================================ */

const PEI_STYLE_ID = "prastar-pei-styles";

const ANALYSIS_STAGES = [
	__("Reading attachments"),
	__("Extracting contact details"),
	__("Understanding project scope"),
	__("Checking existing leads"),
	__("Checking existing customers"),
];

// ── Frappe hook ───────────────────────────────────────────────────────────────

frappe.ui.form.on("Opportunity", {
	refresh(frm) {
		frm.add_custom_button(__("Import from Email"), () => pei_open_dialog());
	},
});

// ── Dialog entry point ────────────────────────────────────────────────────────

function pei_open_dialog() {
	pei_inject_styles();

	const state = {
		step: "attach",        // "attach" | "analyzing" | "review"
		files: [],
		analysis: null,
		stageIndex: 0,
		stageTimer: null,
		formValues: {
			email_subject:    "",
			company_name:     "",
			contact_person:   "",
			contact_email:    "",
			mobile_no:        "",
			phone:            "",
			website:          "",
			project_title:    "",
			project_location: "",
			scope_summary:    "",
			notes:            "",
		},
		selectedParty: { type: "Lead", name: "" },  // name="" → create new Lead
	};

	const dialog = new frappe.ui.Dialog({
		title: __("Import from Email"),
		size: "large",
		fields: [{ fieldname: "wizard_html", fieldtype: "HTML" }],
		primary_action_label: __("Analyze →"),
		primary_action() {
			if (state.step === "attach")   pei_run_analysis(dialog, state);
			if (state.step === "review")   pei_create_opportunity(dialog, state);
		},
	});

	dialog.show();
	dialog.$wrapper.addClass("pei-modal");
	dialog.$wrapper.on("hidden.bs.modal", () => pei_stop_feed(state));
	pei_render(dialog, state);
}

// ── Render ────────────────────────────────────────────────────────────────────

function pei_render(dialog, state) {
	const $wrap = dialog.get_field("wizard_html").$wrapper;

	$wrap.html(`
		<div class="pei-wizard">
			${pei_stepper(state)}
			<div class="pei-body">
				${state.step === "attach"    ? pei_attach_html(state)    : ""}
				${state.step === "analyzing" ? pei_analyzing_html(state) : ""}
				${state.step === "review"    ? pei_review_html(state)    : ""}
			</div>
		</div>
	`);

	if (state.step === "attach")   pei_bind_attach($wrap, dialog, state);
	if (state.step === "review")   pei_bind_review($wrap, dialog, state);
}

// ── Step indicator ────────────────────────────────────────────────────────────

function pei_stepper(state) {
	const steps = [
		{ key: "attach",    label: __("Attach")  },
		{ key: "analyzing", label: __("Analyze") },
		{ key: "review",    label: __("Review")  },
	];
	const idx = steps.findIndex(s => s.key === state.step);

	return `
		<div class="pei-stepper">
			${steps.map((step, i) => {
				const done   = i < idx;
				const active = i === idx;
				return `
					${i > 0 ? `<div class="pei-step-line${done ? " done" : ""}"></div>` : ""}
					<div class="pei-step${active ? " active" : ""}${done ? " done" : ""}">
						<div class="pei-step-dot">${done ? "✓" : i + 1}</div>
						<div class="pei-step-lbl">${step.label}</div>
					</div>
				`;
			}).join("")}
		</div>
	`;
}

// ── Step 1: Attach ────────────────────────────────────────────────────────────

function pei_attach_html(state) {
	const fileList = state.files.length ? `
		<div class="pei-file-list">
			${state.files.map((f, i) => `
				<div class="pei-file-row">
					<div class="pei-file-icon">${pei_file_icon(f.file_name)}</div>
					<div class="pei-file-meta">
						<div class="pei-file-name">${frappe.utils.escape_html(f.file_name || f.file_url)}</div>
						<div class="pei-file-ok">✓ ${__("Uploaded and ready")}</div>
					</div>
					<a class="pei-file-view" href="${frappe.utils.escape_html(f.file_url)}" target="_blank" rel="noreferrer">${__("View")}</a>
					<button class="pei-file-del" type="button" data-idx="${i}" title="${__("Remove")}">
						<svg width="12" height="12" viewBox="0 0 12 12" fill="none">
							<path d="M1 1l10 10M11 1L1 11" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
						</svg>
					</button>
				</div>
			`).join("")}
		</div>
	` : "";

	return `
		<div class="pei-attach">
			<div class="pei-section-intro">
				<h3 class="pei-panel-title">${__("Attach the email")}</h3>
				<p class="pei-panel-copy">${__("Upload screenshots or a PDF export of the email. The AI will extract contact details, project scope and check your existing CRM records automatically.")}</p>
			</div>

			<div class="pei-dropzone" data-pei="open-upload">
				<div class="pei-dz-icon">
					<svg width="48" height="48" viewBox="0 0 48 48" fill="none">
						<rect width="48" height="48" rx="14" fill="rgba(79,70,229,0.09)"/>
						<path d="M24 14l-9 9h6v10h6V23h6l-9-9z" fill="#4f46e5"/>
						<rect x="13" y="33" width="22" height="3" rx="1.5" fill="#4f46e5" opacity="0.3"/>
					</svg>
				</div>
				<div class="pei-dz-label">
					<strong>${state.files.length ? __("Add more files") : __("Drop files here to upload")}</strong>
					<span>${__("or")} <span class="pei-dz-link">${__("browse")}</span></span>
				</div>
				<div class="pei-dz-formats">PNG &nbsp;·&nbsp; JPG &nbsp;·&nbsp; WEBP &nbsp;·&nbsp; PDF</div>
			</div>

			${fileList}
		</div>
	`;
}

function pei_file_icon(name) {
	const ext = (name || "").split(".").pop().toLowerCase();
	if (ext === "pdf") {
		return `<svg width="32" height="32" viewBox="0 0 32 32" fill="none">
			<rect width="32" height="32" rx="8" fill="rgba(220,38,38,0.10)"/>
			<text x="16" y="21" text-anchor="middle" font-size="10" font-weight="800" fill="#dc2626" font-family="sans-serif">PDF</text>
		</svg>`;
	}
	return `<svg width="32" height="32" viewBox="0 0 32 32" fill="none">
		<rect width="32" height="32" rx="8" fill="rgba(79,70,229,0.10)"/>
		<rect x="8" y="8" width="16" height="16" rx="3" fill="#818cf8" opacity="0.5"/>
		<circle cx="12" cy="12" r="2.5" fill="#4f46e5"/>
		<path d="M8 22l6-6 3.5 3.5 2-2 4.5 4.5" stroke="#4f46e5" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
	</svg>`;
}

function pei_bind_attach($wrap, dialog, state) {
	$wrap.find("[data-pei='open-upload']").on("click", () => pei_open_uploader(dialog, state));
	$wrap.find(".pei-file-del").on("click", function (e) {
		e.stopPropagation();
		const idx = parseInt($(this).attr("data-idx"), 10);
		state.files.splice(idx, 1);
		pei_render(dialog, state);
	});
}

function pei_open_uploader(dialog, state) {
	new frappe.ui.FileUploader({
		allow_multiple: true,
		dialog_title: __("Upload Email Attachment"),
		restrictions: { allowed_file_types: [".png", ".jpg", ".jpeg", ".webp", ".pdf"] },
		on_success(file_doc) {
			state.files.push(file_doc);
			pei_render(dialog, state);
		},
	});
}

// ── Step 2: Analyzing ─────────────────────────────────────────────────────────

function pei_analyzing_html(state) {
	return `
		<div class="pei-analyzing">
			<div class="pei-spin-wrap">
				<div class="pei-spin-ring"></div>
				<div class="pei-spin-star">✦</div>
			</div>
			<h3 class="pei-panel-title" style="text-align:center; margin-bottom:6px;">${__("Analyzing your email")}</h3>
			<p class="pei-panel-copy" style="text-align:center;">${__("Extracting contact details, project scope, and checking existing CRM records…")}</p>

			<div class="pei-stage-list">
				${ANALYSIS_STAGES.map((label, i) => {
					const done   = i < state.stageIndex;
					const active = i === state.stageIndex;
					return `
						<div class="pei-stage${done ? " done" : active ? " active" : ""}">
							<div class="pei-stage-dot"></div>
							<span>${frappe.utils.escape_html(label)}</span>
							${done ? `<span class="pei-stage-tick">✓</span>` : ""}
						</div>
					`;
				}).join("")}
			</div>
		</div>
	`;
}

// ── Step 3: Review ────────────────────────────────────────────────────────────

function pei_review_html(state) {
	const { formValues: fv, selectedParty, analysis } = state;
	const matches   = analysis?.matches   || {};
	const extracted = analysis?.extracted || {};

	const confPct   = Math.round((extracted.confidence || 0) * 100);
	const confCls   = confPct >= 75 ? "high" : confPct >= 50 ? "med" : "low";
	const confLabel = confPct >= 75 ? __("High confidence") : confPct >= 50 ? __("Moderate") : __("Low confidence");

	const custMatches = matches.customers || [];
	const leadMatches = matches.leads     || [];
	const isNewLead   = selectedParty.type === "Lead" && !selectedParty.name;

	const recType = matches.recommended_party_type || "Lead";

	return `
		<div class="pei-review">

			<!-- ── Left: extracted & editable fields ── -->
			<div class="pei-review-l">

				<div class="pei-review-topbar">
					<button class="pei-back" type="button" data-pei="back">
						<svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="margin-right:4px">
							<path d="M9 2L4 7l5 5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
						</svg>
						${__("Back")}
					</button>
					<div class="pei-conf pei-conf-${confCls}">
						<div class="pei-conf-bar">
							<div class="pei-conf-fill" style="width:${confPct}%"></div>
						</div>
						<span>${confPct}% · ${confLabel}</span>
					</div>
				</div>

				${fv.email_subject ? `
					<div class="pei-subject">
						<svg width="14" height="14" viewBox="0 0 14 14" fill="none" style="flex-shrink:0; margin-top:2px">
							<rect x="1" y="3" width="12" height="8" rx="1.5" stroke="#4f46e5" stroke-width="1.5"/>
							<path d="M1 5l6 4 6-4" stroke="#4f46e5" stroke-width="1.5" stroke-linecap="round"/>
						</svg>
						<span>${frappe.utils.escape_html(fv.email_subject)}</span>
					</div>
				` : ""}

				<!-- Contact Information -->
				<div class="pei-section">
					<div class="pei-sec-head"><span>Contact Information</span></div>
					<div class="pei-field-grid">
						${pei_input("contact_person", __("Contact Person"), "text",  fv.contact_person)}
						${pei_input("company_name",   __("Company"),        "text",  fv.company_name)}
						${pei_input("contact_email",  __("Email Address"),  "email", fv.contact_email, true)}
						${pei_input("mobile_no",      __("Mobile"),         "tel",   fv.mobile_no)}
						${pei_input("phone",          __("Phone"),          "tel",   fv.phone)}
						${fv.website ? pei_input("website", __("Website"), "url", fv.website, true) : ""}
					</div>
				</div>

				<!-- Project Details -->
				<div class="pei-section">
					<div class="pei-sec-head"><span>Project Details</span></div>
					<div class="pei-field-grid">
						${pei_input("project_title",    __("Project Title"), "text", fv.project_title, true)}
						${fv.project_location ? pei_input("project_location", __("Location"), "text", fv.project_location, true) : ""}
					</div>
					${pei_textarea("scope_summary", __("Scope Summary"), fv.scope_summary)}
					${fv.notes ? pei_textarea("notes", __("Notes"), fv.notes) : ""}
				</div>
			</div>

			<!-- ── Right: AI recommendation & match panel ── -->
			<div class="pei-review-r">

				<!-- AI recommendation banner -->
				<div class="pei-rec-card">
					<div class="pei-rec-head">
						<div class="pei-rec-orb">✦</div>
						<div>
							<div class="pei-rec-label">${__("AI Recommendation")}</div>
							<div class="pei-rec-type ${recType === "Customer" ? "customer" : "lead"}">
								${recType === "Customer"
									? `<svg width="11" height="11" viewBox="0 0 11 11" fill="none"><rect x="0.5" y="0.5" width="10" height="10" rx="2" stroke="currentColor" stroke-width="1.2"/></svg> ${__("Existing Customer")}`
									: `<svg width="11" height="11" viewBox="0 0 11 11" fill="none"><circle cx="5.5" cy="3.5" r="2.5" stroke="currentColor" stroke-width="1.2"/><path d="M1 10c0-2.5 2-4 4.5-4s4.5 1.5 4.5 4" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg> ${__("Lead / New Lead")}`
								}
							</div>
						</div>
					</div>
					<p class="pei-rec-reason">${frappe.utils.escape_html(matches.match_reason || __("Review the extracted details and create the opportunity."))}</p>
				</div>

				<!-- Customer matches -->
				${custMatches.length ? `
					<div class="pei-match-group">
						<div class="pei-match-group-lbl">${__("Customer Matches")}</div>
						${custMatches.map(m => pei_match_card(m, "Customer", selectedParty)).join("")}
					</div>
				` : ""}

				<!-- Lead matches -->
				${leadMatches.length ? `
					<div class="pei-match-group">
						<div class="pei-match-group-lbl">${__("Lead Matches")}</div>
						${leadMatches.map(m => pei_match_card(m, "Lead", selectedParty)).join("")}
					</div>
				` : ""}

				<!-- No matches at all -->
				${!custMatches.length && !leadMatches.length ? `
					<div class="pei-no-match">
						<svg width="28" height="28" viewBox="0 0 28 28" fill="none">
							<circle cx="13" cy="13" r="7" stroke="#94a3b8" stroke-width="1.6"/>
							<path d="M18 18l5 5" stroke="#94a3b8" stroke-width="1.6" stroke-linecap="round"/>
						</svg>
						<p>${__("No existing records matched. A new Lead will be created.")}</p>
					</div>
				` : ""}

				<!-- Create new lead option -->
				<div class="pei-new-lead-card${isNewLead ? " selected" : ""}" data-pei="new-lead">
					<div class="pei-new-lead-orb">✦</div>
					<div class="pei-new-lead-text">
						<strong>${__("Create New Lead")}</strong>
						<span>${__("Start fresh from this email contact")}</span>
					</div>
					${isNewLead ? `<div class="pei-check-mark">✓</div>` : ""}
				</div>

				<!-- Selection summary -->
				<div class="pei-selection ${isNewLead ? "is-new" : "is-existing"}">
					<div class="pei-sel-icon">${isNewLead ? "✦" : "✓"}</div>
					<div class="pei-sel-text">
						<strong>${isNewLead ? __("New Lead will be created") : selectedParty.type}</strong>
						<span>${frappe.utils.escape_html(
							isNewLead
								? (fv.company_name || fv.contact_person || __("from this email"))
								: selectedParty.name
						)}</span>
					</div>
				</div>
			</div>

		</div>
	`;
}

function pei_match_card(match, type, selectedParty) {
	const sel   = selectedParty.type === type && selectedParty.name === match.name;
	const score = Math.min(999, Math.round(match.score || 0));
	return `
		<div class="pei-match-card${sel ? " selected" : ""}"
		     data-pei="select"
		     data-match-type="${frappe.utils.escape_html(type)}"
		     data-match-name="${frappe.utils.escape_html(match.name)}">
			<div class="pei-match-top">
				<span class="pei-match-name">${frappe.utils.escape_html(match.name)}</span>
				<span class="pei-match-score">${score}pts</span>
			</div>
			${match.match_reason ? `<div class="pei-match-why">${frappe.utils.escape_html(match.match_reason)}</div>` : ""}
			${sel ? `<div class="pei-match-sel">✓ ${__("Selected")}</div>` : ""}
		</div>
	`;
}

function pei_input(name, label, type, value, full) {
	return `
		<div class="pei-field${full ? " full" : ""}">
			<label>${frappe.utils.escape_html(label)}</label>
			<input type="${type}" data-pei-field="${name}"
			       value="${frappe.utils.escape_html(value || "")}"
			       placeholder="${frappe.utils.escape_html(label)}" />
		</div>
	`;
}

function pei_textarea(name, label, value) {
	return `
		<div class="pei-field full" style="margin-top:10px;">
			<label>${frappe.utils.escape_html(label)}</label>
			<textarea data-pei-field="${name}" rows="3"
			          placeholder="${frappe.utils.escape_html(label)}">${frappe.utils.escape_html(value || "")}</textarea>
		</div>
	`;
}

function pei_bind_review($wrap, dialog, state) {
	// Live-save editable inputs to state (no re-render on input)
	$wrap.find("[data-pei-field]").on("input change", function () {
		const f = this.getAttribute("data-pei-field");
		if (f in state.formValues) state.formValues[f] = this.value;
	});

	// Back button
	$wrap.find("[data-pei='back']").on("click", () => {
		state.step = "attach";
		pei_sync_actions(dialog, state);
		pei_render(dialog, state);
	});

	// Match card selection
	$wrap.find("[data-pei='select']").on("click", function () {
		state.selectedParty = {
			type: this.getAttribute("data-match-type"),
			name: this.getAttribute("data-match-name"),
		};
		pei_rerender_review(dialog, state);
	});

	// New lead option
	$wrap.find("[data-pei='new-lead']").on("click", () => {
		state.selectedParty = { type: "Lead", name: "" };
		pei_rerender_review(dialog, state);
	});
}

function pei_rerender_review(dialog, state) {
	pei_render(dialog, state);
	pei_bind_review(dialog.get_field("wizard_html").$wrapper, dialog, state);
}

// ── Analysis feed ─────────────────────────────────────────────────────────────

function pei_start_feed(dialog, state) {
	pei_stop_feed(state);
	state.stageIndex = 0;
	state.step = "analyzing";
	pei_render(dialog, state);
	pei_sync_actions(dialog, state);

	state.stageTimer = window.setInterval(() => {
		if (state.stageIndex < ANALYSIS_STAGES.length - 1) {
			state.stageIndex += 1;
			pei_render(dialog, state);
		}
	}, 1400);
}

function pei_stop_feed(state) {
	if (state.stageTimer) {
		window.clearInterval(state.stageTimer);
		state.stageTimer = null;
	}
}

// ── API: analyze ─────────────────────────────────────────────────────────────

function pei_run_analysis(dialog, state) {
	if (!state.files.length) {
		frappe.msgprint(__("Please upload at least one email attachment first."));
		return;
	}

	pei_start_feed(dialog, state);

	frappe.call({
		method: "prastara_ai.api.opportunity_email_import.analyze_email_screenshots",
		args: { file_urls: JSON.stringify(state.files.map(f => f.file_url)) },
		callback(response) {
			const payload   = response.message || {};
			const extracted = payload.extracted || {};
			const matches   = payload.matches   || {};

			state.analysis = payload;
			pei_stop_feed(state);
			state.step = "review";

			Object.assign(state.formValues, {
				email_subject:    extracted.email_subject    || "",
				company_name:     extracted.company_name     || "",
				contact_person:   extracted.contact_person   || extracted.sender_name  || "",
				contact_email:    extracted.contact_email    || extracted.sender_email  || "",
				mobile_no:        extracted.mobile_no        || "",
				phone:            extracted.phone            || "",
				website:          extracted.website          || "",
				project_title:    extracted.project_title    || extracted.company_name  || "",
				project_location: extracted.project_location || "",
				scope_summary:    extracted.scope_summary    || "",
				notes:            extracted.notes            || "",
			});

			state.selectedParty = {
				type: matches.recommended_party_type || extracted.recommended_party_type || "Lead",
				name: matches.recommended_party_name || "",
			};

			pei_render(dialog, state);
			pei_bind_review(dialog.get_field("wizard_html").$wrapper, dialog, state);
			pei_sync_actions(dialog, state);
		},
		error() {
			pei_stop_feed(state);
			state.step = "attach";
			pei_render(dialog, state);
			pei_sync_actions(dialog, state);
		},
	});
}

// ── API: create opportunity ───────────────────────────────────────────────────

function pei_create_opportunity(dialog, state) {
	const { formValues, selectedParty } = state;

	dialog.disable_primary_action();
	dialog.set_primary_action(__("Creating…"), () => {});

	frappe.call({
		method: "prastara_ai.api.opportunity_email_import.create_opportunity_from_email_import",
		args: {
			payload: JSON.stringify({
				...formValues,
				party_type: selectedParty.type,
				party_name: selectedParty.name,
				file_urls:  state.files.map(f => f.file_url),
			}),
		},
		callback(response) {
			const result = response.message || {};
			dialog.hide();
			frappe.set_route("Form", "Opportunity", result.opportunity_name);
		},
		error() {
			pei_sync_actions(dialog, state);
		},
	});
}

// ── Primary button state ──────────────────────────────────────────────────────

function pei_sync_actions(dialog, state) {
	if (state.step === "attach") {
		dialog.set_primary_action(__("Analyze →"), () => pei_run_analysis(dialog, state));
		dialog.enable_primary_action();
	} else if (state.step === "analyzing") {
		dialog.set_primary_action(__("Analyzing…"), () => {});
		dialog.disable_primary_action();
	} else {
		dialog.set_primary_action(__("✓ Create Opportunity"), () => pei_create_opportunity(dialog, state));
		dialog.enable_primary_action();
	}
}

// ── Styles ────────────────────────────────────────────────────────────────────

function pei_inject_styles() {
	if (document.getElementById(PEI_STYLE_ID)) return;
	const el = document.createElement("style");
	el.id = PEI_STYLE_ID;
	el.textContent = `

/* ── Dialog shell ── */
.pei-modal .modal-dialog   { max-width: 900px; }
.pei-modal .modal-content  {
	border: 0;
	border-radius: 22px;
	background: #f8fafc;
	box-shadow: 0 32px 80px rgba(15,23,42,0.18), 0 0 0 1px rgba(0,0,0,0.055);
	overflow: hidden;
}
.pei-modal .modal-header {
	padding: 22px 26px 0;
	border-bottom: 0;
	background: transparent;
}
.pei-modal .modal-title {
	font-size: 17px;
	font-weight: 800;
	color: #0f172a;
	letter-spacing: -0.02em;
}
.pei-modal .modal-body   { padding: 16px 26px 8px; }
.pei-modal .modal-footer {
	padding: 14px 26px 24px;
	border-top: 0;
	background: #f8fafc;
}
.pei-modal .frappe-control { margin-bottom: 0; }

/* Primary button */
.pei-modal .btn-primary {
	border: 0;
	border-radius: 12px;
	padding: 11px 24px;
	font-size: 14px;
	font-weight: 700;
	background: linear-gradient(135deg, #4f46e5 0%, #2563eb 100%);
	box-shadow: 0 4px 18px rgba(79,70,229,0.38);
	transition: transform 0.15s, box-shadow 0.15s;
}
.pei-modal .btn-primary:not(:disabled):hover {
	transform: translateY(-1px);
	box-shadow: 0 6px 28px rgba(79,70,229,0.5);
}
.pei-modal .btn-primary:disabled { opacity: 0.48; }

/* Secondary / cancel button */
.pei-modal .btn-default,
.pei-modal .btn-secondary {
	border-radius: 12px;
	border: 1px solid #e2e8f0;
	color: #64748b;
	background: #fff;
	font-weight: 600;
}

/* ── Wizard card ── */
.pei-wizard {
	background: #fff;
	border: 1px solid #e8edf4;
	border-radius: 18px;
	overflow: hidden;
}
.pei-body { padding: 24px; }

/* ── Stepper ── */
.pei-stepper {
	display: flex;
	align-items: center;
	padding: 16px 24px;
	border-bottom: 1px solid #f1f5f9;
	background: #fafbfc;
}
.pei-step {
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 5px;
	flex-shrink: 0;
}
.pei-step-line {
	flex: 1;
	height: 2px;
	background: #e2e8f0;
	margin: 0 8px;
	align-self: center;
	margin-top: -20px;
	transition: background 0.25s;
}
.pei-step-line.done { background: #4f46e5; }
.pei-step-dot {
	width: 30px; height: 30px; border-radius: 50%;
	display: flex; align-items: center; justify-content: center;
	font-size: 12px; font-weight: 800;
	background: #e8edf4; color: #94a3b8;
	transition: all 0.22s;
}
.pei-step.active .pei-step-dot {
	background: #4f46e5; color: #fff;
	box-shadow: 0 0 0 5px rgba(79,70,229,0.14);
}
.pei-step.done .pei-step-dot { background: #4f46e5; color: #fff; }
.pei-step-lbl {
	font-size: 11px; font-weight: 700;
	text-transform: uppercase; letter-spacing: 0.07em;
	color: #b0bac9;
}
.pei-step.active .pei-step-lbl { color: #4f46e5; }
.pei-step.done   .pei-step-lbl { color: #64748b; }

/* ── Shared type ── */
.pei-panel-title {
	font-size: 17px; font-weight: 800;
	color: #0f172a; margin-bottom: 6px;
	letter-spacing: -0.02em;
}
.pei-panel-copy {
	font-size: 13px; color: #64748b;
	line-height: 1.65; margin-bottom: 18px;
}

/* ── Step 1: Attach ── */
.pei-section-intro { margin-bottom: 14px; }
.pei-dropzone {
	display: flex; flex-direction: column; align-items: center;
	gap: 10px; padding: 34px 24px;
	border: 2px dashed #c7d2fe;
	border-radius: 16px;
	background: rgba(79,70,229,0.03);
	cursor: pointer; text-align: center;
	transition: all 0.2s;
}
.pei-dropzone:hover {
	border-color: #4f46e5;
	background: rgba(79,70,229,0.07);
}
.pei-dz-label {
	font-size: 14px; color: #334155;
	display: flex; align-items: center; gap: 6px;
}
.pei-dz-label strong { font-weight: 700; }
.pei-dz-link { color: #4f46e5; font-weight: 700; text-decoration: underline; cursor: pointer; }
.pei-dz-formats { font-size: 12px; color: #94a3b8; font-weight: 600; letter-spacing: 0.06em; }

.pei-file-list { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.pei-file-row {
	display: flex; align-items: center; gap: 12px;
	padding: 10px 14px;
	border: 1px solid #e8edf4;
	border-radius: 12px;
	background: #fff;
	transition: border-color 0.15s;
}
.pei-file-row:hover { border-color: #c7d2fe; }
.pei-file-icon { flex-shrink: 0; }
.pei-file-meta { flex: 1; min-width: 0; }
.pei-file-name {
	font-size: 13px; font-weight: 700; color: #0f172a;
	overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pei-file-ok { font-size: 11px; color: #16a34a; font-weight: 700; margin-top: 2px; }
.pei-file-view {
	font-size: 12px; font-weight: 700; color: #4f46e5;
	text-decoration: none; flex-shrink: 0;
	padding: 4px 10px; border-radius: 8px;
	background: rgba(79,70,229,0.07);
	transition: background 0.15s;
}
.pei-file-view:hover { background: rgba(79,70,229,0.14); text-decoration: none; color: #4f46e5; }
.pei-file-del {
	background: none; border: none; padding: 6px;
	color: #b0bac9; cursor: pointer; border-radius: 8px;
	flex-shrink: 0; display: flex; align-items: center;
	transition: all 0.15s;
}
.pei-file-del:hover { background: #fee2e2; color: #dc2626; }

/* ── Step 2: Analyzing ── */
.pei-analyzing {
	display: flex; flex-direction: column;
	align-items: center; padding: 8px 0 16px;
}
.pei-spin-wrap {
	position: relative;
	width: 76px; height: 76px;
	display: flex; align-items: center; justify-content: center;
	margin-bottom: 22px;
}
.pei-spin-ring {
	position: absolute; inset: 0;
	border: 3px solid #e8edf4;
	border-top-color: #4f46e5;
	border-radius: 50%;
	animation: pei-spin 0.72s linear infinite;
}
.pei-spin-star {
	font-size: 26px; color: #4f46e5;
	animation: pei-pulse-star 1.4s ease-in-out infinite;
}
@keyframes pei-spin      { to { transform: rotate(360deg); } }
@keyframes pei-pulse-star {
	0%, 100% { opacity: 0.55; transform: scale(0.9);  }
	50%       { opacity: 1;    transform: scale(1.08); }
}
.pei-stage-list {
	display: flex; flex-direction: column; gap: 8px;
	width: 100%; max-width: 380px; margin-top: 18px;
}
.pei-stage {
	display: flex; align-items: center; gap: 12px;
	padding: 11px 16px; border-radius: 11px;
	border: 1px solid #e8edf4;
	background: #fafbfc;
	font-size: 13px; font-weight: 600; color: #94a3b8;
	transition: all 0.22s;
}
.pei-stage.done {
	background: #f0fdf4; border-color: #bbf7d0; color: #166534;
}
.pei-stage.active {
	background: #eff6ff; border-color: #bfdbfe; color: #1d4ed8;
	box-shadow: 0 2px 10px rgba(29,78,216,0.09);
}
.pei-stage-dot {
	width: 8px; height: 8px; border-radius: 50%;
	background: #cbd5e1; flex-shrink: 0; transition: all 0.22s;
}
.pei-stage.done   .pei-stage-dot { background: #16a34a; }
.pei-stage.active .pei-stage-dot {
	background: #4f46e5;
	animation: pei-dot-pulse 1.1s ease infinite;
}
@keyframes pei-dot-pulse {
	0%, 100% { box-shadow: 0 0 0 3px rgba(79,70,229,0.15); }
	50%       { box-shadow: 0 0 0 7px rgba(79,70,229,0.22); }
}
.pei-stage-tick { margin-left: auto; font-size: 13px; color: #16a34a; font-weight: 800; }

/* ── Step 3: Review layout ── */
.pei-review {
	display: grid;
	grid-template-columns: 1fr 290px;
	gap: 22px;
	align-items: start;
}

/* Topbar */
.pei-review-topbar {
	display: flex; align-items: center;
	justify-content: space-between; gap: 12px;
	margin-bottom: 14px;
}
.pei-back {
	display: flex; align-items: center;
	background: none; border: 1px solid #e2e8f0;
	border-radius: 9px; padding: 6px 12px;
	font-size: 12px; font-weight: 700; color: #475569;
	cursor: pointer; transition: all 0.15s;
}
.pei-back:hover { border-color: #c7d2fe; color: #4f46e5; background: #eff6ff; }

/* Confidence */
.pei-conf {
	display: flex; align-items: center; gap: 8px;
	font-size: 12px; font-weight: 700;
}
.pei-conf-bar {
	width: 72px; height: 5px;
	background: #e8edf4; border-radius: 3px; overflow: hidden;
}
.pei-conf-fill { height: 100%; border-radius: 3px; transition: width 0.4s; }
.pei-conf-high .pei-conf-fill { background: #16a34a; }
.pei-conf-high span            { color: #16a34a; }
.pei-conf-med  .pei-conf-fill  { background: #d97706; }
.pei-conf-med  span            { color: #d97706; }
.pei-conf-low  .pei-conf-fill  { background: #dc2626; }
.pei-conf-low  span            { color: #dc2626; }

/* Email subject badge */
.pei-subject {
	display: flex; align-items: flex-start; gap: 8px;
	padding: 10px 14px;
	background: #f8fafc;
	border: 1px solid #e8edf4;
	border-radius: 10px;
	margin-bottom: 16px;
	font-size: 13px; font-weight: 600; color: #334155;
	line-height: 1.5;
}

/* Section */
.pei-section { margin-bottom: 18px; }
.pei-sec-head {
	font-size: 11px; font-weight: 800;
	text-transform: uppercase; letter-spacing: 0.09em;
	color: #94a3b8; margin-bottom: 12px;
	display: flex; align-items: center; gap: 10px;
}
.pei-sec-head::after {
	content: ""; flex: 1; height: 1px; background: #f1f5f9;
}

/* Fields */
.pei-field-grid {
	display: grid;
	grid-template-columns: 1fr 1fr;
	gap: 10px;
}
.pei-field { display: flex; flex-direction: column; gap: 5px; }
.pei-field.full { grid-column: 1 / -1; }
.pei-field label {
	font-size: 11px; font-weight: 700;
	text-transform: uppercase; letter-spacing: 0.05em;
	color: #64748b;
}
.pei-field input,
.pei-field textarea {
	width: 100%; border: 1px solid #e2e8f0;
	border-radius: 10px; padding: 9px 13px;
	font-size: 13px; font-family: inherit; color: #0f172a;
	background: #fff; outline: none; resize: vertical;
	transition: border-color 0.15s, box-shadow 0.15s;
}
.pei-field input:focus,
.pei-field textarea:focus {
	border-color: #818cf8;
	box-shadow: 0 0 0 3px rgba(79,70,229,0.10);
}
.pei-field textarea { min-height: 78px; }

/* ── Right column ── */

/* Recommendation card */
.pei-rec-card {
	background: linear-gradient(135deg, #f8faff 0%, #eff6ff 100%);
	border: 1px solid #c7d2fe;
	border-radius: 14px;
	padding: 16px;
	margin-bottom: 14px;
}
.pei-rec-head {
	display: flex; align-items: flex-start; gap: 10px;
	margin-bottom: 10px;
}
.pei-rec-orb {
	width: 32px; height: 32px; border-radius: 9px; flex-shrink: 0;
	background: linear-gradient(135deg, #4f46e5, #2563eb);
	color: #fff; font-size: 14px;
	display: flex; align-items: center; justify-content: center;
}
.pei-rec-label {
	font-size: 10px; font-weight: 800;
	text-transform: uppercase; letter-spacing: 0.07em;
	color: #3730a3; margin-bottom: 5px;
}
.pei-rec-type {
	display: inline-flex; align-items: center; gap: 5px;
	padding: 3px 9px; border-radius: 100px;
	font-size: 11px; font-weight: 700;
}
.pei-rec-type.customer {
	background: rgba(16,185,129,0.12); color: #065f46;
	border: 1px solid rgba(16,185,129,0.25);
}
.pei-rec-type.lead {
	background: rgba(79,70,229,0.10); color: #3730a3;
	border: 1px solid rgba(79,70,229,0.22);
}
.pei-rec-reason { font-size: 12px; color: #1e40af; line-height: 1.6; }

/* Match groups */
.pei-match-group        { margin-bottom: 12px; }
.pei-match-group-lbl {
	font-size: 10px; font-weight: 800;
	text-transform: uppercase; letter-spacing: 0.09em;
	color: #94a3b8; margin-bottom: 6px;
}
.pei-match-card {
	border: 1px solid #e2e8f0;
	border-radius: 11px; padding: 10px 13px;
	background: #fff; cursor: pointer;
	transition: all 0.15s; margin-bottom: 6px;
}
.pei-match-card:hover { border-color: #818cf8; background: #fafbff; }
.pei-match-card.selected {
	border-color: #4f46e5; background: #eff6ff;
	box-shadow: 0 0 0 3px rgba(79,70,229,0.12);
}
.pei-match-top {
	display: flex; align-items: center;
	justify-content: space-between; margin-bottom: 3px;
}
.pei-match-name  { font-size: 13px; font-weight: 700; color: #0f172a; }
.pei-match-score {
	font-size: 10px; font-weight: 800; color: #4f46e5;
	background: rgba(79,70,229,0.10);
	padding: 2px 7px; border-radius: 6px;
}
.pei-match-why  { font-size: 11px; color: #64748b; line-height: 1.45; }
.pei-match-sel  { font-size: 11px; font-weight: 800; color: #4f46e5; margin-top: 5px; }

/* No match */
.pei-no-match {
	display: flex; flex-direction: column; align-items: center; gap: 8px;
	padding: 16px; text-align: center; color: #94a3b8;
	font-size: 12px; line-height: 1.5;
}

/* New lead card */
.pei-new-lead-card {
	display: flex; align-items: center; gap: 10px;
	border: 1.5px dashed #c7d2fe;
	border-radius: 11px; padding: 11px 13px;
	background: rgba(79,70,229,0.03);
	cursor: pointer; margin-bottom: 12px;
	transition: all 0.15s;
}
.pei-new-lead-card:hover { border-color: #4f46e5; background: rgba(79,70,229,0.07); }
.pei-new-lead-card.selected {
	border-style: solid; border-color: #4f46e5;
	background: #eff6ff;
}
.pei-new-lead-orb {
	width: 30px; height: 30px; border-radius: 8px; flex-shrink: 0;
	background: linear-gradient(135deg, #4f46e5, #2563eb);
	color: #fff; font-size: 13px;
	display: flex; align-items: center; justify-content: center;
}
.pei-new-lead-text strong { display: block; font-size: 12px; font-weight: 800; color: #0f172a; }
.pei-new-lead-text span   { font-size: 11px; color: #64748b; }
.pei-check-mark { margin-left: auto; font-size: 15px; color: #4f46e5; font-weight: 800; }

/* Selection summary */
.pei-selection {
	display: flex; align-items: center; gap: 10px;
	padding: 12px 14px; border-radius: 11px; border: 1px solid;
}
.pei-selection.is-new {
	background: rgba(79,70,229,0.06); border-color: rgba(79,70,229,0.22);
}
.pei-selection.is-existing {
	background: rgba(16,185,129,0.06); border-color: rgba(16,185,129,0.22);
}
.pei-sel-icon {
	width: 28px; height: 28px; border-radius: 7px; flex-shrink: 0;
	display: flex; align-items: center; justify-content: center; font-size: 13px;
}
.pei-selection.is-new      .pei-sel-icon { background: rgba(79,70,229,0.14); color: #4f46e5; }
.pei-selection.is-existing .pei-sel-icon { background: rgba(16,185,129,0.14); color: #16a34a; }
.pei-sel-text strong { display: block; font-size: 12px; font-weight: 800; color: #0f172a; }
.pei-sel-text span   { font-size: 11px; color: #64748b; }

/* ── Responsive ── */
@media (max-width: 700px) {
	.pei-review         { grid-template-columns: 1fr; }
	.pei-field-grid     { grid-template-columns: 1fr; }
	.pei-modal .modal-dialog { max-width: 100%; margin: 10px; }
	.pei-stepper        { padding: 12px 16px; }
	.pei-body           { padding: 16px; }
}

`;
	document.head.appendChild(el);
}
