<template>
	<div class="ew-root">
		<div v-if="notifications.length" class="ew-toast-stack">
			<div
				v-for="toast in notifications"
				:key="toast.id"
				:class="['ew-toast', `tone-${toast.tone || 'info'}`]"
			>
				<div class="ew-toast-body">
					<strong class="ew-toast-title">{{ toastTitles[toast.tone] || 'Notice' }}</strong>
					<p class="ew-toast-copy">{{ toast.message }}</p>
				</div>
				<button class="ew-toast-close" type="button" @click="dismissNotification(toast.id)">×</button>
			</div>
		</div>

		<!-- ── Loading screen ──────────────────────────── -->
		<div v-if="state_loading" class="loading-screen">
			<div class="loading-ring"></div>
			<p class="loading-label">Loading opportunity…</p>
		</div>

		<template v-else>

			<!-- ── Header ──────────────────────────────────── -->
			<header class="ew-header">
				<div class="ew-header-l">
					<button class="btn btn-glass btn-sm" @click="$emit('back')">← Back</button>
					<div class="ew-divider-v"></div>
					<div>
						<p class="ew-opp-id">{{ opportunity.name || 'Opportunity' }}</p>
						<p class="ew-opp-name">{{ opportunity.title || summary.customer || 'Project Estimation' }}</p>
					</div>
				</div>

				<div class="ew-header-r">
					<button class="btn btn-glass btn-sm" @click="$emit('toggle-theme')">
						{{ theme === 'light' ? '☾ Dark' : '☀ Light' }}
					</button>
					<span v-if="autoSaveInFlight" style="font-size:0.75rem; color:var(--indigo); font-weight:600;">Autosaving…</span>
					<span v-else-if="autoSavePending" style="font-size:0.75rem; color:var(--text-3); font-weight:600;">Autosave queued</span>
					<span v-if="isDirty" style="font-size:0.75rem; color:var(--amber); font-weight:600;">● Unsaved</span>
					<button class="btn btn-glass btn-sm" @click="saveEstimation" :disabled="processing || !estimation || !!existingQuotation">
						Save Draft
					</button>
					<button
						v-if="existingQuotation"
						class="btn btn-success btn-sm"
						@click="openQuotation(existingQuotation)"
					>
						View Quotation →
					</button>
					<button
						v-else
						class="btn btn-success btn-sm"
						@click="approveAndConvert"
						:disabled="processing || !estimation || !hasRates || hasBlockingValidation"
					>
						{{ processing ? 'Processing…' : '✓ Create Quotation' }}
					</button>
				</div>
			</header>

			<!-- ── Body ───────────────────────────────────── -->
			<div class="ew-body">

				<!-- Main content -->
				<div>

					<!-- Quotation already created banner -->
					<div v-if="existingQuotation" class="quotation-banner">
						<div class="qb-icon">✓</div>
						<div class="qb-body">
							<p class="qb-title">Quotation already created</p>
							<p class="qb-sub">This estimation was converted to <strong>{{ existingQuotation }}</strong>. Make further changes directly in the quotation.</p>
						</div>
						<button class="btn btn-success btn-sm" @click="openQuotation(existingQuotation)">
							Open {{ existingQuotation }} →
						</button>
					</div>

					<!-- Tab navigation -->
					<div class="ew-tabs">
						<button
							v-for="tab in tabs"
							:key="tab.id"
							:class="['ew-tab', { active: activeTab === tab.id }]"
							@click="activeTab = tab.id"
						>{{ tab.label }}</button>
					</div>

					<EstimationInputPanel
						v-if="activeTab === 'input'"
						:scope-text="scopeText"
						:files="files"
						:opportunity-references="opportunityReferences"
						:processing="processing"
						:format-file-size="formatFileSize"
						:format-date-time="formatDateTime"
						@update:scope-text="scopeText = $event"
						@upload-files="handleFileUpload"
						@remove-file="removeFile"
						@generate-estimation="startAIAnalysis"
					/>

					<!-- ─ Tab 2: Draft Estimation ───────────── -->
					<EstimationBoqPanel
						v-if="activeTab === 'estimation'"
						:estimation="estimation"
						:grouped-items="groupedItems"
						:group-mode="groupMode"
						:currency="summary.currency"
						:material-total="materialTotal"
						:service-total="serviceTotal"
						:total-amount="totalAmount"
						:is-dirty="isDirty"
						:auto-save-in-flight="autoSaveInFlight"
						:auto-save-pending="autoSavePending"
						:auto-save-error="autoSaveError"
						:validation-summary="validationSummary"
						:item-validation-state="itemValidationState"
						:confidence-color="confidenceColor"
						:format-currency="formatCurrency"
						@mark-dirty="markDirty"
						@switch-to-input="activeTab = 'input'"
						@view-item-detail="handleViewItemDetail"
						@update:group-mode="groupMode = $event"
					/>

					<!-- ─ Tab 3: Scope Notes ─────────────────── -->
					<EstimationNotesPanel
						v-if="activeTab === 'notes'"
						:estimation="estimation"
						:audit-summary="auditSummary"
						:commercial-review="commercialReview"
						:commercial-review-loading="commercialReviewLoading"
						:drawing-takeoff="drawingTakeoff"
						:drawing-takeoff-loading="drawingTakeoffLoading"
						:version-history="versionHistory"
						:format-date-time="formatDateTime"
						@refresh-review="loadCommercialReview({ refresh: true })"
						@refresh-takeoff="loadDrawingTakeoff({ refresh: true })"
						@restore-version="restoreVersion"
					/>
				</div>

				<EstimationSidebar
					:opportunity="opportunity"
					:summary="summary"
					:estimation="estimation"
					:existing-quotation="existingQuotation"
					:scope-text="scopeText"
					:file-count="files.length"
					:active-tab="activeTab"
					:is-dirty="isDirty"
					:material-total="materialTotal"
					:service-total="serviceTotal"
					:total-amount="totalAmount"
					:item-count="items.length"
					:target-margin-pct="targetMarginPct"
					:covered-cost-item-count="coveredCostItems.length"
					:estimated-cost-total="estimatedCostTotal"
					:current-margin-pct="currentMarginPct"
					:gross-profit-value="grossProfitValue"
					:gross-profit-pct="grossProfitPct"
					:cost-share-pct="costSharePct"
					:expected-gross-profit-value="expectedGrossProfitValue"
					:expected-gross-profit-pct="expectedGrossProfitPct"
					:expected-cost-value="expectedCostValue"
					:expected-cost-share-pct="expectedCostSharePct"
					:gross-profit-mode="grossProfitMode"
					:cost-breakdown-loading="costBreakdownLoading"
					:suggested-sell-total="suggestedSellTotal"
					:cost-templates="costTemplates"
					:mockup-images="mockupImages"
					:mockup-loading="mockupLoading"
					:mockup-style="mockupStyle"
					:mockup-prompt="mockupPrompt"
					:estimation-name="estimation_name"
					:format-currency="formatCurrency"
					:format-date="formatDate"
					@open-quotation="openQuotation"
					@update:target-margin-pct="targetMarginPct = $event"
					@generate-cost-breakdown="generateCostBreakdown"
					@apply-target-margin="applyTargetMarginToItems"
					@save-template="saveAsTemplate($event)"
					@apply-template="applyTemplate($event.templateName, $event.mergeMode)"
					@generate-mockups="generateMockups"
					@update:mockup-style="mockupStyle = $event"
					@update:mockup-prompt="mockupPrompt = $event"
				/>
			</div>

			<EstimationItemDetailModal
				:open="itemDetailOpen"
				:loading="itemDetailLoading"
				:error="itemDetailError"
				:detail="selectedItemDetail"
				:item="selectedItemDetailRow"
				:currency="summary.currency"
				:format-currency="formatCurrency"
				@close="closeItemDetail"
				@refresh="refreshSelectedItemDetail"
			/>
		</template>

		<!-- ── AI Generation full-screen overlay ──────── -->
		<Transition name="ai-overlay">
			<div v-if="processing" class="ai-gen-overlay">
				<div class="ai-gen-card">

					<div class="ai-gen-ring-wrap">
						<svg class="ai-gen-ring" viewBox="0 0 120 120">
							<circle cx="60" cy="60" r="54" fill="none" stroke="rgba(139,92,246,0.12)" stroke-width="6"/>
							<circle cx="60" cy="60" r="54" fill="none" stroke="url(#aiRingGrad)" stroke-width="6"
								stroke-linecap="round" stroke-dasharray="120 220" class="ai-gen-arc"/>
							<defs>
								<linearGradient id="aiRingGrad" x1="0%" y1="0%" x2="100%" y2="100%">
									<stop offset="0%" stop-color="#8B5CF6"/>
									<stop offset="100%" stop-color="#4ADE80"/>
								</linearGradient>
							</defs>
						</svg>
						<div class="ai-gen-icon">✦</div>
					</div>

					<p class="ai-gen-title">Generating AI Estimation</p>
					<p class="ai-gen-stage">{{ aiGenStage }}</p>

					<div class="ai-gen-dots">
						<span></span><span></span><span></span>
					</div>

					<div class="ai-gen-steps">
						<div
							v-for="(step, i) in aiGenSteps"
							:key="i"
							:class="['ai-gen-step', i < aiGenActiveStep ? 'done' : i === aiGenActiveStep ? 'active' : 'pending']"
						>
							<span class="ai-step-icon">
								{{ i < aiGenActiveStep ? '✓' : i === aiGenActiveStep ? '⏳' : '○' }}
							</span>
							<span>{{ step }}</span>
						</div>
					</div>

					<p class="ai-gen-note">This usually takes 15–30 seconds depending on file size.</p>
				</div>
			</div>
		</Transition>
	</div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import EstimationInputPanel from './EstimationInputPanel.vue';
import EstimationBoqPanel from './EstimationBoqPanel.vue';
import EstimationItemDetailModal from './EstimationItemDetailModal.vue';
import EstimationNotesPanel from './EstimationNotesPanel.vue';
import EstimationSidebar from './EstimationSidebar.vue';
import { useEstimationWorkspaceActions } from './useEstimationWorkspaceActions.js';
import {
	confidenceColor,
	extractFrappeErrorMessage,
	formatCurrency,
	formatDate,
	formatDateTime,
	formatFileSize,
	itemValidationState,
	useEstimationWorkspaceMetrics,
} from './useEstimationWorkspaceHelpers.js';

const props = defineProps(['opportunityName', 'theme']);
const emit = defineEmits(['back', 'toggle-theme']);

// ── AI generation overlay state ───────────────────────────────────────────────
const aiGenSteps = [
	'Uploading documents',
	'Reading project scope',
	'Analysing drawings with AI',
	'Generating BOQ items',
	'Calculating quantities & rates',
	'Finalising estimation',
];
const aiGenMessages = [
	'Uploading your documents…',
	'Reading project scope…',
	'Analysing drawings with AI…',
	'Identifying scope items…',
	'Calculating quantities & rates…',
	'Building your BOQ…',
	'Finalising estimation…',
];
const aiGenActiveStep = ref(0);
const aiGenStage = ref(aiGenMessages[0]);
let aiGenTimer = null;

function startAiGenOverlay() {
	aiGenActiveStep.value = 0;
	aiGenStage.value = aiGenMessages[0];
	let idx = 0;
	aiGenTimer = setInterval(() => {
		idx++;
		if (idx < aiGenMessages.length) aiGenStage.value = aiGenMessages[idx];
		if (aiGenActiveStep.value < aiGenSteps.length - 1) aiGenActiveStep.value++;
	}, 4000);
}

function stopAiGenOverlay() {
	clearInterval(aiGenTimer);
	aiGenTimer = null;
	aiGenActiveStep.value = 0;
	aiGenStage.value = aiGenMessages[0];
}

const activeTab = ref('input');
const tabs = [
	{ id: 'input',      label: '1. Project Scope' },
	{ id: 'estimation', label: '2. Draft BOQ' },
	{ id: 'notes',      label: '3. Scope Notes' },
];

const opportunity  = ref({});
const summary      = ref({});
const estimations  = ref([]);
const opportunityReferences = ref({ files: [], notes_text: '', comments: [], context_text: '' });
const processing   = ref(false);
const state_loading = ref(true);
const isDirty      = ref(false);
const existingQuotation = ref('');

const scopeText        = ref('');
const targetMarginPct  = ref(18);
const files            = ref([]);
const estimation       = ref(null);
const estimation_name  = ref('');
const items            = ref([]);
const costTemplates    = ref([]);
const mockupImages     = ref([]);
const mockupLoading    = ref(false);
const mockupStyle      = ref('photorealistic');
const mockupPrompt     = ref('');
const itemDetailOpen   = ref(false);
const selectedItemDetail = ref(null);
const selectedItemDetailRow = ref(null);
const itemDetailLoading = ref(false);
const itemDetailError   = ref('');
const costBreakdownLoading = ref(false);
const commercialReviewLoading = ref(false);
const drawingTakeoffLoading = ref(false);
const groupMode = ref('category');
const notifications = ref([]);
const autoSavePending = ref(false);
const autoSaveInFlight = ref(false);
const autoSaveError = ref('');
const lastSavedSignature = ref('');
let autoSaveTimer = null;
const toastTitles = {
	success: 'Success',
	error: 'Action needed',
	info: 'Notice',
};
const MAX_UPLOAD_SIZE = 50 * 1024 * 1024;
const ALLOWED_FILE_EXTENSIONS = new Set(['pdf', 'dwg', 'dxf', 'txt']);

function notify({ message, tone = 'info' }) {
	if (!message) return;
	const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
	notifications.value = [...notifications.value, { id, message, tone }];
	window.setTimeout(() => dismissNotification(id), tone === 'error' ? 7000 : 4200);
}

function dismissNotification(id) {
	notifications.value = notifications.value.filter(toast => toast.id !== id);
}

const draftSignature = computed(() => JSON.stringify({
	scope_text: scopeText.value || '',
	target_margin_pct: Number(targetMarginPct.value || 0),
	items: items.value.map(item => ({
		name: item.name,
		qty: Number(item.qty || 0),
		rate: Number(item.rate || 0),
	})),
}));

const {
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
} = useEstimationWorkspaceMetrics(items, estimation, groupMode, targetMarginPct);

const {
	loadDetails,
	handleFileUpload,
	removeFile,
	startAIAnalysis,
	generateMockups,
	saveEstimation,
	approveAndConvert: approveAndConvertAction,
	loadMockupsAction,
	openItemDetail,
	generateCostBreakdown,
	applyTargetMarginToItems,
	loadCommercialReview,
	loadDrawingTakeoff,
	restoreVersion,
	saveAsTemplate,
	applyTemplate,
} = useEstimationWorkspaceActions({
	props,
	activeTab,
	opportunity,
	summary,
	estimations,
	opportunityReferences,
	existingQuotation,
	processing,
	stateLoading: state_loading,
	isDirty,
	scopeText,
	targetMarginPct,
	files,
	estimation,
	estimationName: estimation_name,
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
	maxUploadSize: MAX_UPLOAD_SIZE,
	allowedFileExtensions: ALLOWED_FILE_EXTENSIONS,
	hasBlockingValidation,
	extractFrappeErrorMessage,
	loadMockups: () => loadMockupsAction(),
	notify,
});

// ── helpers ───────────────────────────────────────────────────────────────────

function markDirty() {
	isDirty.value = true;
}

function clearAutoSaveTimer() {
	if (!autoSaveTimer) return;
	window.clearTimeout(autoSaveTimer);
	autoSaveTimer = null;
}

async function runAutoSave() {
	if (!estimation_name.value || existingQuotation.value || autoSaveInFlight.value || processing.value) {
		return;
	}
	if (hasBlockingValidation.value) {
		autoSavePending.value = false;
		autoSaveError.value = 'Autosave paused until blocking BOQ issues are fixed.';
		return;
	}

	autoSaveInFlight.value = true;
	autoSavePending.value = false;
	autoSaveError.value = '';

	try {
		const saved = await saveEstimation({ silent: true });
		if (saved) {
			lastSavedSignature.value = draftSignature.value;
			isDirty.value = false;
		}
	} catch (_) {
		autoSaveError.value = 'Autosave failed. Use Save Draft to retry.';
	} finally {
		autoSaveInFlight.value = false;
	}
}

function queueAutoSave() {
	if (!estimation_name.value || existingQuotation.value) return;
	autoSavePending.value = true;
	clearAutoSaveTimer();
	autoSaveTimer = window.setTimeout(() => {
		runAutoSave();
	}, 1400);
}

function approveAndConvert() {
	return approveAndConvertAction(openQuotation);
}

function handleViewItemDetail(item) {
	openItemDetail(item);
}

function refreshSelectedItemDetail() {
	if (!selectedItemDetailRow.value) return;
	openItemDetail(selectedItemDetailRow.value, { refresh: true });
}

function closeItemDetail() {
	itemDetailOpen.value = false;
	itemDetailError.value = '';
}

function openQuotation(name) {
	if (!name) return;
	window.location.href = `/app/quotation/${encodeURIComponent(name)}`;
}

watch(
	() => processing.value,
	(running) => { running ? startAiGenOverlay() : stopAiGenOverlay(); }
);

watch(
	() => estimation_name.value,
	async (name) => {
		clearAutoSaveTimer();
		autoSavePending.value = false;
		autoSaveInFlight.value = false;
		autoSaveError.value = '';
		if (!name) {
			lastSavedSignature.value = '';
			return;
		}
		await nextTick();
		lastSavedSignature.value = draftSignature.value;
		isDirty.value = false;
	}
);

watch(
	draftSignature,
	(signature) => {
		if (!estimation_name.value || !lastSavedSignature.value) return;
		if (signature === lastSavedSignature.value) {
			isDirty.value = false;
			autoSavePending.value = false;
			autoSaveError.value = '';
			clearAutoSaveTimer();
			return;
		}
		isDirty.value = true;
		queueAutoSave();
	}
);

watch(
	() => hasBlockingValidation.value,
	(hasBlocking) => {
		if (!hasBlocking && isDirty.value && draftSignature.value !== lastSavedSignature.value) {
			queueAutoSave();
		}
	}
);

onBeforeUnmount(() => {
	clearAutoSaveTimer();
	stopAiGenOverlay();
});

onMounted(loadDetails);
</script>
