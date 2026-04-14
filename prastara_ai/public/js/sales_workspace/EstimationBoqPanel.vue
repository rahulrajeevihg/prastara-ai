<template>
	<div class="ew-panel glass">
		<p class="ew-panel-kicker">Step 2</p>
		<h2 class="ew-panel-title">Bill of Quantities</h2>

		<div v-if="!estimation" style="text-align:center; padding:48px 24px;">
			<div style="font-size:2.5rem; margin-bottom:14px;">📋</div>
			<p style="color:var(--text-2); margin-bottom:16px;">No estimation yet. Go to Project Scope and generate one first.</p>
			<button class="btn btn-primary btn-sm" @click="$emit('switch-to-input')">Go to Project Scope →</button>
		</div>

		<div v-else>
			<div class="boq-toolbar">
				<div class="boq-view-switch">
					<button
						:class="['btn btn-sm', groupMode === 'category' ? 'btn-primary' : 'btn-glass']"
						type="button"
						@click="$emit('update:groupMode', 'category')"
					>
						Trade View
					</button>
					<button
						:class="['btn btn-sm', groupMode === 'room' ? 'btn-primary' : 'btn-glass']"
						type="button"
						@click="$emit('update:groupMode', 'room')"
					>
						Room-wise View
					</button>
				</div>
				<p class="boq-toolbar-copy">
					Showing {{ groupMode === 'room' ? 'room / zone' : 'trade category' }} grouping.
				</p>
			</div>

			<!-- ── Empty items state ─────────────────────── -->
			<div v-if="!groupedItems.length" class="boq-empty-state">
				<div class="boq-empty-icon">📋</div>
				<p class="boq-empty-title">No BOQ items yet</p>
				<p class="boq-empty-text">
					The estimation record exists but has no line items.
					This usually means the AI generation didn't produce output — try going back to Project Scope,
					check your scope text or attached files, and regenerate.
				</p>
				<button class="btn btn-primary btn-sm" @click="$emit('switch-to-input')">
					← Back to Project Scope
				</button>
			</div>

			<div v-for="group in groupedItems" :key="group.category" class="cat-block">
				<div class="cat-head">
					<span class="cat-name">{{ group.category }}</span>
					<span class="cat-count">{{ group.items.length }} item{{ group.items.length !== 1 ? 's' : '' }}</span>
					<span class="cat-subtotal">{{ formatCurrency(group.subtotal, currency) }}</span>
				</div>

				<table class="boq-table">
					<thead>
						<tr>
							<th style="width:30%">Item / Description</th>
							<th style="width:8%">AI Detail</th>
							<th style="width:7%">Type</th>
							<th style="width:8%">Qty</th>
							<th style="width:6%">UOM</th>
							<th style="width:13%">Rate ({{ currency || 'AED' }})</th>
							<th style="width:13%">Total</th>
							<th style="width:15%">Confidence</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="(item, idx) in group.items"
							:key="item.name || idx"
							:class="{ 'boq-row-error': itemValidationState(item).errors.length, 'boq-row-warning': !itemValidationState(item).errors.length && itemValidationState(item).warnings.length }"
						>
							<td class="item-name-cell">
								<p class="iname">{{ item.item_name }}</p>
								<p class="idesc">{{ item.description }}</p>
								<p v-if="itemValidationState(item).errors.length" class="row-issue error">{{ itemValidationState(item).errors[0] }}</p>
								<p v-else-if="itemValidationState(item).warnings.length" class="row-issue warning">{{ itemValidationState(item).warnings[0] }}</p>
							</td>
							<td>
								<button class="btn btn-glass btn-sm detail-btn" type="button" @click="$emit('view-item-detail', item)">
									View AI Detail
								</button>
							</td>
							<td>
								<span :class="['type-badge', item.type === 'Service' ? 'svc' : 'mat']">
									{{ item.type || 'Material' }}
								</span>
							</td>
							<td>
								<input
									type="number"
									v-model.number="item.qty"
									:class="['num-inp', { invalid: itemValidationState(item).errors.some(message => message.toLowerCase().includes('quantity')) }]"
									min="0"
									@input="$emit('mark-dirty')"
								/>
							</td>
							<td class="uom-cell">{{ item.uom }}</td>
							<td>
								<input
									type="number"
									v-model.number="item.rate"
									:class="['num-inp', { invalid: itemValidationState(item).errors.some(message => message.toLowerCase().includes('rate')), warning: !itemValidationState(item).errors.some(message => message.toLowerCase().includes('rate')) && itemValidationState(item).warnings.some(message => message.toLowerCase().includes('rate')) }]"
									min="0"
									step="0.01"
									@input="$emit('mark-dirty')"
								/>
							</td>
							<td class="row-total">{{ formatCurrency((item.qty || 0) * (item.rate || 0), currency) }}</td>
							<td>
								<div class="conf-wrap">
									<div class="conf-fill" :style="{ width: ((item.confidence || 0) * 100) + '%', background: confidenceColor(item.confidence) }"></div>
								</div>
								<p class="conf-pct">{{ Math.round((item.confidence || 0) * 100) }}%</p>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div v-if="validationSummary.totalIssues" class="validation-panel">
				<div class="validation-head">
					<span>{{ validationSummary.blockingIssues ? 'Resolve blocking BOQ issues before quotation creation.' : 'Review these BOQ warnings before finalizing the quotation.' }}</span>
					<span>{{ validationSummary.totalIssues }} issue{{ validationSummary.totalIssues !== 1 ? 's' : '' }}</span>
				</div>
				<p v-if="validationSummary.blockingIssues" class="validation-copy">
					{{ validationSummary.blockingIssues }} blocking, {{ validationSummary.warningIssues }} warning{{ validationSummary.warningIssues !== 1 ? 's' : '' }}.
				</p>
				<p v-else class="validation-copy">
					{{ validationSummary.warningIssues }} warning{{ validationSummary.warningIssues !== 1 ? 's' : '' }} found. Saving is allowed, but review is recommended.
				</p>
			</div>

			<div class="totals-block">
				<div class="totals-row">
					<span>Materials subtotal</span>
					<span>{{ formatCurrency(materialTotal, currency) }}</span>
				</div>
				<div class="totals-row">
					<span>Services subtotal</span>
					<span>{{ formatCurrency(serviceTotal, currency) }}</span>
				</div>
				<div class="totals-row grand">
					<span>Net Estimated Value</span>
					<strong>{{ formatCurrency(totalAmount, currency) }}</strong>
				</div>
			</div>

			<div v-if="isDirty" class="dirty-bar">
				<span>⚠</span>
				<span v-if="autoSaveError">{{ autoSaveError }}</span>
				<span v-else-if="autoSaveInFlight">Saving your latest changes automatically…</span>
				<span v-else-if="autoSavePending">Unsaved edits detected. Autosave will update this draft shortly.</span>
				<span v-else>You have unsaved edits — autosave will retry shortly.</span>
			</div>
		</div>
	</div>
</template>

<script setup>
defineProps({
	estimation: { type: Object, default: null },
	groupedItems: { type: Array, default: () => [] },
	groupMode: { type: String, default: 'category' },
	currency: { type: String, default: 'AED' },
	materialTotal: { type: Number, default: 0 },
	serviceTotal: { type: Number, default: 0 },
	totalAmount: { type: Number, default: 0 },
	isDirty: { type: Boolean, default: false },
	autoSaveInFlight: { type: Boolean, default: false },
	autoSavePending: { type: Boolean, default: false },
	autoSaveError: { type: String, default: '' },
	validationSummary: {
		type: Object,
		default: () => ({ blockingIssues: 0, warningIssues: 0, totalIssues: 0 }),
	},
	itemValidationState: { type: Function, required: true },
	confidenceColor: { type: Function, required: true },
	formatCurrency: { type: Function, required: true },
});

defineEmits(['mark-dirty', 'switch-to-input', 'view-item-detail', 'update:groupMode']);
</script>
