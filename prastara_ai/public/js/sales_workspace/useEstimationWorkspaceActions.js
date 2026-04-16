export function useEstimationWorkspaceActions({
	props,
	activeTab,
	opportunity,
	summary,
	estimations,
	opportunityReferences,
	existingQuotation,
	processing,
	stateLoading,
	isDirty,
	scopeText,
	targetMarginPct,
	files,
	estimation,
	estimationName,
	items,
	costTemplates,
	mockupImages,
	mockupLoading,
	mockupStyle,
	mockupPrompt,
	selectedItemDetail,
	selectedItemDetailRow,
	itemDetailOpen,
	itemDetailLoading,
	itemDetailError,
	costBreakdownLoading,
	commercialReviewLoading,
	drawingTakeoffLoading,
	maxUploadSize,
	allowedFileExtensions,
	hasBlockingValidation,
	extractFrappeErrorMessage,
	loadMockups,
	notify,
}) {
	function pushMessage(message, tone = 'info') {
		if (!message) return;
		if (typeof notify === 'function') {
			notify({ message, tone });
			return;
		}
		console[tone === 'error' ? 'error' : 'log'](message);
	}

	async function loadDetails() {
		try {
			const res = await window.frappe.call(
				'prastara_ai.api.opportunities.get_opportunity_details',
				{ opportunity_name: props.opportunityName }
			);
			const data = res.message || res;
			opportunity.value = data.opportunity || {};
			summary.value = data.summary || {};
			estimations.value = data.estimations || [];
			opportunityReferences.value = data.references || { files: [], notes_text: '', comments: [], context_text: '' };
			existingQuotation.value = data.quotation || '';
			costTemplates.value = data.templates || [];

			if (estimations.value.length > 0) {
				const preferredEstimation = estimations.value.find(row => Number(row.item_count || 0) > 0)
					|| estimations.value[0];
				await loadEstimation(preferredEstimation.name);
			}
		} catch (e) {
			console.error('Failed to load opportunity details:', e);
		} finally {
			stateLoading.value = false;
		}
	}

	async function loadEstimation(name, { navigateToBoq = false } = {}) {
		const res = await window.frappe.call('frappe.client.get', {
			doctype: 'AI Estimation',
			name,
		});
		const doc = res.message;
		estimation.value = doc;
		estimationName.value = name;
		items.value = (doc.items || []).map(i => ({ ...i }));
		scopeText.value = doc.scope_text || '';
		targetMarginPct.value = Number(doc.target_margin_pct || 18);
		isDirty.value = false;
		if (navigateToBoq) {
			activeTab.value = 'estimation';
		}
		await loadSourceFiles();
		await loadMockups();
	}

	async function openItemDetail(item, options = {}) {
		if (!item?.name || !estimationName.value) return;
		const { refresh = false } = options;
		selectedItemDetailRow.value = item;
		selectedItemDetail.value = null;
		itemDetailOpen.value = true;
		itemDetailLoading.value = true;
		itemDetailError.value = '';

		try {
			const res = await window.frappe.call(
				'prastara_ai.api.ai_service.get_estimation_item_pricing_detail',
				{
					estimation_name: estimationName.value,
					item_row_name: item.name,
					refresh: refresh ? 1 : 0,
				}
			);
			selectedItemDetail.value = res.message?.detail || null;
			const currentIndex = items.value.findIndex(row => row.name === item.name);
			if (currentIndex !== -1) {
				items.value[currentIndex] = {
					...items.value[currentIndex],
					pricing_detail_json: JSON.stringify(selectedItemDetail.value || {}),
				};
			}
		} catch (e) {
			console.error('Failed to load item detail:', e);
			itemDetailError.value = extractFrappeErrorMessage(e) || __('Failed to load item pricing detail.');
		} finally {
			itemDetailLoading.value = false;
		}
	}

	function handleFileUpload(event) {
		const fileList = event.dataTransfer?.files ?? event.target?.files ?? [];
		const newFiles = Array.from(fileList).map((file) => {
			const extension = file.name.split('.').pop()?.toLowerCase() || '';
			let error = '';

			if (!allowedFileExtensions.has(extension)) {
				error = 'Unsupported file type. Use PDF, DWG, DXF, or TXT.';
			} else if (file.size > maxUploadSize) {
				error = 'File is too large. Maximum size is 50 MB.';
			}

			return {
				file,
				name: file.name,
				size: file.size,
				uploaded: false,
				uploading: false,
				url: null,
				error,
			};
		});

		files.value = [...files.value, ...newFiles];
		if (event.target) event.target.value = '';
	}

	function removeFile(index) {
		files.value = files.value.filter((_, i) => i !== index);
	}

	function createPersistedFileEntry(fileDoc = {}) {
		return {
			file: null,
			name: fileDoc.file_name || fileDoc.name || 'Attached file',
			size: Number(fileDoc.file_size || 0),
			uploaded: true,
			uploading: false,
			url: fileDoc.file_url || null,
			error: '',
		};
	}

	async function loadSourceFiles() {
		if (!estimationName.value) {
			files.value = [];
			return;
		}

		try {
			const res = await window.frappe.call(
				'prastara_ai.api.ai_service.get_estimation_source_files',
				{ estimation_name: estimationName.value }
			);
			files.value = (res.message?.files || []).map(createPersistedFileEntry);
		} catch (e) {
			console.error('Failed to load attached source files:', e);
		}
	}

	async function uploadPendingFiles() {
		const pending = files.value.filter(file => !file.uploaded && file.file && !file.error);
		const urls = [];

		for (const fileEntry of pending) {
			try {
				fileEntry.uploading = true;
				fileEntry.error = '';
				const formData = new FormData();
				formData.append('file', fileEntry.file, fileEntry.name);
				formData.append('is_private', '0');
				formData.append('folder', 'Home/Attachments');
				if (estimationName.value) {
					formData.append('doctype', 'AI Estimation');
					formData.append('docname', estimationName.value);
				}

				const res = await fetch('/api/method/upload_file', {
					method: 'POST',
					headers: { 'X-Frappe-CSRF-Token': window.frappe.csrf_token },
					body: formData,
				});
				if (!res.ok) {
					throw new Error('Upload request failed.');
				}

				const data = await res.json();
				const fileUrl = data?.message?.file_url;
				if (fileUrl) {
					fileEntry.url = fileUrl;
					fileEntry.uploaded = true;
					urls.push(fileUrl);
				} else {
					throw new Error('Upload completed without a file URL.');
				}
			} catch (err) {
				console.error('File upload failed:', fileEntry.name, err);
				fileEntry.error = err?.message || 'Upload failed. Please retry or remove the file.';
			} finally {
				fileEntry.uploading = false;
			}
		}

		const alreadyUploaded = files.value.filter(file => file.uploaded && file.url).map(file => file.url);
		return [...new Set([...alreadyUploaded, ...urls])];
	}

	async function startAIAnalysis() {
		processing.value = true;
		try {
			if (files.value.some(file => file.error)) {
				pushMessage(__('Please remove or fix files with errors before generating the estimation.'), 'error');
				return;
			}

			const uploadedFileUrls = await uploadPendingFiles();
			if (files.value.some(file => file.error)) {
				pushMessage(__('Some files failed to upload. Remove or retry them before generating the estimation.'), 'error');
				return;
			}

			const res = await window.frappe.call(
				'prastara_ai.api.ai_service.process_estimation',
				{
					opportunity: props.opportunityName,
					text: scopeText.value,
					file_urls: JSON.stringify(uploadedFileUrls),
				}
			);

			await loadEstimation(res.message, { navigateToBoq: true });
			pushMessage('AI Estimation generated! Generating cost breakdown for all items…', 'success');
			await generateCostBreakdown({ silent: true });
		} catch (e) {
			console.error('AI estimation failed:', e);
			pushMessage(
				extractFrappeErrorMessage(e)
				|| __('AI estimation failed. Check the error log or verify your OpenAI API key.'),
				'error'
			);
		} finally {
			processing.value = false;
		}
	}

	async function loadMockupsAction() {
		if (!estimationName.value) {
			mockupImages.value = [];
			return;
		}

		try {
			const res = await window.frappe.call(
				'prastara_ai.api.ai_service.get_estimation_mockups',
				{ estimation_name: estimationName.value }
			);
			mockupImages.value = res.message?.images || [];
		} catch (e) {
			console.error('Failed to load mockups:', e);
		}
	}

	async function generateMockups() {
		if (!estimationName.value) return;

		mockupLoading.value = true;
		try {
			if (files.value.some(file => file.error)) {
				pushMessage(__('Please remove or fix files with errors before generating mockups.'), 'error');
				return;
			}

			const fileUrls = await uploadPendingFiles();
			if (files.value.some(file => file.error)) {
				pushMessage(__('Some files failed to upload. Remove or retry them before generating mockups.'), 'error');
				return;
			}

			const res = await window.frappe.call(
				'prastara_ai.api.ai_service.generate_estimation_mockups',
				{
					estimation_name: estimationName.value,
					scope_text: scopeText.value,
					file_urls: JSON.stringify(fileUrls),
					style: mockupStyle.value,
					additional_prompt: mockupPrompt.value,
					count: 2,
				}
			);

			mockupImages.value = res.message?.images || [];
			pushMessage('Mockup images generated!', 'success');
			await loadMockupsAction();
		} catch (e) {
			console.error('Mockup generation failed:', e);
			pushMessage(
				extractFrappeErrorMessage(e) || __('Failed to generate mockup images. Please check the drawing files and API settings.'),
				'error'
			);
		} finally {
			mockupLoading.value = false;
		}
	}

	async function saveEstimation(options = {}) {
		if (!estimationName.value) return;
		const { silent = false } = options;

		if (hasBlockingValidation.value) {
			if (!silent) {
				pushMessage(__('Please fix BOQ rows with invalid quantity or rate values before saving.'), 'error');
			}
			return false;
		}

		processing.value = true;
		try {
			const updates = items.value.map(item => ({
				name: item.name,
				qty: item.qty,
				rate: item.rate,
			}));

			await window.frappe.call(
				'prastara_ai.api.opportunities.update_estimation_items',
				{
					estimation_name: estimationName.value,
					items: JSON.stringify(updates),
					scope_text: scopeText.value,
					target_margin_pct: targetMarginPct.value,
				}
			);

			isDirty.value = false;
			if (!silent) {
				pushMessage('Draft saved!', 'success');
			}
			return true;
		} catch (e) {
			console.error('Save failed:', e);
			if (!silent) {
				pushMessage(extractFrappeErrorMessage(e) || __('Failed to save draft. Please try again.'), 'error');
			}
			throw e;
		} finally {
			processing.value = false;
		}
	}

	async function approveAndConvert(openQuotation) {
		if (!estimation.value) return;

		if (hasBlockingValidation.value) {
			pushMessage(__('Please resolve the highlighted BOQ issues before creating the quotation.'), 'error');
			return;
		}

		processing.value = true;
		try {
			const saved = await saveEstimation({ silent: true });
			if (!saved) return;

			// Use object form with a no-op error callback to suppress Frappe's
			// built-in error dialog — we handle all errors ourselves below.
			const res = await window.frappe.call({
				method: 'prastara_ai.api.opportunities.convert_to_quotation',
				args: { estimation_name: estimationName.value },
				error: () => {},
			});

			const payload = res.message || {};
			const quotationName = typeof payload === 'string' ? payload : payload.name;
			const isExisting = typeof payload === 'object' && payload.existing;

			if (!quotationName) {
				throw new Error('Quotation was not returned by the server.');
			}

			pushMessage(
				isExisting ? `Opening existing quotation ${quotationName}` : `Quotation ${quotationName} created!`,
				'success'
			);
			existingQuotation.value = quotationName;
			openQuotation(quotationName);
		} catch (e) {
			console.error('Quotation creation failed:', e);
			const message = extractFrappeErrorMessage(e)
				|| __('Failed to create Quotation. Ensure all items are linked to ERPNext Item records, or check the error log.');
			pushMessage(message, 'error');
		} finally {
			processing.value = false;
		}
	}

	function applyTargetMarginToItems() {
		const margin = Number(targetMarginPct.value || 0);
		if (margin < 0 || margin >= 100) {
			pushMessage(__('Target margin must be between 0 and 99.'), 'error');
			return;
		}

		let updatedCount = 0;
		items.value = items.value.map((item) => {
			let detail = null;
			try {
				detail = item.pricing_detail_json ? JSON.parse(item.pricing_detail_json) : null;
			} catch (_) {
				detail = null;
			}
			const costRate = Number(detail?.cost_summary?.unit_rate || 0);
			if (!costRate) return item;
			updatedCount += 1;
			return {
				...item,
				rate: Number((costRate / (1 - (margin / 100))).toFixed(2)),
			};
		});

		if (!updatedCount) {
			pushMessage(__('No BOQ items have AI cost breakdowns yet. Use Generate Cost Breakdown first so margin planning has a cost baseline.'), 'error');
			return;
		}

		isDirty.value = true;
		pushMessage(`Applied target margin to ${updatedCount} item(s).`, 'success');
	}

	async function generateCostBreakdown(options = {}) {
		if (!estimationName.value) return;
		const { refresh = false, silent = false } = options;
		costBreakdownLoading.value = true;
		try {
			const res = await window.frappe.call(
				'prastara_ai.api.ai_service.generate_estimation_cost_breakdown',
				{
					estimation_name: estimationName.value,
					refresh: refresh ? 1 : 0,
				}
			);
			await loadEstimation(estimationName.value);
			const payload = res.message || {};
			const generated = Number(payload.generated_count || 0);
			const cached = Number(payload.cached_count || 0);
			const failed = Number(payload.failed_count || 0);
			if (!silent) {
				if (generated > 0) {
					const failureNote = failed > 0 ? ` ${failed} item(s) still need manual review.` : '';
					pushMessage(`Generated cost breakdown for ${generated} item(s).${failureNote}`, failed > 0 ? 'info' : 'success');
				} else if (cached > 0) {
					pushMessage(`Cost breakdown already available for ${cached} item(s).`, 'info');
				}
			}
			if (failed > 0 && !silent) {
				const failedNames = (payload.failed_items || []).map(item => item.item_name).filter(Boolean).join(', ');
				pushMessage(
					failedNames
						? `Could not generate cost breakdown for: ${failedNames}`
						: __('Some items could not be analyzed automatically.'),
					'error'
				);
			}
		} catch (e) {
			console.error('Cost breakdown generation failed:', e);
			pushMessage(
				extractFrappeErrorMessage(e) || __('Failed to generate cost breakdown for this BOQ. Please try again.'),
				'error'
			);
		} finally {
			costBreakdownLoading.value = false;
		}
	}

	async function loadCommercialReview(options = {}) {
		if (!estimationName.value) return null;
		const { refresh = false } = options;
		commercialReviewLoading.value = true;
		try {
			const res = await window.frappe.call(
				'prastara_ai.api.ai_service.get_estimation_commercial_review',
				{ estimation_name: estimationName.value, refresh: refresh ? 1 : 0 }
			);
			if (estimation.value) {
				estimation.value.commercial_review_json = JSON.stringify(res.message?.review || {});
			}
			return res.message?.review || null;
		} finally {
			commercialReviewLoading.value = false;
		}
	}

	async function loadDrawingTakeoff(options = {}) {
		if (!estimationName.value) return null;
		const { refresh = false } = options;
		drawingTakeoffLoading.value = true;
		try {
			const res = await window.frappe.call(
				'prastara_ai.api.ai_service.get_estimation_drawing_takeoff',
				{ estimation_name: estimationName.value, refresh: refresh ? 1 : 0 }
			);
			if (estimation.value) {
				estimation.value.drawing_takeoff_json = JSON.stringify(res.message?.takeoff || {});
			}
			return res.message?.takeoff || null;
		} finally {
			drawingTakeoffLoading.value = false;
		}
	}

	async function restoreVersion(versionName) {
		if (!versionName || !estimationName.value) return;
		processing.value = true;
		try {
			await window.frappe.call(
				'prastara_ai.api.opportunities.restore_estimation_version',
				{ estimation_name: estimationName.value, version_name: versionName }
			);
			await loadEstimation(estimationName.value);
			pushMessage('Version restored.', 'success');
		} finally {
			processing.value = false;
		}
	}

	async function refreshCostTemplates() {
		const res = await window.frappe.call('prastara_ai.api.opportunities.get_cost_templates');
		costTemplates.value = res.message?.templates || [];
	}

	async function saveAsTemplate(templateName, notes = '') {
		if (!estimationName.value) return;
		if (!templateName) {
			pushMessage(__('Please enter a template name before saving.'), 'error');
			return;
		}
		processing.value = true;
		try {
			await window.frappe.call(
				'prastara_ai.api.opportunities.save_estimation_as_template',
				{ estimation_name: estimationName.value, template_name: templateName, notes }
			);
			await refreshCostTemplates();
			pushMessage('Template saved.', 'success');
		} finally {
			processing.value = false;
		}
	}

	async function applyTemplate(templateName, mergeMode = 'append') {
		if (!estimationName.value) return;
		if (!templateName) {
			pushMessage(__('Please select a saved template first.'), 'error');
			return;
		}
		processing.value = true;
		try {
			await window.frappe.call(
				'prastara_ai.api.opportunities.apply_cost_template',
				{ estimation_name: estimationName.value, template_name: templateName, merge_mode: mergeMode }
			);
			await loadEstimation(estimationName.value);
			pushMessage('Template applied.', 'success');
		} finally {
			processing.value = false;
		}
	}

	return {
		loadDetails,
		loadEstimation,
		handleFileUpload,
		removeFile,
		loadSourceFiles,
		uploadPendingFiles,
		startAIAnalysis,
		loadMockupsAction,
		generateMockups,
		saveEstimation,
		approveAndConvert,
		openItemDetail,
		generateCostBreakdown,
		applyTargetMarginToItems,
		loadCommercialReview,
		loadDrawingTakeoff,
		restoreVersion,
		refreshCostTemplates,
		saveAsTemplate,
		applyTemplate,
	};
}
