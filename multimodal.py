import logging
import io
import numpy as np
from PIL import Image
from typing import Optional

logger = logging.getLogger(__name__)

class MultimodalProcessor:
    def __init__(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr = RapidOCR()
            logger.info("本地 RapidOCR (ONNX) 加载成功")
        except Exception as e:
            self.ocr = None
            logger.error("OCR 引擎初始化失败: %s", str(e))

    def process_image(self, image_data: bytes, question: str = "") -> str:
        if not self.ocr:
            return "系统 OCR 引擎未就绪"

        try:
            image = Image.open(io.BytesIO(image_data)).convert('RGB')
            img_array = np.array(image)

            result, elapse = self.ocr(img_array)

            if not result:
                return "图片解析完成: 未检测到有效文字内容"

            extracted_text = "\n".join([line[1] for line in result])

            if isinstance(elapse, (list, tuple)):
                total_time = sum(e for e in elapse if isinstance(e, (int, float)))
            else:
                total_time = float(elapse)
            logger.info("图片解析成功, 耗时: %.2fs", total_time)

            return f"图片内容提取如下:\n{extracted_text}"

        except Exception as e:
            logger.error("本地图片解析异常: %s", str(e))
            return "图片处理过程中发生未知错误"

_processor: Optional[MultimodalProcessor] = None

def get_processor() -> MultimodalProcessor:
    global _processor
    if _processor is None:
        _processor = MultimodalProcessor()
    return _processor
