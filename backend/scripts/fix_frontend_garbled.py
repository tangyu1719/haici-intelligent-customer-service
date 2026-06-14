"""修复前端 Vue 文件中因编码损坏出现的 ???? 文案。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "frontend" / "src" / "views" / "MainShell.vue"
MM = ROOT / "frontend" / "src" / "components" / "MultimodalPanel.vue"

KNOWLEDGE_BLOCK = r"""            <div v-else-if="route.path === '/knowledge'" class="flex-1 p-6 overflow-y-auto">
        <div class="max-w-5xl mx-auto">
          <div class="flex flex-wrap justify-between items-center gap-3 mb-6">
            <h2 class="text-lg font-black">知识库管理</h2>
            <div class="flex flex-wrap items-center gap-3">
              <!-- 知识库选择器 -->
              <label v-if="kbList.length > 0" class="text-[12px] font-bold text-[#363e42]/60 flex items-center gap-2">
                知识库
                <select v-model="selectedKbId" class="border rounded-lg px-2 py-1.5 text-[12px] font-medium min-w-[140px]" @change="kbQuery.page = 1; loadKnowledge()">
                  <option :value="null">全部文档</option>
                  <option v-for="kb in kbList" :key="kb.id" :value="kb.id">{{ kb.name }} ({{ kb.doc_count }}篇)</option>
                </select>
              </label>
              <button
                v-if="!kbCreating"
                type="button"
                class="text-[11px] font-bold text-[#d97706] border border-[#d97706]/30 rounded-lg px-3 py-1.5 hover:bg-[#d97706]/5 transition-colors"
                @click="kbCreating = true"
              >+ 新建知识库</button>
              <template v-if="kbCreating">
                <input v-model="kbCreateName" type="text" class="border rounded-lg px-2 py-1.5 text-[12px] w-[140px] focus:outline-none focus:border-[#d97706]" placeholder="知识库名称" maxlength="128" />
                <input v-model="kbCreateDesc" type="text" class="border rounded-lg px-2 py-1.5 text-[12px] w-[160px] focus:outline-none focus:border-[#d97706]" placeholder="描述（可选）" maxlength="512" />
                <button type="button" class="text-[11px] font-bold bg-[#363e42] text-white rounded-lg px-3 py-1.5 hover:bg-[#4a5256] transition-colors" @click="createKb">确定</button>
                <button type="button" class="text-[11px] text-[#363e42]/50 hover:text-[#363e42]/70" @click="kbCreating = false">取消</button>
              </template>
              <label class="text-[12px] font-bold text-[#363e42]/60 flex items-center gap-2">
                分块策略
                <select v-model="kbSliceMethod" class="border rounded-lg px-2 py-1.5 text-[12px] font-medium min-w-[160px]">
                  <option v-for="m in kbSliceMethods" :key="m.id" :value="m.id">{{ m.label }}</option>
                </select>
              </label>
              <label v-if="hasPerm('kb:upload')" class="bg-[#363e42] text-white px-5 py-2.5 rounded-xl font-bold text-[13px] cursor-pointer hover:bg-[#4a5256] transition-colors shadow-sm">
                上传文档
                <input type="file" class="hidden" accept=".txt,.md,.pdf,.doc,.docx,.xls,.xlsx,.png,.jpg,.jpeg" @change="uploadKnowledge" />
              </label>
            </div>
          </div>

          <!-- 知识库卡片 -->
          <div v-if="kbList.length > 0" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
            <div
              v-for="kb in kbList"
              :key="kb.id"
              :class="[
                'relative rounded-2xl border-2 p-5 cursor-pointer transition-all duration-200 hover:shadow-lg',
                selectedKbId === kb.id
                  ? 'border-[#d97706] bg-[#d97706]/5 shadow-md'
                  : 'border-[#e5e7eb] bg-white hover:border-[#d97706]/40'
              ]"
              @click="selectedKbId = kb.id; kbQuery.page = 1; loadKnowledge()"
            >
              <div class="flex items-start justify-between mb-3">
                <div class="flex items-center gap-2.5">
                  <div :class="[
                    'w-9 h-9 rounded-xl flex items-center justify-center text-sm font-black',
                    selectedKbId === kb.id ? 'bg-[#d97706] text-white' : 'bg-[#f3f4f6] text-[#363e42]'
                  ]">
                    {{ kb.name.charAt(0).toUpperCase() }}
                  </div>
                  <div>
                    <div class="text-sm font-bold text-[#363e42] leading-tight">{{ kb.name }}</div>
                    <div v-if="kb.description" class="text-[11px] text-[#64748b] mt-0.5 line-clamp-2">{{ kb.description }}</div>
                  </div>
                </div>
                <span v-if="kb.is_default === 1" class="text-[10px] font-bold bg-[#fef3c7] text-[#d97706] px-2 py-0.5 rounded-full">默认</span>
              </div>
              <div class="flex items-center gap-4 text-[11px] text-[#64748b]">
                <span class="flex items-center gap-1">
                  <span class="text-[#d97706]">文档</span> {{ kb.doc_count }} 篇
                </span>
                <span class="flex items-center gap-1">
                  <span class="text-[#d97706]">创建</span> {{ fmtDateTime(kb.created_at) }}
                </span>
              </div>
              <div v-if="selectedKbId === kb.id" class="absolute top-3 right-3 w-5 h-5 bg-[#d97706] rounded-full flex items-center justify-center">
                <span class="text-white text-[10px] font-black">✓</span>
              </div>
            </div>
          </div>

          <!-- 空状态 -->
          <div v-if="kbList.length === 0 && !kbCreating" class="text-center py-16 mb-6 bg-white rounded-2xl border-2 border-dashed border-[#e5e7eb]">
            <div class="text-5xl mb-4">📚</div>
            <h3 class="text-base font-bold text-[#363e42] mb-2">还没有知识库</h3>
            <p class="text-sm text-[#64748b] mb-5 max-w-md mx-auto leading-relaxed">
              创建知识库后，可上传 PDF、Word、Excel 等文档，系统会自动 OCR/VLM 识别并写入向量库，供 AI 问答检索。
            </p>
            <button
              type="button"
              class="inline-flex items-center gap-2 bg-[#d97706] text-white px-5 py-2.5 rounded-xl font-bold text-sm hover:bg-[#c26806] transition-colors shadow-sm"
              @click="kbCreating = true"
            >
              <span class="text-lg">+</span> 创建第一个知识库
            </button>
          </div>

          <p class="text-[11px] text-[#363e42]/50 mb-4">
            含图文档（PDF/DOCX/XLS 等）会先标准化：抽图 → OCR/VLM 识别 → 写入 kb_assets；单文档 VLM 上限
            <strong>{{ kbVlmLimit }}</strong> 张。图片经 <code>/output/kb_assets/...</code> 可在回答界面渲染。
          </p>
          <ListQueryBar
            v-model="kbQuery"
            :sort-options="[
              { value: 'created_at', label: '上传时间' },
              { value: 'filename', label: '文档名' },
              { value: 'status', label: '状态' },
              { value: 'chunk_count', label: '分块数' },
            ]"
            name-placeholder="文档文件名"
            keyword-placeholder="文件名关键词"
            @search="loadKnowledge"
            @reset="resetKbQuery"
          />
          <div class="flex items-center gap-3 mb-3 text-[11px] font-bold text-[#363e42]/60">
            <label>状态筛选
              <select v-model="kbStatusFilter" class="ml-2 border rounded px-2 py-1" @change="kbQuery.page = 1; loadKnowledge()">
                <option value="">全部</option>
                <option value="ready">ready</option>
                <option value="processing">processing</option>
                <option value="failed">failed</option>
              </select>
            </label>
          </div>
          <table class="w-full bg-white rounded-2xl border text-sm overflow-hidden">
            <thead class="bg-[#fcfcfc] text-[#363e42]/60">
              <tr>
                <th class="p-3 text-left">文档</th>
                <th class="p-3 text-left">知识库</th>
                <th class="p-3 text-left">类型</th>
                <th class="p-3 text-left">大小</th>
                <th class="p-3 text-left">图片</th>
                <th class="p-3 text-left">状态</th>
                <th class="p-3 text-left">分块</th>
                <th class="p-3 text-left">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in kbDocs" :key="d.id" class="border-t">
                <td class="p-3">{{ fixDisplayFilename(d.filename) }}</td>
                <td class="p-3 text-[11px] text-[#64748b]">{{ d.kb_name || '未分类' }}</td>
                <td class="p-3 uppercase text-[11px]">{{ d.file_type || '-' }}</td>
                <td class="p-3 text-[11px]">{{ d.file_size_human || (d.file_size_bytes ? `${d.file_size_bytes} B` : '-') }}</td>
                <td class="p-3 text-[11px]">
                  {{ d.image_count ?? 0 }}
                  <span v-if="d.truncated" class="text-[#d97706]">（超上限）</span>
                </td>
                <td class="p-3">{{ d.status }}</td>
                <td class="p-3">{{ d.chunk_count }}</td>
                <td class="p-3"><button v-if="hasPerm('kb:delete')" class="text-red-500" @click="deleteKnowledge(d.id)">删除</button></td>
              </tr>
            </tbody>
          </table>
          <ListPagination v-model:page="kbQuery.page" v-model:size="kbQuery.size" :total="kbTotal" />
        </div>
      </div>

"""

REPLACEMENTS = {
    "?????": "知识库管理",
    "退出登录": "退出登录",
}

MM_REPLACEMENTS = [
    ("S_MAP: Record<string,string> = { pending:'等待', running:'处理中', completed:'已完成', failed:'失败' }", None),
]


def fix_main_shell() -> None:
    text = MAIN.read_text(encoding="utf-8")
    start = text.find("<div v-else-if=\"route.path === '/knowledge'\"")
    end = text.find("<div v-else-if=\"route.path === '/sessions'\"")
    if start < 0 or end < 0:
        raise SystemExit("knowledge block not found")
    text = text[:start] + KNOWLEDGE_BLOCK + text[end:]
    # 修复侧栏退出按钮等零星乱码
    text = text.replace("退出登录", "退出登录")  # noop ensure utf-8
    text = text.replace('>?????<', '>知识库管理<')
    text = text.replace("@click=\"logout\">退出登录", "@click=\"logout\">退出登录")
    if "?????" in text:
        print("WARN: still has ???? in MainShell")
    MAIN.write_text(text, encoding="utf-8", newline="\n")
    print("fixed MainShell.vue")


def fix_multimodal_panel() -> None:
    if not MM.is_file():
        return
    text = MM.read_text(encoding="utf-8")
    pairs = {
        "pending:'等待'": True,
    }
    # 若脚本区已是乱码字节，整段替换 S_MAP 等
    import re

    text = re.sub(
        r"S_MAP: Record<string,string> = \{[^}]+\}",
        "S_MAP: Record<string,string> = { pending:'等待', running:'处理中', completed:'已完成', failed:'失败' }",
        text,
        count=1,
    )
    fixes = {
        "上传失败": "上传失败",
        "粘贴文本": "粘贴文本",
        "提交失败，请重试": "提交失败，请重试",
        "已提交": "已提交",
        "删除该任务记录？": "删除该任务记录？",
        "处理任务": "处理任务",
        "上传文件": "上传文件",
        "点击左侧任务查看详情和实时日志": "点击左侧任务查看详情和实时日志",
    }
    for old, new in fixes.items():
        if old not in text and "?" in text:
            pass
    MM.write_text(text, encoding="utf-8", newline="\n")
    print("fixed MultimodalPanel.vue")


if __name__ == "__main__":
    fix_main_shell()
    fix_multimodal_panel()
