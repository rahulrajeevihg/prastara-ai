<template>
	<div v-if="open" class="item-detail-overlay" @click.self="$emit('close')">
		<div class="item-detail-modal glass">
			<div class="item-detail-head">
				<div>
					<p class="item-detail-kicker">AI Pricing Breakdown</p>
					<h3 class="item-detail-title">{{ item?.item_name || 'Item detail' }}</h3>
					<p class="item-detail-meta">
						{{ item?.item_category || 'General' }} · {{ item?.type || 'Material' }} ·
						{{ formatCurrency(item?.rate || 0, currency) }}/{{ item?.uom || 'unit' }}
					</p>
				</div>
				<div class="item-detail-actions">
					<button class="btn btn-glass btn-sm" type="button" @click="$emit('refresh')" :disabled="loading">
						{{ loading ? 'Refreshing…' : 'Refresh AI Detail' }}
					</button>
					<button class="btn btn-ghost btn-sm" type="button" @click="$emit('close')">Close</button>
				</div>
			</div>

			<div v-if="loading" class="item-detail-state">
				<div class="loading-ring small"></div>
				<p>Generating item-wise pricing explanation from the saved scope and drawings…</p>
			</div>

			<div v-else-if="error" class="item-detail-state error">
				<p>{{ error }}</p>
			</div>

			<div v-else-if="detail" class="item-detail-body">
				<div class="item-detail-grid">
					<section class="detail-card">
						<h4>Scope Summary</h4>
						<p>{{ detail.scope_summary || item?.description || 'No scope summary available yet.' }}</p>
					</section>
					<section class="detail-card">
						<h4>Quantity Basis</h4>
						<p>{{ detail.quantity_basis || 'Not available.' }}</p>
					</section>
					<section class="detail-card">
						<h4>Rate Basis</h4>
						<p>{{ detail.rate_basis || 'Not available.' }}</p>
					</section>
					<section class="detail-card">
						<h4>Confidence Note</h4>
						<p>{{ detail.confidence_note || 'No confidence note available.' }}</p>
					</section>
				</div>

				<section class="detail-card wide">
					<h4>Scope Inclusions</h4>
					<ul v-if="detail.scope_inclusions?.length" class="detail-list">
						<li v-for="entry in detail.scope_inclusions" :key="entry">{{ entry }}</li>
					</ul>
					<p v-else>No specific inclusions returned.</p>
				</section>

				<section class="detail-card wide">
					<h4>Drawing / Brief Scope Interpreted</h4>
					<ul v-if="detail.drawing_scope?.length" class="detail-list">
						<li v-for="entry in detail.drawing_scope" :key="entry">{{ entry }}</li>
					</ul>
					<p v-else>No drawing-specific scope cues were returned.</p>
				</section>

				<section class="detail-card wide">
					<h4>Raw Materials</h4>
					<div v-if="detail.raw_materials?.length" class="detail-table-wrap">
						<table class="detail-table">
							<thead>
								<tr>
									<th>Material</th>
									<th>Specification</th>
									<th>Qty</th>
									<th>Unit Rate</th>
									<th>Amount</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="material in detail.raw_materials" :key="`${material.name}-${material.specification}`">
									<td>
										<strong>{{ material.name || 'Material' }}</strong>
										<p class="detail-sub">{{ material.notes || '' }}</p>
									</td>
									<td>{{ material.specification || 'N/A' }}</td>
									<td>{{ material.qty || 0 }} {{ material.uom || '' }}</td>
									<td>{{ formatCurrency(material.unit_rate || 0, currency) }}</td>
									<td>{{ formatCurrency(material.amount || 0, currency) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
					<p v-else>No raw material breakdown returned for this item.</p>
				</section>

				<section class="detail-card wide">
					<h4>Labour Components</h4>
					<ul v-if="detail.labour_components?.length" class="detail-list">
						<li v-for="entry in detail.labour_components" :key="`${entry.name}-${entry.amount}`">
							<strong>{{ entry.name || 'Labour' }}</strong>:
							{{ formatCurrency(entry.amount || 0, currency) }}
							<span v-if="entry.cost_basis"> · {{ entry.cost_basis }}</span>
							<span v-if="entry.notes"> · {{ entry.notes }}</span>
						</li>
					</ul>
					<p v-else>No labour component breakdown returned.</p>
				</section>

				<section class="detail-card wide">
					<h4>Other Costs</h4>
					<ul v-if="detail.other_costs?.length" class="detail-list">
						<li v-for="entry in detail.other_costs" :key="`${entry.name}-${entry.amount}`">
							<strong>{{ entry.name || 'Other Cost' }}</strong>:
							{{ formatCurrency(entry.amount || 0, currency) }}
							<span v-if="entry.notes"> · {{ entry.notes }}</span>
						</li>
					</ul>
					<p v-else>No other cost components returned.</p>
				</section>

				<section class="detail-card wide">
					<h4>Cost Summary</h4>
					<div class="summary-grid">
						<div><span>Raw material cost</span><strong>{{ formatCurrency(detail.cost_summary?.raw_material_cost || 0, currency) }}</strong></div>
						<div><span>Labour cost</span><strong>{{ formatCurrency(detail.cost_summary?.labour_cost || 0, currency) }}</strong></div>
						<div><span>Other cost</span><strong>{{ formatCurrency(detail.cost_summary?.other_cost || 0, currency) }}</strong></div>
						<div><span>Unit rate</span><strong>{{ formatCurrency(detail.cost_summary?.unit_rate || item?.rate || 0, currency) }}</strong></div>
						<div><span>Quantity</span><strong>{{ detail.cost_summary?.quantity || item?.qty || 0 }} {{ item?.uom || '' }}</strong></div>
						<div><span>Total amount</span><strong>{{ formatCurrency(detail.cost_summary?.total_amount || ((item?.qty || 0) * (item?.rate || 0)), currency) }}</strong></div>
					</div>
				</section>

				<section class="detail-card wide">
					<h4>Assumptions</h4>
					<ul v-if="detail.assumptions?.length" class="detail-list">
						<li v-for="entry in detail.assumptions" :key="entry">{{ entry }}</li>
					</ul>
					<p v-else>No assumptions returned.</p>
				</section>

				<section class="detail-card wide">
					<h4>Scope Exclusions / Risks</h4>
					<ul v-if="combinedRisks.length" class="detail-list">
						<li v-for="entry in combinedRisks" :key="entry">{{ entry }}</li>
					</ul>
					<p v-else>No exclusions or risks returned.</p>
				</section>
			</div>
		</div>
	</div>
</template>

<script setup>
import { computed } from 'vue';

const props = defineProps({
	open: { type: Boolean, default: false },
	loading: { type: Boolean, default: false },
	error: { type: String, default: '' },
	detail: { type: Object, default: null },
	item: { type: Object, default: null },
	currency: { type: String, default: 'AED' },
	formatCurrency: { type: Function, required: true },
});

defineEmits(['close', 'refresh']);

const combinedRisks = computed(() => [
	...(props.detail?.scope_exclusions || []),
	...(props.detail?.risks || []),
]);
</script>
