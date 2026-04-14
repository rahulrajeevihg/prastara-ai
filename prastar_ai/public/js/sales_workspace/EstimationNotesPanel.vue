<template>
	<div class="ew-panel glass">
		<p class="ew-panel-kicker">Step 3</p>
		<h2 class="ew-panel-title">AI Scope Notes</h2>

		<div v-if="!estimation" style="text-align:center; padding:48px 24px;">
			<div style="font-size:2.5rem; margin-bottom:14px;">🤖</div>
			<p style="color:var(--text-2);">Generate an AI estimation first to see scope notes here.</p>
		</div>

		<div v-else>
			<div v-if="estimation.ai_summary" class="note-card summary">
				<p class="note-kicker">Executive Summary</p>
				<p>{{ estimation.ai_summary }}</p>
			</div>

			<div v-if="estimation.assumptions" class="note-card assume">
				<p class="note-kicker">Assumptions</p>
				<p>{{ estimation.assumptions }}</p>
			</div>

			<div v-if="estimation.exclusions" class="note-card exclude">
				<p class="note-kicker">Exclusions</p>
				<p>{{ estimation.exclusions }}</p>
			</div>

			<div v-if="estimation.project_area" class="note-card area">
				<p class="note-kicker">Estimated Project Footprint</p>
				<div style="margin-top:8px; display:flex; align-items:baseline; gap:6px;">
					<span class="area-num">{{ estimation.project_area.toLocaleString() }}</span>
					<span class="area-unit">Sq. Ft.</span>
				</div>
			</div>

			<div v-if="auditSummary" class="note-card summary">
				<p class="note-kicker">Generation Audit</p>
				<p>
					Model: {{ auditSummary.model || 'Unknown' }}<br>
					Generated: {{ formatDateTime(auditSummary.generated_at) }}<br>
					Prompt: {{ auditSummary.used_custom_prompt ? 'Custom settings prompt' : 'Default fallback prompt' }}<br>
					Source files: {{ auditSummary.source_file_count || 0 }}<br>
					Estimated items: {{ auditSummary.result_item_count || 0 }}<br>
					Vision mode: {{ auditSummary.used_vision ? `Yes (${auditSummary.vision_page_count || 0} page(s))` : 'No' }}
				</p>
			</div>

			<div v-if="auditResponseMeta.hasPreview" :class="['note-card', auditResponseMeta.isFailure ? 'exclude' : 'summary']">
				<div class="notes-action-head">
					<p class="note-kicker" style="margin-bottom:0;">{{ auditResponseMeta.title }}</p>
					<button class="btn btn-glass btn-sm" type="button" @click="showRawAudit = !showRawAudit">
						{{ showRawAudit ? 'Hide Raw Response' : 'Show Raw Response' }}
					</button>
				</div>
				<div class="audit-preview-grid">
					<div v-if="auditResponseMeta.projectTitle">
						<span>Project Title</span>
						<strong>{{ auditResponseMeta.projectTitle }}</strong>
					</div>
					<div>
						<span>Response Keys</span>
						<strong>{{ auditResponseMeta.responseKeys }}</strong>
					</div>
					<div v-if="auditResponseMeta.itemCount !== null">
						<span>Detected Items</span>
						<strong>{{ auditResponseMeta.itemCount }}</strong>
					</div>
					<div v-if="auditResponseMeta.projectArea">
						<span>Project Area</span>
						<strong>{{ auditResponseMeta.projectArea }}</strong>
					</div>
				</div>
				<p v-if="auditResponseMeta.scopeSummary">{{ auditResponseMeta.scopeSummary }}</p>
				<div v-if="auditResponseMeta.assumptions || auditResponseMeta.exclusions" class="audit-preview-split">
					<div v-if="auditResponseMeta.assumptions">
						<p class="note-kicker">Assumptions Preview</p>
						<p>{{ auditResponseMeta.assumptions }}</p>
					</div>
					<div v-if="auditResponseMeta.exclusions">
						<p class="note-kicker">Exclusions Preview</p>
						<p>{{ auditResponseMeta.exclusions }}</p>
					</div>
				</div>
				<pre v-if="showRawAudit" class="audit-raw">{{ auditSummary.ai_response_preview }}</pre>
				<p v-else class="audit-preview-note">
					{{ auditResponseMeta.isFailure
						? 'This raw preview is shown to help diagnose why the AI response could not be used directly.'
						: 'The AI response was parsed successfully. Open the raw response only if you need debugging detail.' }}
				</p>
			</div>

			<div class="note-card area">
				<div class="notes-action-head">
					<p class="note-kicker" style="margin-bottom:0;">Drawing-aware Takeoff</p>
					<button class="btn btn-glass btn-sm" type="button" @click="$emit('refresh-takeoff')" :disabled="drawingTakeoffLoading">
						{{ drawingTakeoffLoading ? 'Refreshing…' : (drawingTakeoff ? 'Refresh' : 'Generate') }}
					</button>
				</div>
				<p v-if="drawingTakeoff?.takeoff_summary">{{ drawingTakeoff.takeoff_summary }}</p>
				<p v-else style="color:var(--text-2);">No drawing takeoff generated yet.</p>
				<div v-if="drawingTakeoff?.rooms?.length" class="takeoff-rooms">
					<div v-for="room in drawingTakeoff.rooms" :key="room.room_zone" class="takeoff-room">
						<strong>{{ room.room_zone || 'Unassigned Zone' }}</strong>
						<p>Scope: {{ (room.scope_detected || []).join(', ') || '—' }}</p>
						<p>Dimensions: {{ (room.dimensions_detected || []).join(', ') || '—' }}</p>
						<p>Quantity cues: {{ (room.quantity_cues || []).join(', ') || '—' }}</p>
					</div>
				</div>
			</div>

			<div class="note-card summary">
				<div class="notes-action-head">
					<p class="note-kicker" style="margin-bottom:0;">AI Commercial Review</p>
					<button class="btn btn-glass btn-sm" type="button" @click="$emit('refresh-review')" :disabled="commercialReviewLoading">
						{{ commercialReviewLoading ? 'Refreshing…' : (commercialReview ? 'Refresh' : 'Generate') }}
					</button>
				</div>
				<p v-if="commercialReview?.executive_summary">
					Review Score: {{ commercialReview.review_score || 0 }}/100<br><br>
					{{ commercialReview.executive_summary }}
				</p>
				<p v-else style="color:var(--text-2);">No commercial review generated yet.</p>
				<div v-if="commercialReview" class="review-lists">
					<div class="review-block">
						<p class="note-kicker">Missing Scope</p>
						<p>{{ formatFindings(commercialReview.missing_scope, 'title', 'reason') }}</p>
					</div>
					<div class="review-block">
						<p class="note-kicker">Underpriced / Margin Risks</p>
						<p>{{ formatFindings([...(commercialReview.underpriced_items || []), ...(commercialReview.margin_risks || [])], 'item_name', 'issue') }}</p>
					</div>
					<div class="review-block">
						<p class="note-kicker">Recommended Actions</p>
						<p>{{ (commercialReview.recommended_actions || []).join('\n') || 'None' }}</p>
					</div>
				</div>
			</div>

			<div v-if="versionHistory?.length" class="note-card summary">
				<p class="note-kicker">Version History</p>
				<div class="version-list">
					<div v-for="version in versionHistory" :key="version.name" class="version-item">
						<div>
							<strong>{{ version.version_label }}</strong>
							<p>{{ version.source_action }} · {{ formatDateTime(version.created_at) }} · {{ version.item_count || 0 }} items</p>
							<p>{{ version.snapshot_summary || 'Snapshot saved' }}</p>
						</div>
						<button class="btn btn-glass btn-sm" type="button" @click="$emit('restore-version', version.name)">Restore</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
	estimation: { type: Object, default: null },
	auditSummary: { type: Object, default: null },
	commercialReview: { type: Object, default: null },
	commercialReviewLoading: { type: Boolean, default: false },
	drawingTakeoff: { type: Object, default: null },
	drawingTakeoffLoading: { type: Boolean, default: false },
	versionHistory: { type: Array, default: () => [] },
	formatDateTime: { type: Function, required: true },
});

defineEmits(['refresh-review', 'refresh-takeoff', 'restore-version']);

const showRawAudit = ref(false);

const auditResponseMeta = computed(() => {
	const preview = props.auditSummary?.ai_response_preview || '';
	const keys = props.auditSummary?.ai_response_keys || [];
	let parsed = null;
	try {
		parsed = preview ? JSON.parse(preview) : null;
	} catch (_) {
		parsed = null;
	}

	const itemCount = Array.isArray(parsed?.items) ? parsed.items.length : null;
	const hasStructuredSuccess = Boolean(parsed && itemCount !== null && itemCount > 0);

	return {
		hasPreview: Boolean(preview),
		isFailure: !hasStructuredSuccess,
		title: hasStructuredSuccess ? 'AI Response Preview' : 'Failure Transparency',
		responseKeys: keys.length ? keys.join(', ') : 'N/A',
		projectTitle: parsed?.project_title || '',
		scopeSummary: parsed?.scope_summary || '',
		projectArea: parsed?.project_area_sqft ? `${parsed.project_area_sqft.toLocaleString()} Sq. Ft.` : '',
		itemCount,
		assumptions: parsed?.assumptions || '',
		exclusions: parsed?.exclusions || '',
	};
});

function formatFindings(entries = [], titleKey, reasonKey) {
	if (!entries?.length) return 'None';
	return entries.map(entry => `${entry[titleKey] || entry.title || entry.item_name || 'Item'}: ${entry[reasonKey] || entry.reason || entry.issue || ''}`).join('\n');
}
</script>
