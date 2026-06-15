<script setup lang="ts">
import { useRouter } from 'vue-router'

export interface SidebarMenuNode {
  id: number
  name: string
  path?: string
  menu_type: string
  children?: SidebarMenuNode[]
}

const props = defineProps<{
  nodes: SidebarMenuNode[]
  depth?: number
  isSidebarOpen: boolean
  activePath: string
  expandedMenuIds: Set<number>
}>()

const emit = defineEmits<{ toggle: [id: number] }>()
const router = useRouter()
const depth = props.depth ?? 0

function containsActivePath(node: SidebarMenuNode): boolean {
  if (node.path && node.path === props.activePath) return true
  return (node.children || []).some((c) => containsActivePath(c))
}

function isGroupActive(node: SidebarMenuNode): boolean {
  return containsActivePath(node) && node.path !== props.activePath
}

function onGroupClick(node: SidebarMenuNode): void {
  if (!props.isSidebarOpen) {
    const firstLeaf = findFirstLeaf(node)
    if (firstLeaf?.path) router.push(firstLeaf.path)
    return
  }
  emit('toggle', node.id)
}

function findFirstLeaf(node: SidebarMenuNode): SidebarMenuNode | null {
  if (node.menu_type === 'C' && node.path) return node
  for (const c of node.children || []) {
    const hit = findFirstLeaf(c)
    if (hit) return hit
  }
  return null
}
</script>

<template>
  <template v-for="node in nodes" :key="node.id">
    <!-- 目录：可展开 -->
    <div v-if="node.menu_type === 'M' && node.children?.length" class="flex flex-col gap-0.5">
      <button
        type="button"
        class="w-full flex items-center justify-between rounded-xl text-[12px] font-bold transition-all"
        :class="[
          depth > 0 ? 'py-2 px-3 text-[11px]' : 'py-2.5 px-3',
          isGroupActive(node) ? 'bg-[#363e42]/10 text-[#363e42]' : 'text-[#363e42] hover:bg-[#363e42]/5',
        ]"
        @click="onGroupClick(node)"
      >
        <span v-if="isSidebarOpen">{{ node.name }}</span>
        <span v-else class="w-full text-center text-[10px]">{{ node.name.slice(0, 2) }}</span>
        <i
          v-if="isSidebarOpen"
          class="fas text-[10px] text-[#363e42]/40"
          :class="expandedMenuIds.has(node.id) ? 'fa-chevron-down' : 'fa-chevron-right'"
        ></i>
      </button>
      <div
        v-if="isSidebarOpen && expandedMenuIds.has(node.id)"
        class="ml-2 pl-2 border-l border-[#363e42]/10 flex flex-col gap-0.5"
      >
        <SidebarMenuTree
          :nodes="node.children"
          :depth="depth + 1"
          :is-sidebar-open="isSidebarOpen"
          :active-path="activePath"
          :expanded-menu-ids="expandedMenuIds"
          @toggle="emit('toggle', $event)"
        />
      </div>
    </div>

    <!-- 叶子：可点击路由 -->
    <router-link
      v-else-if="node.menu_type === 'C' && node.path"
      :to="node.path"
      class="w-full flex items-center rounded-lg text-[11px] font-bold transition-all"
      :class="[
        depth > 0 ? 'py-2 px-3' : 'py-2.5 px-3 rounded-xl text-[12px]',
        activePath === node.path ? 'bg-[#363e42] text-white' : 'text-[#363e42]/80 hover:bg-[#363e42]/5',
      ]"
    >
      <span v-if="isSidebarOpen">{{ node.name }}</span>
      <span v-else class="w-full text-center text-[10px]">{{ node.name.slice(0, 2) }}</span>
    </router-link>
  </template>
</template>
