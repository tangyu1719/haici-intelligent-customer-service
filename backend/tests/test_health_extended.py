"""健康检查扩展。"""

import os
import sys

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)


def test_health_endpoint_shape():
    from app.main import health

    data = health()
    assert "status" in data
    assert "items" in data
    assert isinstance(data["items"], list)
    ids = {it.get("id") for it in data["items"]}
    assert "mysql" in ids
    assert "chroma" in ids
    assert "embedding" in ids
