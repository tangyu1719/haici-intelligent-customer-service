import logging
import hashlib
import os
from typing import Dict, Optional
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from config import settings
import torch

logger = logging.getLogger(__name__)

RESPONSE_CACHE: Dict[str, str] = {}
CACHE_MAX_SIZE = 1000

class LLMWrapper:
    def __init__(self):
        self._llm_instance = None

    @property
    def llm(self) -> ChatOpenAI:
        if self._llm_instance is None:
            self._llm_instance = ChatOpenAI(
                model=settings.GEMINI_MODEL,
                api_key=settings.GEMINI_API_KEY,
                base_url=settings.GEMINI_BASE_URL,
                temperature=0.1,
                max_tokens=1024,
                timeout=10,
                max_retries=1
            )
        return self._llm_instance

    def _get_cache_key(self, prompt: str, temperature: float) -> str:
        return hashlib.md5(f"{prompt}:{temperature}".encode()).hexdigest()

    def call(self, prompt: str, temperature: float = 0.1, max_tokens: int = 1024) -> str:
        cache_key = self._get_cache_key(prompt, temperature)
        if cache_key in RESPONSE_CACHE:
            return RESPONSE_CACHE[cache_key]

        try:
            messages = [HumanMessage(content=prompt)]
            response = self.llm.invoke(messages)
            result = response.content.strip()

            if len(RESPONSE_CACHE) >= CACHE_MAX_SIZE:
                RESPONSE_CACHE.clear()
            RESPONSE_CACHE[cache_key] = result
            return result
        except Exception as e:
            logger.error("LLM调用失败: %s", str(e))
            return "服务暂时不可用"

    def call_with_image(self, prompt: str, image_data: bytes) -> str:
        import base64
        try:
            b64 = base64.b64encode(image_data).decode()
            messages = [
                HumanMessage(content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
                ])
            ]
            response = self.llm.invoke(messages)
            return response.content.strip()
        except Exception as e:
            logger.debug("图片解析跳过: %s", str(e))
            return ""

_llm_wrapper: Optional[LLMWrapper] = None

def get_llm() -> LLMWrapper:
    global _llm_wrapper
    if _llm_wrapper is None:
        _llm_wrapper = LLMWrapper()
    return _llm_wrapper

_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        model_path = settings.EMBEDDING_MODEL_PATH

        if ("/" in model_path or "\\" in model_path) and not os.path.exists(model_path):
            logger.warning("未找到本地路径，将自动拉取开源模型")
            model_path = "BAAI/bge-large-zh-v1.5"

        logger.info("正在加载向量模型: %s", model_path)
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError:
            from langchain_community.embeddings import HuggingFaceEmbeddings

        _embedder = HuggingFaceEmbeddings(
            model_name=model_path,
            model_kwargs={'device': 'cpu'},
            encode_kwargs={'normalize_embeddings': True}
        )
    return _embedder

class BGEReranker:
    def __init__(self, model_path):
        # 弃用有Bug的CrossEncoder，使用原生transformers精准加载
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, AutoConfig
        from safetensors.torch import load_file as sf_load
        import os
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        config = AutoConfig.from_pretrained(model_path)
        with torch.device("cpu"):
            self.model = AutoModelForSequenceClassification.from_config(config)
        sd = sf_load(os.path.join(model_path, "model.safetensors"), device="cpu")
        self.model.load_state_dict(sd, strict=False, assign=True)
        self.model = self.model.half().cuda(0)
        self.model.eval()
    def rerank(self, query, docs, top_k=3):
        if not docs:
            return []
        pairs = [[query, doc.page_content] for doc in docs]
        with torch.no_grad():
            inputs = self.tokenizer(
                pairs,
                padding=True,
                truncation=True,
                return_tensors='pt',
                max_length=512
            )
            inputs = {k: v.cuda(0) for k, v in inputs.items()}
            scores = self.model(**inputs, return_dict=True).logits.view(-1,).float()

        scored = list(zip(docs, scores.cpu().tolist()))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in scored[:top_k]]

_reranker = None

def get_reranker():
    global _reranker
    if _reranker is None:
        model_path = "/datadisk/home/lsr/.cache/huggingface/hub/models--BAAI--bge-reranker-base/snapshots/2cfc18c9415c912f9d8155881c133215df768a70"
        if os.path.exists(model_path):
            try:
                _reranker = BGEReranker(model_path)
                logger.info("BGE Reranker 加载成功")
            except Exception as e:
                logger.warning("Reranker 加载失败: %s", str(e))
    return _reranker
