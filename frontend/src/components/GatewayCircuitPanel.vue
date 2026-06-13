<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

interface NodeHealth { node_id:string; state:string; fail_count:number; is_available:boolean; total_requests:number; total_failures:number; failure_rate:number; degrade_count:number; last_fail_reason:string; last_fail_time:string; history:{time:string;state:string;message:string}[] }
const healthList = ref<NodeHealth[]>([])
const msg = ref('')

const stateLabel = (s:string)=>({active:'正常',degraded:'已熔断',half_open:'半开探测'} as Record<string,string>)[s]||s
const stateColor = (s:string)=>({active:'bg-green-100 text-green-700',degraded:'bg-red-100 text-red-600',half_open:'bg-amber-100 text-amber-700'} as Record<string,string>)[s]||''

async function loadHealth() {
  try {
    const r = await fetch('/api/v1/settings/gateway-nodes/health', { headers:authHeaders() })
    if (r.ok) healthList.value = (await r.json()).nodes || []
  } catch {}
}
async function recover(nodeId:string) {
  await fetch(`/api/v1/settings/gateway-nodes/${encodeURIComponent(nodeId)}/health/recover`,{method:'POST',headers:authHeaders()})
  msg.value='节点已恢复'; await loadHealth()
}
async function degrade(nodeId:string) {
  const reason = prompt('降级原因(可选):') || '手动降级'
  await fetch(`/api/v1/settings/gateway-nodes/${encodeURIComponent(nodeId)}/health/degrade?reason=${encodeURIComponent(reason)}`,{method:'POST',headers:authHeaders()})
  msg.value='节点已降级'; await loadHealth()
}
onMounted(()=>loadHealth())
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-4xl mx-auto">
      <div class="flex items-center justify-between mb-4">
        <div>
          <h2 class="text-lg font-black">熔断监控</h2>
          <p class="text-[11px] text-[#64748b]">节点健康状态实时监控：active→degraded→half_open 状态机。</p>
        </div>
        <button class="text-[12px] font-bold border px-3 py-1.5 rounded-lg" @click="loadHealth">刷新</button>
      </div>
      <p v-if="msg" class="text-[12px] text-green-600 mb-3">{{ msg }}</p>

      <div v-if="!healthList.length" class="text-center py-16 text-[#94a3b8] text-sm">
        暂无节点健康数据<br><span class="text-[10px]">在Agent网关中添加节点并产生请求后会出现</span>
      </div>

      <div v-for="h in healthList" :key="h.node_id" class="bg-white border rounded-xl p-4 mb-3">
        <div class="flex items-center justify-between mb-3">
          <div class="flex items-center gap-3">
            <span class="font-bold text-[14px]">{{ h.node_id }}</span>
            <span class="text-[11px] px-2 py-0.5 rounded-full font-bold" :class="stateColor(h.state)">{{ stateLabel(h.state) }}</span>
            <span class="text-[11px] text-[#94a3b8]">可用: {{ h.is_available?'是':'否' }}</span>
          </div>
          <div class="flex gap-2">
            <button v-if="h.state==='degraded'" class="text-[11px] px-3 py-1 border rounded bg-green-50 text-green-600 font-bold" @click="recover(h.node_id)">强制恢复</button>
            <button v-if="h.state==='active'" class="text-[11px] px-3 py-1 border rounded bg-amber-50 text-amber-600 font-bold" @click="degrade(h.node_id)">强制降级</button>
          </div>
        </div>

        <!-- 指标 -->
        <div class="grid grid-cols-5 gap-3 mb-3 text-center">
          <div class="bg-[#f8fafc] rounded-lg p-2">
            <div class="text-[18px] font-black text-[#363e42]">{{ h.total_requests }}</div>
            <div class="text-[9px] text-[#94a3b8]">总请求</div>
          </div>
          <div class="bg-[#f8fafc] rounded-lg p-2">
            <div class="text-[18px] font-black text-red-500">{{ h.total_failures }}</div>
            <div class="text-[9px] text-[#94a3b8]">总失败</div>
          </div>
          <div class="bg-[#f8fafc] rounded-lg p-2">
            <div class="text-[18px] font-black" :class="h.failure_rate>0.1?'text-red-500':'text-green-500'">{{ (h.failure_rate*100).toFixed(1) }}%</div>
            <div class="text-[9px] text-[#94a3b8]">失败率</div>
          </div>
          <div class="bg-[#f8fafc] rounded-lg p-2">
            <div class="text-[18px] font-black text-[#363e42]">{{ h.fail_count }}</div>
            <div class="text-[9px] text-[#94a3b8]">连续失败</div>
          </div>
          <div class="bg-[#f8fafc] rounded-lg p-2">
            <div class="text-[18px] font-black text-amber-500">{{ h.degrade_count }}</div>
            <div class="text-[9px] text-[#94a3b8]">累计熔断</div>
          </div>
        </div>

        <!-- 最后失败原因 -->
        <div v-if="h.last_fail_reason" class="text-[10px] text-red-500 bg-red-50 rounded-lg px-3 py-1.5 mb-2">{{ h.last_fail_reason }} · {{ h.last_fail_time }}</div>

        <!-- 事件历史 -->
        <details class="text-[10px]">
          <summary class="text-[#94a3b8] cursor-pointer">事件历史 (最近{{ h.history?.length||0 }}条)</summary>
          <div v-for="(ev,i) in (h.history||[])" :key="i" class="flex gap-2 py-0.5 font-mono">
            <span class="text-[#94a3b8] w-10">{{ ev.time }}</span>
            <span class="px-1 rounded text-[9px]" :class="ev.state==='active'?'bg-green-100':ev.state==='degraded'?'bg-red-100':'bg-amber-100'">{{ ev.state }}</span>
            <span class="text-[#64748b]">{{ ev.message }}</span>
          </div>
        </details>
      </div>
    </div>
  </div>
</template>
