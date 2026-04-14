<template>
	<div class="ew-panel glass">
		<p class="ew-panel-kicker">Step 1</p>
		<h2 class="ew-panel-title">Define Project Scope</h2>

		<div class="ew-section">
			<label class="ew-label">Project Requirements Brief</label>
			<textarea
				:model-value="scopeText"
				class="scope-ta"
				placeholder="Describe the project in detail — room types, total area (sqft / sqm), required finishes, grades, brands, special requirements.&#10;&#10;Example: 2,500 sqft office fit-out in Business Bay. Reception with marble flooring, 5 private offices with carpet, open-plan area with raised flooring. Full gypsum ceiling with indirect LED lighting throughout. Pantry with full joinery."
				@input="$emit('update:scopeText', $event.target.value)"
			></textarea>
			<p class="ew-hint">Include total area, room breakdown, finish grades, and any specific preferences for more accurate AI estimates.</p>
		</div>

		<div class="ew-section">
			<label class="ew-label">Drawings &amp; Supporting Documents</label>
			<div
				class="drop-zone"
				:class="{ dragging: isDragging }"
				@click="$refs.fileInput.click()"
				@dragover.prevent="isDragging = true"
				@dragleave.prevent="isDragging = false"
				@drop.prevent="handleDrop"
			>
				<div class="dz-icon">📂</div>
				<p class="dz-label">{{ isDragging ? 'Drop files to upload' : 'Drop files here or click to browse' }}</p>
				<button class="btn btn-glass btn-sm" type="button" @click.stop="$refs.fileInput.click()">Browse Files</button>
				<p class="ew-hint" style="margin-top:8px;">PDF briefs, DWG / DXF drawings, TXT notes</p>
			</div>
			<input
				type="file"
				ref="fileInput"
				multiple
				accept=".pdf,.dwg,.dxf,.txt"
				@change="$emit('upload-files', $event)"
				style="display:none"
			/>

			<div v-if="files.length" style="margin-top:12px;">
				<div v-for="(file, idx) in files" :key="idx" class="file-item">
					<div class="file-type-icon">{{ file.name.endsWith('.pdf') ? '📄' : '📐' }}</div>
					<div class="file-info">
						<p class="file-name">{{ file.name }}</p>
						<p class="file-size">{{ formatFileSize(file.size) }}</p>
						<p v-if="file.error" class="file-error">{{ file.error }}</p>
					</div>
					<span v-if="file.uploaded" class="file-ok">✓ Ready</span>
					<span v-else-if="file.uploading" class="file-uploading">Uploading…</span>
					<button
						v-else
						class="btn btn-ghost btn-icon"
						style="color:var(--red); font-size:1rem;"
						title="Remove"
						@click="$emit('remove-file', idx)"
					>✕</button>
				</div>
			</div>

			<div
				v-if="hasOpportunityReferences"
				class="opp-ref-block"
			>
				<div class="opp-ref-head">
					<div>
						<p class="opp-ref-title">Opportunity References</p>
						<p class="opp-ref-copy">These files, notes, and messages from opportunity creation are included automatically in AI estimation.</p>
					</div>
					<div class="opp-ref-stats">
						<span v-if="opportunityReferences.files.length" class="opp-ref-stat">{{ opportunityReferences.files.length }} file<span v-if="opportunityReferences.files.length !== 1">s</span></span>
						<span v-if="opportunityReferences.notes_text" class="opp-ref-stat">Notes</span>
						<span v-if="opportunityReferences.comments.length" class="opp-ref-stat">{{ opportunityReferences.comments.length }} message<span v-if="opportunityReferences.comments.length !== 1">s</span></span>
					</div>
				</div>

				<div v-if="opportunityReferences.files.length" class="opp-ref-group">
					<p class="opp-ref-label">Attached Files</p>
					<a
						v-for="file in opportunityReferences.files"
						:key="file.name"
						class="file-item opp-ref-file"
						:href="file.file_url"
						target="_blank"
						rel="noreferrer"
					>
						<div class="file-type-icon">{{ file.file_name?.toLowerCase().endsWith('.pdf') ? '📄' : '📎' }}</div>
						<div class="file-info">
							<p class="file-name">{{ file.file_name }}</p>
							<p class="file-size">
								{{ formatFileSize(file.file_size || 0) }}
								<span v-if="file.creation">· Added {{ formatDateTime(file.creation) }}</span>
							</p>
						</div>
						<span class="file-ok">Reference</span>
					</a>
				</div>

				<div v-if="opportunityReferences.notes_text" class="opp-ref-group">
					<p class="opp-ref-label">Opportunity Notes</p>
					<div class="opp-ref-note">{{ opportunityReferences.notes_text }}</div>
				</div>

				<div v-if="opportunityReferences.comments.length" class="opp-ref-group">
					<div class="opp-ref-group-head">
						<p class="opp-ref-label">Messages &amp; Comments</p>
						<button
							v-if="hasMoreComments"
							class="btn btn-glass btn-sm"
							type="button"
							@click="showAllComments = !showAllComments"
						>
							{{ showAllComments ? 'Show Fewer' : `Show All ${opportunityReferences.comments.length}` }}
						</button>
					</div>
					<div class="opp-comment-list">
						<div v-for="comment in displayedComments" :key="comment.name" class="opp-comment">
						<div class="opp-comment-meta">
							<strong>{{ comment.comment_by || 'Unknown' }}</strong>
							<span>{{ comment.comment_type || 'Comment' }} · {{ formatDateTime(comment.creation) }}</span>
						</div>
						<p class="opp-comment-body">{{ comment.content }}</p>
					</div>
					</div>
				</div>
			</div>
		</div>

		<div style="display:flex; justify-content:flex-end; margin-top:32px;">
			<button
				class="btn btn-primary btn-lg"
				@click="$emit('generate-estimation')"
				:disabled="processing || (!scopeText && !files.length && !opportunityReferences.files.length && !opportunityReferences.notes_text && !opportunityReferences.comments.length)"
			>
				{{ processing ? '⏳ Generating…' : '✦ Generate AI Estimation' }}
			</button>
		</div>
	</div>
</template>

<script setup>
import { computed, ref } from 'vue';

const props = defineProps({
	scopeText: { type: String, default: '' },
	files: { type: Array, default: () => [] },
	opportunityReferences: {
		type: Object,
		default: () => ({ files: [], notes_text: '', comments: [], context_text: '' }),
	},
	processing: { type: Boolean, default: false },
	formatFileSize: { type: Function, required: true },
	formatDateTime: { type: Function, required: true },
});

const emit = defineEmits(['update:scopeText', 'upload-files', 'remove-file', 'generate-estimation']);

const isDragging = ref(false);
const showAllComments = ref(false);

const hasOpportunityReferences = computed(() => (
	props.opportunityReferences.files.length
	|| props.opportunityReferences.notes_text
	|| props.opportunityReferences.comments.length
));

const hasMoreComments = computed(() => props.opportunityReferences.comments.length > 4);
const displayedComments = computed(() => (
	showAllComments.value
		? props.opportunityReferences.comments
		: props.opportunityReferences.comments.slice(0, 4)
));

function handleDrop(event) {
	isDragging.value = false;
	emit('upload-files', event);
}
</script>
