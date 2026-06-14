<script setup lang="ts">
export interface FlowStage {
  id: string
  label: string
  count: number
  desc?: string
}

defineProps<{
  title?: string
  stages: FlowStage[]
}>()
</script>

<template>
  <div class="flow-chart">
    <h4 v-if="title" class="flow-title">{{ title }}</h4>
    <div class="flow-track">
      <template v-for="(stage, idx) in stages" :key="stage.id">
        <div class="flow-node">
          <div class="flow-node-count">{{ stage.count }}</div>
          <div class="flow-node-label">{{ stage.label }}</div>
          <div v-if="stage.desc" class="flow-node-desc">{{ stage.desc }}</div>
        </div>
        <div v-if="idx < stages.length - 1" class="flow-arrow" aria-hidden="true">
          <span class="flow-arrow-line" />
          <i class="fas fa-chevron-right flow-arrow-icon" />
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.flow-chart {
  width: 100%;
}
.flow-title {
  margin: 0 0 14px;
  font-size: 13px;
  font-weight: 800;
  color: #b45309;
}
.flow-track {
  display: flex;
  align-items: stretch;
  gap: 0;
  overflow-x: auto;
  padding-bottom: 4px;
}
.flow-node {
  flex: 1;
  min-width: 108px;
  padding: 14px 12px;
  text-align: center;
  background: linear-gradient(180deg, #fffbeb 0%, #fff 100%);
  border: 1px solid #fde68a;
  border-radius: 12px;
  box-shadow: 0 1px 3px rgba(217, 119, 6, 0.08);
}
.flow-node-count {
  font-size: 22px;
  font-weight: 800;
  color: #b45309;
  line-height: 1.2;
}
.flow-node-label {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 700;
  color: #1f2937;
}
.flow-node-desc {
  margin-top: 4px;
  font-size: 11px;
  color: #6b7280;
  line-height: 1.4;
}
.flow-arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  flex-shrink: 0;
  color: #d97706;
}
.flow-arrow-line {
  display: none;
}
.flow-arrow-icon {
  font-size: 12px;
  opacity: 0.7;
}
@media (max-width: 720px) {
  .flow-track {
    flex-direction: column;
    align-items: stretch;
  }
  .flow-arrow {
    width: 100%;
    height: 24px;
    transform: rotate(90deg);
  }
}
</style>
