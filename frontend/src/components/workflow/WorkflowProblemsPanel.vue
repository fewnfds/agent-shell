<script setup lang="ts">
import { useValidationIssuePresentation } from '@/composables/useValidationIssuePresentation'
import type { WorkflowCanvasProblem } from '@/domain/workflowCanvasProblems'

defineProps<{
  problems: WorkflowCanvasProblem[]
}>()

const emit = defineEmits<{
  selectProblem: [problem: WorkflowCanvasProblem]
}>()

const issuePresentation = useValidationIssuePresentation()

function problemKey(problem: WorkflowCanvasProblem, index: number): string {
  return `${problem.source}:${problem.code}:${problem.owner_id}:${problem.path}:${index}`
}
</script>

<template>
  <section class="workflow-tool-panel" aria-labelledby="workflow-problems-title">
    <header class="workflow-tool-panel-header">
      <h2 id="workflow-problems-title" class="workflow-tool-panel-title">
        {{ $t('workflows.editor.canvasProblems.title') }}
      </h2>
    </header>

    <div class="workflow-tool-panel-body" aria-live="polite">
      <p v-if="problems.length === 0" class="workflow-problems-empty">
        {{ $t('workflows.editor.canvasProblems.none') }}
      </p>
      <div v-else class="workflow-problems-list">
        <button
          v-for="(problem, index) in problems"
          :key="problemKey(problem, index)"
          class="workflow-problems-item"
          type="button"
          @click="emit('selectProblem', problem)"
        >
          <span class="workflow-problems-message">{{ issuePresentation.message(problem) }}</span>
          <span v-if="problem.owner_id" class="workflow-problems-owner">{{ problem.owner_id }}</span>
        </button>
      </div>
    </div>
  </section>
</template>
