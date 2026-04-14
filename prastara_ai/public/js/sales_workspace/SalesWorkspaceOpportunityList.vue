<template>
	<div class="list-panel glass">
		<div class="list-head">
			<p class="list-head-title">{{ formatInteger(state.meta.total_count) }} Opportunities</p>
			<p class="list-head-meta">{{ activeSortLabel }}</p>
		</div>

		<div v-if="state.loading" class="list-body">
			<div v-for="i in 5" :key="i" class="shimmer"></div>
		</div>

		<div v-else-if="state.error" class="state-msg">
			<div class="state-msg-icon">⚠️</div>
			<h3>Couldn't load opportunities</h3>
			<p>{{ state.error }}</p>
			<button class="btn btn-primary btn-sm" type="button" @click="$emit('refresh')">Try again</button>
		</div>

		<div v-else-if="!state.items.length" class="state-msg">
			<div class="state-msg-icon">📭</div>
			<h3>No opportunities found</h3>
			<p>Try widening your filters or create the first opportunity.</p>
			<button class="btn btn-primary btn-sm" type="button" @click="$emit('create-opportunity')">New Opportunity</button>
		</div>

		<div v-else class="list-body">
			<article
				v-for="opp in state.items"
				:key="opp.name"
				class="opp-card"
				:data-status="normalizeStatus(opp.status)"
				@click="$emit('open-estimation', opp.name)"
			>
				<div class="opp-main">
					<p class="opp-ref">{{ opp.name }}</p>
					<p class="opp-name">{{ opp.title || opp.customer_name || opp.party_name || 'Untitled Opportunity' }}</p>
					<p class="opp-cust">{{ opp.customer_name || opp.party_name || 'Customer not linked' }}</p>
					<div class="opp-chips">
						<span :class="['spill', normalizeStatus(opp.status)]">{{ opp.status || 'Draft' }}</span>
						<div class="chip-sep"></div>
						<div class="chip">
							<span class="chip-label">Owner</span>
							<span class="chip-value">{{ opp.opportunity_owner || 'Unassigned' }}</span>
						</div>
						<div class="chip-sep"></div>
						<div class="chip">
							<span class="chip-label">Stage</span>
							<span class="chip-value">{{ opp.sales_stage || 'Prospecting' }}</span>
						</div>
						<div v-if="opp.latest_estimation" class="chip-sep"></div>
						<div v-if="opp.latest_estimation" class="chip">
							<span class="chip-label">Estimation</span>
							<span class="chip-value">Ready to resume</span>
						</div>
						<div class="chip-sep"></div>
						<div class="chip">
							<span class="chip-label">Expected Close</span>
							<span class="chip-value">{{ formatDate(opp.expected_closing) }}</span>
						</div>
					</div>
				</div>

				<div class="opp-right" @click.stop>
					<div>
						<p class="opp-amount">{{ formatCurrency(opp.opportunity_amount, opp.currency) }}</p>
						<p class="opp-currency">{{ opp.currency || 'AED' }} · Updated {{ formatDateTime(opp.modified) }}</p>
					</div>
					<div class="opp-actions">
						<button class="btn btn-glass btn-sm" type="button" @click="$emit('open-opportunity', opp.name)">View</button>
						<button class="btn btn-primary btn-sm" type="button" @click="$emit('open-estimation', opp.name)">
							{{ opp.latest_estimation ? 'Resume →' : 'Estimate →' }}
						</button>
					</div>
				</div>
			</article>

			<div v-if="state.meta.has_more" class="list-loadmore">
				<button
					class="btn btn-glass btn-sm"
					type="button"
					@click="$emit('load-more')"
					:disabled="state.loadingMore"
				>
					{{ state.loadingMore ? 'Loading…' : 'Load More Opportunities' }}
				</button>
			</div>
		</div>
	</div>
</template>

<script setup>
defineProps({
	state: { type: Object, required: true },
	activeSortLabel: { type: String, required: true },
	formatCurrency: { type: Function, required: true },
	formatInteger: { type: Function, required: true },
	formatDate: { type: Function, required: true },
	formatDateTime: { type: Function, required: true },
	normalizeStatus: { type: Function, required: true },
});

defineEmits([
	"refresh",
	"load-more",
	"open-estimation",
	"open-opportunity",
	"create-opportunity",
]);
</script>
