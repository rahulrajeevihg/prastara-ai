<template>
	<div class="page-wrap">
		<div class="stats-strip">
			<div class="stat-card glass">
				<div class="stat-icon si-blue">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--blue)"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
				</div>
				<div class="stat-body">
					<p class="stat-label">Open Opportunities</p>
					<span class="stat-value">{{ formatInteger(state.summary.total_open) }}</span>
					<p class="stat-sub">Active in current view</p>
				</div>
			</div>
			<div class="stat-card glass">
				<div class="stat-icon si-green">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--green)"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>
				</div>
				<div class="stat-body">
					<p class="stat-label">Pipeline Value</p>
					<span class="stat-value">{{ formatCurrency(state.summary.total_value) }}</span>
					<p class="stat-sub">Across loaded records</p>
				</div>
			</div>
			<div class="stat-card glass">
				<div class="stat-icon si-indigo">
					<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--accent)"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
				</div>
				<div class="stat-body">
					<p class="stat-label">Active Pipeline</p>
					<span class="stat-value">{{ formatInteger(state.summary.active_pipeline) }}</span>
					<p class="stat-sub">Progressing to close</p>
				</div>
			</div>
		</div>

		<div class="main-layout">
			<div>
				<SalesWorkspaceFilters
					:filters="filters"
					:sort-value="sortValue"
					:status-options="state.statusOptions"
					:owner-options="state.ownerOptions"
					:stage-options="state.stageOptions"
					@update-filter="$emit('update-filter', $event)"
					@update-sort="$emit('update-sort', $event)"
					@refresh="$emit('refresh')"
					@reset="$emit('reset')"
				/>
				<SalesWorkspaceOpportunityList
					:state="state"
					:active-sort-label="activeSortLabel"
					:format-currency="formatCurrency"
					:format-integer="formatInteger"
					:format-date="formatDate"
					:format-date-time="formatDateTime"
					:normalize-status="normalizeStatus"
					@refresh="$emit('refresh')"
					@load-more="$emit('load-more')"
					@open-estimation="$emit('open-estimation', $event)"
					@open-opportunity="$emit('open-opportunity', $event)"
					@create-opportunity="$emit('create-opportunity')"
				/>
			</div>

			<aside>
				<div class="sidebar-card glass">
					<p class="sc-kicker">How it works</p>
					<p class="sc-title">Opportunity → Quotation</p>
					<div class="sc-list">
						<div class="sc-item">
							<div class="sc-dot"></div>
							<div>
								<strong>Select an opportunity</strong>
								<p>Click any record or press "Estimate →" to open the cockpit.</p>
							</div>
						</div>
						<div class="sc-item">
							<div class="sc-dot" style="background:var(--accent);"></div>
							<div>
								<strong>Describe the scope</strong>
								<p>Enter requirements or upload drawings, PDFs, or briefs.</p>
							</div>
						</div>
						<div class="sc-item">
							<div class="sc-dot" style="background:var(--blue);"></div>
							<div>
								<strong>AI generates the BOQ</strong>
								<p>GPT-4o produces a categorised Bill of Quantities with AED rates.</p>
							</div>
						</div>
						<div class="sc-item">
							<div class="sc-dot" style="background:var(--amber);"></div>
							<div>
								<strong>Review &amp; adjust</strong>
								<p>Edit quantities and rates before confirming.</p>
							</div>
						</div>
						<div class="sc-item">
							<div class="sc-dot" style="background:var(--green);"></div>
							<div>
								<strong>Create Quotation</strong>
								<p>One click converts your estimation into an ERPNext Quotation.</p>
							</div>
						</div>
					</div>
				</div>

				<div class="sidebar-card glass">
					<p class="sc-kicker">Pipeline Health</p>
					<div class="sc-stats">
						<div class="sc-stat-row">
							<span class="sc-stat-label">Total records</span>
							<strong class="sc-stat-val">{{ formatInteger(state.meta.total_count) }}</strong>
						</div>
						<div class="sc-stat-row">
							<span class="sc-stat-label">Pipeline value</span>
							<strong class="sc-stat-val">{{ formatCurrency(state.summary.total_value) }}</strong>
						</div>
						<div class="sc-stat-row">
							<span class="sc-stat-label">Conversion targets</span>
							<strong class="sc-stat-val sc-stat-green">{{ formatInteger(state.summary.active_pipeline) }}</strong>
						</div>
					</div>
				</div>
			</aside>
		</div>
	</div>
</template>

<script setup>
import SalesWorkspaceFilters from "./SalesWorkspaceFilters.vue";
import SalesWorkspaceOpportunityList from "./SalesWorkspaceOpportunityList.vue";

defineProps({
	filters: { type: Object, required: true },
	sortValue: { type: String, required: true },
	activeSortLabel: { type: String, required: true },
	state: { type: Object, required: true },
	formatCurrency: { type: Function, required: true },
	formatInteger: { type: Function, required: true },
	formatDate: { type: Function, required: true },
	formatDateTime: { type: Function, required: true },
	normalizeStatus: { type: Function, required: true },
});

const emit = defineEmits([
	"update-filter",
	"update-sort",
	"refresh",
	"reset",
	"load-more",
	"open-estimation",
	"open-opportunity",
	"create-opportunity",
]);
</script>
