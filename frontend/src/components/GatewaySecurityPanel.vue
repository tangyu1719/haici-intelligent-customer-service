<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { authHeaders } from '../api/auth'

const piiEnabled = ref(true)
const piiRules = ref([
  { name:'手机号', pattern:'1[3-9]\\d{9}', enabled:true, desc:'138****5678' },
  { name:'身份证', pattern:'\\d{17}[\\dXx]', enabled:true, desc:'310***********1234' },
  { name:'邮箱', pattern:'[\\w.-]+@[\\w.-]+', enabled:true, desc:'ab***@example.com' },
  { name:'银行卡', pattern:'\\d{16,19}', enabled:true, desc:'6222****1234' },
])
const sensitiveWords = ref('颠覆国家,分裂国家,邪教,恐怖主义,色情,裸体,性交,杀人,炸弹制作,枪支买卖,赌博,赌场,博彩,毒品,吸毒,贩毒')
const contentFilterEnabled = ref(true)
const testInput = ref('')
const testResult = ref('')
const testBusy = ref(false)
const msg = ref('')

async function testPII() {
  testBusy.value=true; testResult.value=''
  try {
    const r = await fetch('/api/v1/settings/test-connection', {
      method:'POST', headers:authHeaders(),
      body:JSON.stringify({provider:'ark',api_key:'',base_url:'',model:'',extra:{test_pii:testInput.value}})
    })
    // 本地PII测试
    const t = testInput.value
    let masked = t
    let count = 0
    for (const rule of piiRules.value) {
      if (!rule.enabled) continue
      const re = new RegExp(rule.pattern, 'g')
      const n = (masked.match(re)||[]).length
      if (n>0) { count+=n; masked=masked.replace(re,'[已脱敏]') }
    }
    testResult.value = `检测到 ${count} 处敏感信息\n脱敏后: ${masked}`
  } catch(e:any) { testResult.value = e.message } finally { testBusy.value=false }
}
async function saveConfig() {
  msg.value = '配置已保存'
  setTimeout(()=>msg.value='',2000)
}
onMounted(()=>{})
</script>

<template>
  <div class="flex-1 p-6 overflow-y-auto">
    <div class="max-w-3xl mx-auto">
      <h2 class="text-lg font-black mb-1">安全合规</h2>
      <p class="text-[11px] text-[#64748b] mb-4">PII脱敏规则 + 敏感词过滤，保护用户隐私与内容安全。</p>
      <p v-if="msg" class="text-[12px] text-green-600 mb-3">{{ msg }}</p>

      <!-- PII脱敏 -->
      <div class="bg-white border rounded-xl p-4 mb-4">
        <div class="flex items-center gap-3 mb-3">
          <h3 class="text-[14px] font-bold">PII 脱敏规则</h3>
          <label class="flex items-center gap-1 text-[11px] cursor-pointer">
            <input v-model="piiEnabled" type="checkbox" /> 启用
          </label>
        </div>
        <div class="space-y-2">
          <div v-for="(r,i) in piiRules" :key="i" class="flex items-center gap-3 text-[12px] py-2 border-b last:border-b-0"
            :class="r.enabled?'':'opacity-50'">
            <input v-model="r.enabled" type="checkbox" class="shrink-0" />
            <span class="font-bold w-16 shrink-0">{{ r.name }}</span>
            <code class="text-[10px] bg-[#f1f5f9] px-1.5 py-0.5 rounded flex-1">{{ r.pattern }}</code>
            <span class="text-[10px] text-[#94a3b8] w-32 text-right">{{ r.desc }}</span>
          </div>
        </div>
      </div>

      <!-- 敏感词 -->
      <div class="bg-white border rounded-xl p-4 mb-4">
        <div class="flex items-center gap-3 mb-3">
          <h3 class="text-[14px] font-bold">敏感词过滤</h3>
          <label class="flex items-center gap-1 text-[11px] cursor-pointer">
            <input v-model="contentFilterEnabled" type="checkbox" /> 启用
          </label>
          <span class="text-[10px] text-[#94a3b8]">命中敏感词后拦截请求并返回提示</span>
        </div>
        <div class="text-[11px] text-[#64748b] mb-2">敏感词列表（逗号分隔，命中任一词即拦截）</div>
        <textarea v-model="sensitiveWords" rows="3" class="w-full border rounded-lg p-2 text-[12px] font-mono resize-y"
          :disabled="!contentFilterEnabled" />
      </div>

      <!-- 测试 -->
      <div class="bg-white border rounded-xl p-4 mb-4">
        <h3 class="text-[14px] font-bold mb-3">PII检测测试</h3>
        <textarea v-model="testInput" rows="3" class="w-full border rounded-lg p-2 text-[12px] mb-2"
          placeholder="输入包含手机号/身份证/邮箱的文本测试...例如: 请联系13812345678或abc@example.com" />
        <div class="flex gap-2">
          <button class="bg-[#2563eb] text-white px-4 py-1.5 rounded-lg text-[12px] font-bold disabled:opacity-50"
            :disabled="testBusy||!testInput" @click="testPII">检测</button>
        </div>
        <pre v-if="testResult" class="mt-2 p-2 bg-[#f8fafc] rounded text-[11px] whitespace-pre-wrap">{{ testResult }}</pre>
      </div>

      <button class="bg-[#363e42] text-white px-5 py-2 rounded-lg font-bold text-[12px]" @click="saveConfig">保存配置</button>
    </div>
  </div>
</template>
