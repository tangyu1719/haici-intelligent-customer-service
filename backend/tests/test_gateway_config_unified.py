"""测试网关单一配置源与热重载。"""

import json
import os
import sys
from pathlib import Path

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

_PYTEST_TMP = Path(_backend_dir) / ".pytest_tmp" / "gateway_unified"
_PYTEST_TMP.mkdir(parents=True, exist_ok=True)


class TestGatewayConfigUnified:
    def test_load_prefers_local_over_env_path(self, monkeypatch):
        local = _PYTEST_TMP / "local_agent_gateway_config.json"
        parent = _PYTEST_TMP / "parent_config.json"
        parent.write_text(
            json.dumps(
                {
                    "api_gateway_nodes": [
                        {
                            "id": "parent_node",
                            "provider": "ark",
                            "api_key": "parent-key",
                            "base_url": "http://parent",
                            "model": "ep-parent",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        local.write_text(
            json.dumps(
                {
                    "api_gateway_nodes": [
                        {
                            "id": "local_node",
                            "provider": "ark",
                            "api_key": "local-key",
                            "base_url": "http://local",
                            "model": "ep-local",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "app.services.gateway_config_store.LOCAL_GATEWAY_CONFIG",
            local,
        )
        monkeypatch.setenv("LLM_GATEWAY_CONFIG", str(parent))

        from app.services.gateway_config_store import load_raw_gateway_config

        raw = load_raw_gateway_config()
        nodes = raw.get("api_gateway_nodes") or []
        assert nodes[0]["id"] == "local_node"

    def test_save_triggers_llm_gateway_reload(self, monkeypatch):
        cfg = _PYTEST_TMP / "reload_gw.json"
        cfg.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            "app.services.gateway_config_store.LOCAL_GATEWAY_CONFIG",
            cfg,
        )

        import app.services.llm_gateway as lg

        lg._gateway = None
        lg.get_llm_gateway()

        from app.services.gateway_config_store import save_raw_gateway_config

        save_raw_gateway_config(
            {
                "gateway_route_mode": "task_type",
                "api_gateway_nodes": [
                    {
                        "id": "reload_test",
                        "provider": "ark",
                        "api_key": "k-test",
                        "base_url": "http://t",
                        "model": "ep-test",
                        "priority": 1,
                        "status": "active",
                    }
                ],
            }
        )
        after = lg.get_llm_gateway().nodes
        assert "reload_test" in after
        assert after["reload_test"].api_key == "k-test"

    def test_agent_gateway_public_dict_masks_key(self):
        from app.services.agent_gateway import GatewayNode

        node = GatewayNode(
            id="n1",
            api_key="abcdefghijklmnop",
            base_url="http://x",
            model="m",
        )
        pub = node.to_public_dict()
        assert "abcdefghijklmnop" not in pub["api_key"]
        assert pub["api_key_hint"].startswith("abcd")

    def test_example_file_exists_and_has_no_real_key(self):
        from app.services.gateway_config_store import LOCAL_GATEWAY_EXAMPLE

        assert LOCAL_GATEWAY_EXAMPLE.is_file()
        raw = json.loads(LOCAL_GATEWAY_EXAMPLE.read_text(encoding="utf-8"))
        for node in raw.get("api_gateway_nodes") or []:
            key = str(node.get("api_key") or "")
            assert "your-" in key or key == "" or key.startswith("ep-")
