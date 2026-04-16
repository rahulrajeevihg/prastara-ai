<template>
	<div class="pw-root">

		<!-- ── Top Navigation ─────────────────────────── -->
		<nav class="pw-nav">
			<div class="nav-brand">
				<div class="nav-logo">
					<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
				</div>
				<div>
					<p class="nav-name">Prastara AI</p>
					<p class="nav-sub">Sales Estimation</p>
				</div>
			</div>
			<div class="nav-actions">
				<a class="btn btn-ghost btn-sm" href="/app" title="Go to ERPNext Desk">← ERPNext</a>
				<button class="btn btn-ghost btn-sm" type="button" @click="toggleTheme">
					{{ theme === 'light' ? 'Dark' : 'Light' }}
				</button>
				<button class="btn btn-glass btn-sm" type="button" @click="openOpportunityList">All Opportunities</button>
				<button class="btn btn-primary btn-sm" type="button" @click="createNewOpportunity">+ New</button>
			</div>
		</nav>

		<!-- ── List View ─────────────────────────────── -->
		<template v-if="currentView === 'list'">
			<SalesWorkspaceListView
				:filters="filters"
				:sort-value="sortValue"
				:active-sort-label="activeSortLabel"
				:state="state"
				:format-currency="formatCurrency"
				:format-integer="formatInteger"
				:format-date="formatDate"
				:format-date-time="formatDateTime"
				:normalize-status="normalizeStatus"
				@update-filter="updateFilter"
				@update-sort="updateSort"
				@refresh="refreshData()"
				@reset="resetFilters"
				@load-more="loadMore"
				@open-estimation="openEstimation"
				@open-opportunity="openOpportunity"
				@create-opportunity="createNewOpportunity"
			/>
		</template>

		<!-- ── Estimation View ─────────────────────────── -->
		<template v-else-if="currentView === 'estimation'">
			<EstimationWorkspace
				:opportunity-name="selectedOpportunity"
				:theme="theme"
				@back="goBack"
				@toggle-theme="toggleTheme"
			/>
		</template>

	</div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, shallowRef, watch } from "vue";
import { callWorkspaceApi } from "./api";
import EstimationWorkspace from "./EstimationWorkspace.vue";
import SalesWorkspaceListView from "./SalesWorkspaceListView.vue";

const currentView = shallowRef("list");
const selectedOpportunity = shallowRef("");
const theme = shallowRef("light");

const filters = reactive({
	search: "",
	status: "",
	owner: "",
	stage: "",
});

const sortValue = shallowRef("modified:desc");

const state = reactive({
	loading: true,
	loadingMore: false,
	error: "",
	items: [],
	statusOptions: [],
	ownerOptions: [],
	stageOptions: [],
	meta: {
		total_count: 0,
		has_more: false,
		start: 0,
		page_length: 12,
		sort_by: "modified",
		sort_order: "desc",
	},
	summary: {
		total_open: 0,
		total_value: 0,
		active_pipeline: 0,
	},
});

const activeSortLabel = computed(() => {
	const labels = {
		"modified:desc": "Latest activity first",
		"expected_closing:asc": "Nearest expected close first",
		"expected_closing:desc": "Farthest expected close first",
		"opportunity_amount:desc": "Highest value first",
		"opportunity_amount:asc": "Lowest value first",
		"transaction_date:desc": "Newest opportunities first",
	};
	return labels[sortValue.value] || "Latest activity first";
});

async function refreshData(options = {}) {
	const { append = false } = options;
	const start = append ? state.items.length : 0;
	const [sortBy, sortOrder] = sortValue.value.split(":");
	state.loading = !append;
	state.loadingMore = append;
	if (!append) {
		state.error = "";
	}

	try {
		const payload = await callWorkspaceApi({
			search: filters.search,
			status: filters.status,
			owner: filters.owner,
			stage: filters.stage,
			sort_by: sortBy,
			sort_order: sortOrder,
			start,
			page_length: state.meta.page_length || 12,
		});

		const nextItems = payload.items || [];
		state.items = append ? [...state.items, ...nextItems] : nextItems;
		state.statusOptions = payload.filters?.status_options || [];
		state.ownerOptions = payload.filters?.owner_options || [];
		state.stageOptions = payload.filters?.stage_options || [];
		state.meta = payload.meta || state.meta;
		state.summary = payload.summary || state.summary;
	} catch (error) {
		state.error = error?.message || "An unexpected error occurred while loading opportunities.";
	} finally {
		state.loading = false;
		state.loadingMore = false;
	}
}

function resetFilters() {
	filters.search = "";
	filters.status = "";
	filters.owner = "";
	filters.stage = "";
	sortValue.value = "modified:desc";
	refreshData();
}

function formatCurrency(value, currency = "AED") {
	if (!value) return "AED 0";
	return new Intl.NumberFormat(undefined, {
		style: "currency",
		currency: currency || "AED",
		maximumFractionDigits: 0,
	}).format(value);
}

function formatInteger(value) {
	return new Intl.NumberFormat().format(value || 0);
}

function formatDate(value) {
	if (!value) return "TBD";
	return new Intl.DateTimeFormat(undefined, {
		month: "short", day: "numeric", year: "numeric",
	}).format(new Date(value));
}

function formatDateTime(value) {
	if (!value) return "recently";
	return new Intl.DateTimeFormat(undefined, {
		month: "short", day: "numeric",
		hour: "numeric", minute: "2-digit",
	}).format(new Date(value));
}

function normalizeStatus(status) {
	return (status || "draft").toLowerCase().replaceAll(" ", "-");
}

// ── Routing ──────────────────────────────────────────────────────────────────

function openEstimation(name) {
	selectedOpportunity.value = name;
	currentView.value = 'estimation';
	history.pushState(null, '', '#estimation/' + encodeURIComponent(name));
}

function goBack() {
	currentView.value = 'list';
	history.replaceState(null, '', window.location.pathname + window.location.search);
}

function parseHash() {
	const hash = window.location.hash.slice(1);
	if (hash.startsWith('estimation/')) {
		const name = decodeURIComponent(hash.slice('estimation/'.length));
		if (name) {
			selectedOpportunity.value = name;
			currentView.value = 'estimation';
			return;
		}
	}
	currentView.value = 'list';
}

function onHashChange() {
	const hash = window.location.hash.slice(1);
	if (hash.startsWith('estimation/')) {
		const name = decodeURIComponent(hash.slice('estimation/'.length));
		if (name) {
			selectedOpportunity.value = name;
			currentView.value = 'estimation';
			return;
		}
	}
	currentView.value = 'list';
}

// ── Navigation ───────────────────────────────────────────────────────────────

function openOpportunity(name) {
	window.location.href = `/app/opportunity/${encodeURIComponent(name)}`;
}

function openOpportunityList() {
	window.location.href = "/app/opportunity/view/list";
}

function loadMore() {
	if (state.loadingMore || !state.meta.has_more) return;
	refreshData({ append: true });
}

function createNewOpportunity() {
	window.location.href = '/app/opportunity/new-opportunity-1';
}

function updateFilter({ field, value }) {
	if (!(field in filters)) return;
	filters[field] = value;
}

function updateSort(value) {
	sortValue.value = value || "modified:desc";
}

function applyTheme(nextTheme) {
	theme.value = nextTheme === "dark" ? "dark" : "light";
	document.documentElement.setAttribute("data-theme", theme.value);
}

function toggleTheme() {
	applyTheme(theme.value === "light" ? "dark" : "light");
}

onMounted(() => {
	const savedTheme = window.localStorage.getItem("prastara-ai-sales-workspace-theme");
	applyTheme(savedTheme || "light");
	parseHash();
	refreshData();
	window.addEventListener('hashchange', onHashChange);
});

onUnmounted(() => {
	window.removeEventListener('hashchange', onHashChange);
});

watch(theme, (nextTheme) => {
	window.localStorage.setItem("prastara-ai-sales-workspace-theme", nextTheme);
});
</script>
