import { computed } from 'vue';

export function itemValidationState(item) {
	const errors = [];
	const warnings = [];
	const qty = Number(item?.qty ?? 0);
	const rate = Number(item?.rate ?? 0);
	const confidence = Number(item?.confidence ?? 0);

	if (!Number.isFinite(qty) || qty <= 0) {
		errors.push('Quantity must be greater than 0.');
	}

	if (!Number.isFinite(rate) || rate < 0) {
		errors.push('Rate cannot be negative.');
	} else if (rate === 0) {
		warnings.push('Rate is still 0. Review pricing before quotation.');
	}

	if (qty > 100000) {
		warnings.push('Quantity looks unusually high. Please verify measurement.');
	}

	if (rate > 100000) {
		warnings.push('Rate looks unusually high. Please verify pricing.');
	}

	if (confidence > 0 && confidence < 0.45) {
		warnings.push('AI confidence is low for this line. Manual review recommended.');
	}

	return { errors, warnings };
}

export function confidenceColor(value) {
	if (!value) return 'var(--text-3)';
	if (value >= 0.8) return 'var(--green)';
	if (value >= 0.5) return 'var(--amber)';
	return 'var(--red)';
}

export function formatCurrency(value, currency = 'AED') {
	return new Intl.NumberFormat(undefined, {
		style: 'currency',
		currency: currency || 'AED',
		maximumFractionDigits: 0,
	}).format(value || 0);
}

export function formatDate(value) {
	if (!value) return 'TBD';
	return new Date(value).toLocaleDateString(undefined, {
		month: 'short', day: 'numeric', year: 'numeric',
	});
}

export function formatDateTime(value) {
	if (!value) return 'Unknown';
	return new Date(value).toLocaleString(undefined, {
		month: 'short',
		day: 'numeric',
		year: 'numeric',
		hour: 'numeric',
		minute: '2-digit',
	});
}

export function formatFileSize(bytes) {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function extractFrappeErrorMessage(error) {
	if (error?.message && typeof error.message === 'string') {
		return error.message;
	}

	const responseJSON = error?.responseJSON;
	if (responseJSON?._server_messages) {
		try {
			const messages = JSON.parse(responseJSON._server_messages).map((entry) => {
				const parsed = JSON.parse(entry);
				return parsed.message;
			}).filter(Boolean);
			if (messages.length) return messages.join('\n');
		} catch (_) {
			/* ignore JSON parsing issues and continue fallback checks */
		}
	}

	if (responseJSON?.message && typeof responseJSON.message === 'string') {
		return responseJSON.message;
	}

	return '';
}

export function parseJsonSafe(value) {
	if (!value) return null;
	if (typeof value === 'object') return value;
	try {
		return JSON.parse(value);
	} catch (_) {
		return null;
	}
}

export function getItemCostRate(item) {
	const detail = parseJsonSafe(item?.pricing_detail_json);
	if (detail?.cost_summary?.unit_rate != null) {
		return Number(detail.cost_summary.unit_rate) || 0;
	}
	const qty = Number(item?.qty || 0);
	const costSummary = detail?.cost_summary;
	const combinedCost = Number(costSummary?.raw_material_cost || 0)
		+ Number(costSummary?.labour_cost || 0)
		+ Number(costSummary?.other_cost || 0);
	if (qty > 0 && combinedCost > 0) {
		return combinedCost / qty;
	}
	return 0;
}

export function getItemFallbackCostRate(item, fallbackMarginPct = 0) {
	const rate = Number(item?.rate || 0);
	const margin = Math.max(0, Math.min(99, Number(fallbackMarginPct || 0)));
	if (!rate) return 0;
	return rate * (1 - (margin / 100));
}

export function useEstimationWorkspaceMetrics(items, estimation, groupMode, targetMarginPct) {
	const totalAmount = computed(() =>
		items.value.reduce((sum, item) => sum + (item.qty || 0) * (item.rate || 0), 0)
	);

	const materialTotal = computed(() =>
		items.value
			.filter(i => i.type !== 'Service')
			.reduce((sum, i) => sum + (i.qty || 0) * (i.rate || 0), 0)
	);

	const serviceTotal = computed(() =>
		items.value
			.filter(i => i.type === 'Service')
			.reduce((sum, i) => sum + (i.qty || 0) * (i.rate || 0), 0)
	);

	const hasRates = computed(() =>
		items.value.length > 0 && items.value.some(i => (i.rate || 0) > 0)
	);

	const validationSummary = computed(() => {
		let blockingIssues = 0;
		let warningIssues = 0;

		for (const item of items.value) {
			const state = itemValidationState(item);
			blockingIssues += state.errors.length;
			warningIssues += state.warnings.length;
		}

		return {
			blockingIssues,
			warningIssues,
			totalIssues: blockingIssues + warningIssues,
		};
	});

	const hasBlockingValidation = computed(() => validationSummary.value.blockingIssues > 0);

	const auditSummary = computed(() => {
		return parseJsonSafe(estimation.value?.generation_audit);
	});

	const commercialReview = computed(() => parseJsonSafe(estimation.value?.commercial_review_json));
	const drawingTakeoff = computed(() => parseJsonSafe(estimation.value?.drawing_takeoff_json));
	const versionHistory = computed(() => estimation.value?.version_history || []);
	const roomOptions = computed(() => {
		const rooms = new Set();
		for (const item of items.value) {
			rooms.add(item.room_zone || 'Unassigned Zone');
		}
		return Array.from(rooms);
	});

	const groupedItems = computed(() => {
		const groups = {};
		for (const item of items.value) {
			const groupLabel = groupMode?.value === 'room'
				? (item.room_zone || 'Unassigned Zone')
				: (item.item_category || 'General');
			if (!groups[groupLabel]) groups[groupLabel] = [];
			groups[groupLabel].push(item);
		}
		return Object.entries(groups).map(([groupLabel, categoryItems]) => ({
			category: groupLabel,
			items: categoryItems,
			subtotal: categoryItems.reduce((sum, item) => sum + (item.qty || 0) * (item.rate || 0), 0),
		}));
	});

	const coveredCostItems = computed(() => items.value.filter(item => getItemCostRate(item) > 0));
	const estimatedCostTotal = computed(() => items.value.reduce((sum, item) => {
		const qty = Number(item.qty) || 0;
		const actualCostRate = getItemCostRate(item);
		const fallbackCostRate = getItemFallbackCostRate(item, targetMarginPct?.value);
		return sum + ((actualCostRate || fallbackCostRate) * qty);
	}, 0));
	const currentMarginPct = computed(() => {
		if (!totalAmount.value || !estimatedCostTotal.value) return 0;
		return ((totalAmount.value - estimatedCostTotal.value) / totalAmount.value) * 100;
	});
	const grossProfitValue = computed(() => {
		if (!totalAmount.value || !estimatedCostTotal.value) return 0;
		return totalAmount.value - estimatedCostTotal.value;
	});
	const costSharePct = computed(() => {
		if (!totalAmount.value || !estimatedCostTotal.value) return 0;
		return Math.max(0, Math.min(100, (estimatedCostTotal.value / totalAmount.value) * 100));
	});
	const grossProfitPct = computed(() => {
		if (!totalAmount.value || !estimatedCostTotal.value) return 0;
		return Math.max(0, Math.min(100, currentMarginPct.value));
	});
	const expectedGrossProfitPct = computed(() => {
		const fallbackMargin = Number(targetMarginPct?.value || 0);
		if (totalAmount.value > 0) return Math.max(0, Math.min(99, grossProfitPct.value));
		return Math.max(0, Math.min(99, fallbackMargin));
	});
	const expectedGrossProfitValue = computed(() => {
		if (!totalAmount.value) return 0;
		return grossProfitValue.value > 0 ? grossProfitValue.value : totalAmount.value * (expectedGrossProfitPct.value / 100);
	});
	const expectedCostValue = computed(() => {
		if (!totalAmount.value) return 0;
		return estimatedCostTotal.value > 0 ? estimatedCostTotal.value : Math.max(0, totalAmount.value - expectedGrossProfitValue.value);
	});
	const expectedCostSharePct = computed(() => {
		if (!totalAmount.value) return 0;
		return costSharePct.value > 0 ? costSharePct.value : Math.max(0, Math.min(100, 100 - expectedGrossProfitPct.value));
	});
	const grossProfitMode = computed(() => {
		if (!items.value.length || coveredCostItems.value.length === 0) return 'expected';
		if (coveredCostItems.value.length === items.value.length) return 'actual';
		return 'hybrid';
	});
	const suggestedSellTotal = computed(() => {
		const margin = Number(targetMarginPct?.value || 0);
		if (!estimatedCostTotal.value || margin >= 100) return 0;
		return estimatedCostTotal.value / (1 - (margin / 100));
	});

	return {
		totalAmount,
		materialTotal,
		serviceTotal,
		hasRates,
		validationSummary,
		hasBlockingValidation,
		auditSummary,
		commercialReview,
		drawingTakeoff,
		versionHistory,
		roomOptions,
		groupedItems,
		coveredCostItems,
		estimatedCostTotal,
		currentMarginPct,
		grossProfitValue,
		grossProfitPct,
		costSharePct,
		expectedGrossProfitValue,
		expectedGrossProfitPct,
		expectedCostValue,
		expectedCostSharePct,
		grossProfitMode,
		suggestedSellTotal,
	};
}
