<template>
	<div class="filter-bar glass">
		<div class="filter-grid">
			<div class="field-col">
				<label class="field-lbl" for="ws-search">Search</label>
				<input
					id="ws-search"
					:value="filters.search"
					class="glass-input"
					type="search"
					placeholder="Opportunity, customer, title…"
					@input="updateFilter('search', $event.target.value)"
					@keyup.enter="$emit('refresh')"
				/>
			</div>
			<div class="field-col">
				<label class="field-lbl" for="ws-status">Status</label>
				<select
					id="ws-status"
					:value="filters.status"
					class="glass-select"
					@change="onSelectChange('status', $event)"
				>
					<option value="">All statuses</option>
					<option
						v-for="opt in statusOptions"
						:key="opt.value || opt.label"
						:value="opt.value"
					>{{ opt.label }} ({{ opt.count }})</option>
				</select>
			</div>
			<div class="field-col">
				<label class="field-lbl" for="ws-owner">Owner</label>
				<select
					id="ws-owner"
					:value="filters.owner"
					class="glass-select"
					@change="onSelectChange('owner', $event)"
				>
					<option value="">All owners</option>
					<option v-for="opt in ownerOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
				</select>
			</div>
			<div class="field-col">
				<label class="field-lbl" for="ws-stage">Stage</label>
				<select
					id="ws-stage"
					:value="filters.stage"
					class="glass-select"
					@change="onSelectChange('stage', $event)"
				>
					<option value="">All stages</option>
					<option v-for="opt in stageOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
				</select>
			</div>
			<div class="field-col">
				<label class="field-lbl" for="ws-sort">Sort</label>
				<select
					id="ws-sort"
					:value="sortValue"
					class="glass-select"
					@change="onSortChange"
				>
					<option value="modified:desc">Latest activity</option>
					<option value="expected_closing:asc">Expected close: nearest</option>
					<option value="expected_closing:desc">Expected close: farthest</option>
					<option value="opportunity_amount:desc">Value: highest first</option>
					<option value="opportunity_amount:asc">Value: lowest first</option>
					<option value="transaction_date:desc">Created: newest first</option>
				</select>
			</div>
			<div class="filter-btns" style="padding-top: 22px;">
				<button class="btn btn-ghost btn-sm" type="button" @click="$emit('reset')">Reset</button>
				<button class="btn btn-primary btn-sm" type="button" @click="$emit('refresh')">Refresh</button>
			</div>
		</div>
	</div>
</template>

<script setup>
defineProps({
	filters: { type: Object, required: true },
	sortValue: { type: String, required: true },
	statusOptions: { type: Array, required: true },
	ownerOptions: { type: Array, required: true },
	stageOptions: { type: Array, required: true },
});

const emit = defineEmits([
	"update-filter",
	"update-sort",
	"refresh",
	"reset",
]);

function updateFilter(field, value) {
	emit("update-filter", { field, value });
}

function onSelectChange(field, event) {
	updateFilter(field, event.target.value);
	emit("refresh");
}

function onSortChange(event) {
	emit("update-sort", event.target.value);
	emit("refresh");
}
</script>
