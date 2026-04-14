<template>
	<aside class="ew-sidebar">
		<div class="ews-card glass">
			<p class="ews-kicker">Project Context</p>
			<div class="ews-row">
				<span class="ews-key">Customer / Lead</span>
				<span class="ews-val">{{ summary.customer || '—' }}</span>
			</div>
			<div class="ews-row">
				<span class="ews-key">Status</span>
				<span :class="['spill', (opportunity.status || 'draft').toLowerCase()]" style="font-size:0.63rem;">
					{{ opportunity.status || 'Draft' }}
				</span>
			</div>
			<div class="ews-row">
				<span class="ews-key">Initial Budget</span>
				<span class="ews-val">{{ formatCurrency(summary.amount, summary.currency) }}</span>
			</div>
			<div class="ews-row">
				<span class="ews-key">Expected Close</span>
				<span class="ews-val">{{ formatDate(summary.expected_closing) }}</span>
			</div>
			<div style="margin-top:14px;">
				<p class="ews-key" style="margin-bottom:6px;">Win Probability</p>
				<div class="prob-track">
					<div class="prob-fill" :style="{ width: (summary.probability || 0) + '%' }"></div>
				</div>
				<p style="font-size:0.72rem; color:var(--text-3); margin-top:4px; text-align:right;">{{ summary.probability || 0 }}%</p>
			</div>
		</div>

		<div v-if="estimation" class="ews-card breakdown-card">
			<p class="ews-kicker">Estimation Totals</p>
			<div class="bd-line">
				<span>Materials</span>
				<strong>{{ formatCurrency(materialTotal, summary.currency) }}</strong>
			</div>
			<div class="bd-line">
				<span>Services</span>
				<strong>{{ formatCurrency(serviceTotal, summary.currency) }}</strong>
			</div>
			<div class="bd-line" style="color:var(--text-3); font-size:0.72rem;">
				<span>{{ itemCount }} line items</span>
				<span>{{ estimation.status }}</span>
			</div>
			<div class="bd-grand">
				<span>Net Total</span>
				<strong>{{ formatCurrency(totalAmount, summary.currency) }}</strong>
			</div>
		</div>

		<div v-if="estimation" class="ews-card glass">
			<div class="gp-head">
				<div>
					<p class="ews-kicker">Expected Gross Profit</p>
					<p class="gp-subcopy">
						{{
							grossProfitMode === 'actual'
								? 'Based on AI cost build-up captured for this BOQ.'
								: grossProfitMode === 'hybrid'
									? 'Uses AI cost build-up where available and projected cost for the remaining items.'
									: 'Projected from your target margin until detailed item cost build-up is available.'
						}}
					</p>
				</div>
				<span :class="['gp-badge', grossProfitMode]">
					{{ grossProfitMode === 'actual' ? 'Live' : grossProfitMode === 'hybrid' ? 'Blended' : 'Projected' }}
				</span>
			</div>
			<button
				class="btn btn-primary btn-sm gp-action-btn"
				type="button"
				@click="$emit('generate-cost-breakdown')"
				:disabled="costBreakdownLoading"
			>
				{{ costBreakdownLoading ? 'Generating Cost Breakdown…' : 'Generate Cost Breakdown for All Items' }}
			</button>
			<p class="gp-action-note">Run this once to calculate item-level costs across the full BOQ for more accurate GP and margin totals.</p>
			<div class="gp-chart-wrap">
				<div class="gp-chart" :style="{ '--gp-progress': gpChartProgress }">
					<div class="gp-chart-inner">
						<strong>{{ expectedGrossProfitPct.toFixed(1) }}%</strong>
						<span>Expected GP</span>
					</div>
				</div>
				<div class="gp-legend">
					<div class="gp-legend-row">
						<span class="gp-dot gp-dot-profit"></span>
						<div>
							<strong>{{ formatCurrency(expectedGrossProfitValue, summary.currency) }}</strong>
							<p>Expected gross profit</p>
						</div>
					</div>
					<div class="gp-legend-row">
						<span class="gp-dot gp-dot-cost"></span>
						<div>
							<strong>{{ formatCurrency(expectedCostValue, summary.currency) }}</strong>
							<p>{{ grossProfitMode === 'actual' ? 'Estimated cost' : grossProfitMode === 'hybrid' ? 'Blended cost' : 'Projected cost' }}</p>
						</div>
					</div>
				</div>
			</div>
			<div class="gp-highlight">
				<div>
					<span class="gp-highlight-label">Expected GP Amount</span>
					<strong>{{ formatCurrency(expectedGrossProfitValue, summary.currency) }}</strong>
				</div>
				<div>
					<span class="gp-highlight-label">Expected GP %</span>
					<strong>{{ expectedGrossProfitPct.toFixed(1) }}%</strong>
				</div>
			</div>
		</div>

		<div v-if="estimation" class="ews-card glass">
			<p class="ews-kicker">Margin Planner</p>
			<div class="ews-row">
				<span class="ews-key">Target Margin %</span>
				<input v-model.number="localTargetMarginPct" class="num-inp" type="number" min="0" max="99" step="0.5" />
			</div>
			<div class="ews-row">
				<span class="ews-key">Cost coverage</span>
				<span class="ews-val">{{ coveredCostItemCount }}/{{ itemCount }} items</span>
			</div>
			<div class="ews-row">
				<span class="ews-key">Estimated cost total</span>
				<span class="ews-val">{{ formatCurrency(estimatedCostTotal, summary.currency) }}</span>
			</div>
			<div class="ews-row">
				<span class="ews-key">Current margin</span>
				<span class="ews-val">{{ currentMarginPct.toFixed(1) }}%</span>
			</div>
			<div class="ews-row">
				<span class="ews-key">Gross profit</span>
				<span class="ews-val">{{ formatCurrency(expectedGrossProfitValue, summary.currency) }}</span>
			</div>
			<div class="ews-row">
				<span class="ews-key">Cost share</span>
				<span class="ews-val">{{ expectedCostSharePct.toFixed(1) }}%</span>
			</div>
			<div class="ews-row">
				<span class="ews-key">Suggested sell total</span>
				<span class="ews-val">{{ formatCurrency(suggestedSellTotal, summary.currency) }}</span>
			</div>
			<button class="btn btn-primary btn-sm" style="width:100%; margin-top:12px;" type="button" @click="$emit('apply-target-margin')">
				Apply Target Margin
			</button>
		</div>

		<div v-if="existingQuotation" class="ews-card ews-quotation-card">
			<div class="ews-quotation-icon">✓</div>
			<p class="ews-kicker" style="margin-bottom:6px;">Quotation Generated</p>
			<p class="ews-quotation-id">{{ existingQuotation }}</p>
			<p style="font-size:0.73rem; color:var(--text-2); margin-bottom:14px; line-height:1.5;">
				This estimation has been converted. Open the quotation to review or send to the customer.
			</p>
			<button class="btn btn-success btn-sm" style="width:100%;" @click="$emit('open-quotation', existingQuotation)">
				Open Quotation →
			</button>
		</div>

		<div class="ews-card glass">
			<p class="ews-kicker">Workflow</p>
			<div class="wf-steps">
				<div class="wf-step">
					<div :class="['wf-num', scopeText || fileCount ? 'done' : activeTab === 'input' ? 'active' : 'pending']">1</div>
					<p :class="['wf-txt', scopeText || fileCount ? 'done' : activeTab === 'input' ? 'active' : '']">Enter scope or upload drawings</p>
				</div>
				<div class="wf-step">
					<div :class="['wf-num', estimation ? 'done' : 'pending']">2</div>
					<p :class="['wf-txt', estimation ? 'done' : '']">Generate AI estimation</p>
				</div>
				<div class="wf-step">
					<div :class="['wf-num', estimation && activeTab === 'estimation' ? 'active' : 'pending']">3</div>
					<p :class="['wf-txt', estimation && activeTab === 'estimation' ? 'active' : '']">Review &amp; adjust qty / rates</p>
				</div>
				<div class="wf-step">
					<div :class="['wf-num', !isDirty && estimation ? 'done' : 'pending']">4</div>
					<p :class="['wf-txt', !isDirty && estimation ? 'done' : '']">Save draft to preserve edits</p>
				</div>
				<div class="wf-step">
					<div :class="['wf-num', estimation && estimation.status === 'Quotation Generated' ? 'done' : 'pending']">5</div>
					<p class="wf-txt">Confirm &amp; create quotation</p>
				</div>
			</div>
		</div>

		<div class="ews-card glass">
			<p class="ews-kicker">Mockup Studio</p>
			<p class="mockup-copy">Generate AI mockup images using the current scope, BOQ context, and the drawing files attached to this estimation.</p>
			<div class="mockup-controls">
				<div class="field-col">
					<label class="field-lbl" for="mockup-style">Style</label>
					<select id="mockup-style" v-model="localMockupStyle" class="glass-select">
						<option value="photorealistic">Photorealistic</option>
						<option value="concept">Concept Render</option>
						<option value="minimal">Minimal Premium</option>
					</select>
				</div>
				<div class="field-col">
					<label class="field-lbl" for="mockup-prompt">Extra Direction</label>
					<textarea
						id="mockup-prompt"
						v-model="localMockupPrompt"
						class="mockup-input"
						placeholder="Optional: modern reception palette, warm oak joinery, hospitality mood, etc."
					></textarea>
				</div>
				<button
					class="btn btn-primary btn-sm"
					@click="$emit('generate-mockups')"
					:disabled="mockupLoading || !estimationName"
				>
					{{ mockupLoading ? 'Generating…' : 'Generate Mockups' }}
				</button>
			</div>
			<p class="mockup-note">Best results come from uploaded PDF / DWG drawings plus a clear project brief.</p>
			<div v-if="mockupImages.length" class="mockup-grid">
				<a
					v-for="image in mockupImages"
					:key="image.name || image.file_url"
					:href="image.file_url"
					target="_blank"
					rel="noreferrer"
					class="mockup-tile"
				>
					<img :src="image.file_url" :alt="image.file_name || 'Generated mockup'" class="mockup-image" />
					<span class="mockup-label">{{ image.file_name || 'Mockup image' }}</span>
				</a>
			</div>
			<p v-else class="mockup-empty">No mockups yet. Generate a set to preview the space visually.</p>
		</div>
	</aside>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
	opportunity: { type: Object, default: () => ({}) },
	summary: { type: Object, default: () => ({}) },
	estimation: { type: Object, default: null },
	existingQuotation: { type: String, default: '' },
	scopeText: { type: String, default: '' },
	fileCount: { type: Number, default: 0 },
	activeTab: { type: String, default: 'input' },
	isDirty: { type: Boolean, default: false },
	materialTotal: { type: Number, default: 0 },
	serviceTotal: { type: Number, default: 0 },
	totalAmount: { type: Number, default: 0 },
	itemCount: { type: Number, default: 0 },
	targetMarginPct: { type: Number, default: 18 },
	coveredCostItemCount: { type: Number, default: 0 },
	estimatedCostTotal: { type: Number, default: 0 },
	currentMarginPct: { type: Number, default: 0 },
	grossProfitValue: { type: Number, default: 0 },
	grossProfitPct: { type: Number, default: 0 },
	costSharePct: { type: Number, default: 0 },
	expectedGrossProfitValue: { type: Number, default: 0 },
	expectedGrossProfitPct: { type: Number, default: 0 },
	expectedCostValue: { type: Number, default: 0 },
	expectedCostSharePct: { type: Number, default: 0 },
	grossProfitMode: { type: String, default: 'expected' },
	costBreakdownLoading: { type: Boolean, default: false },
	suggestedSellTotal: { type: Number, default: 0 },
	mockupImages: { type: Array, default: () => [] },
	mockupLoading: { type: Boolean, default: false },
	mockupStyle: { type: String, default: 'photorealistic' },
	mockupPrompt: { type: String, default: '' },
	estimationName: { type: String, default: '' },
	formatCurrency: { type: Function, required: true },
	formatDate: { type: Function, required: true },
});

const emit = defineEmits([
	'open-quotation',
	'generate-mockups',
	'update:mockupStyle',
	'update:mockupPrompt',
	'update:targetMarginPct',
	'generate-cost-breakdown',
	'apply-target-margin',
]);

const localMockupStyle = computed({
	get: () => props.mockupStyle,
	set: (value) => emit('update:mockupStyle', value),
});

const localMockupPrompt = computed({
	get: () => props.mockupPrompt,
	set: (value) => emit('update:mockupPrompt', value),
});

const localTargetMarginPct = computed({
	get: () => props.targetMarginPct,
	set: (value) => emit('update:targetMarginPct', Number(value || 0)),
});

const gpChartProgress = computed(() => {
	const pct = Number(props.expectedGrossProfitPct || 0);
	return `${Math.max(0, Math.min(100, pct))}%`;
});

</script>
