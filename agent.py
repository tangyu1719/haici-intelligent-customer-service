import logging
import asyncio
from dataclasses import dataclass
from typing import Optional, List
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langchain_core.tools import StructuredTool
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.session import ClientSession
from langchain_mcp_adapters.tools import load_mcp_tools
from memory import get_memory

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是专业的电商智能客服助手。
核心原则：
1. 必须根据用户的输入调用相关工具，绝不允许捏造订单号或库存数据。
2. 如果缺少调用工具的必要参数，必须主动向用户反问索取。
3. 结合上下文历史记录理解用户的指代意图。
4. 使用中文回答，保持简洁直接。"""

@dataclass
class AgentResult:
    answer: str
    intent: str = "agent"

def _load_tool_schemas() -> list:
    """启动时通过 MCP 协议加载工具的 JSON schema 描述"""
    import concurrent.futures

    async def _async_load():
        server_params = StdioServerParameters(command="python", args=["mcp_server.py"])
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await load_mcp_tools(session)
                schemas = []
                for t in tools:
                    schemas.append({
                        "name": t.name,
                        "description": t.description,
                        "args_schema": t.args_schema,
                    })
                return schemas

    def _run():
        return asyncio.run(_async_load())

    with concurrent.futures.ThreadPoolExecutor() as pool:
        future = pool.submit(_run)
        return future.result(timeout=30)

def _build_tools(schemas: list) -> list:
    """用 MCP 获取的 schema + 本地函数构建 LangChain 工具"""
    from mcp_server import query_order, cancel_order, query_logistics, check_stock, compare_products, search_knowledge

    func_map = {
        "query_order": query_order,
        "cancel_order": cancel_order,
        "query_logistics": query_logistics,
        "check_stock": check_stock,
        "compare_products": compare_products,
        "search_knowledge": search_knowledge,
    }

    tools = []
    for schema in schemas:
        name = schema["name"]
        func = func_map.get(name)
        if func:
            tools.append(StructuredTool.from_function(
                func=func,
                name=name,
                description=schema["description"],
            ))
            logger.info("MCP 工具注册: %s", name)
        else:
            logger.warning("MCP 工具 %s 无本地实现，跳过", name)

    return tools

class CustomerServiceAgent:
    def __init__(self):
        self._llm = ChatOpenAI(
            model="qwen2.5-72b-awq",
            api_key="EMPTY",
            base_url="http://localhost:8900/v1",
            temperature=0.0
        )
        # 启动时通过 MCP 加载工具 schema，然后绑定本地函数
        logger.info("通过 MCP 协议加载工具描述...")
        schemas = _load_tool_schemas()
        logger.info("MCP 返回 %d 个工具描述", len(schemas))
        self._tools = _build_tools(schemas)
        self._tool_map = {t.name: t for t in self._tools}
        self._llm_with_tools = self._llm.bind_tools(self._tools)
        logger.info("Agent 初始化完成，共 %d 个工具", len(self._tools))

    def run(self, query: str, session_id: str = "default", context: str = "") -> AgentResult:
        try:
            messages = [SystemMessage(content=SYSTEM_PROMPT)]
            records = get_memory().get_history(session_id)
            for rec in records:
                if rec["role"] == "user":
                    messages.append(HumanMessage(content=rec["content"]))
                elif rec["role"] == "assistant":
                    messages.append(AIMessage(content=rec["content"]))

            input_content = f"{context}\n用户问题: {query}" if context else query
            messages.append(HumanMessage(content=input_content))

            final_answer = ""
            for _ in range(5):
                resp = self._llm_with_tools.invoke(messages)
                messages.append(resp)

                if not resp.tool_calls:
                    final_answer = resp.content
                    break

                for tc in resp.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    logger.info("Agent执行工具调用: %s(%s)", tool_name, tool_args)

                    tool_instance = self._tool_map.get(tool_name)
                    if tool_instance:
                        try:
                            result = tool_instance.invoke(tool_args)
                        except Exception as e:
                            result = f"工具执行异常: {str(e)}"
                    else:
                        result = f"未找到工具: {tool_name}"

                    messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

            clean_answer = final_answer.replace("```json", "").replace("```", "").replace("**", "").strip()
            return AgentResult(answer=clean_answer if clean_answer else "抱歉，暂时无法回答您的请求。")
        except Exception as e:
            logger.error("Agent执行异常: %s", str(e))
            return AgentResult(answer="系统繁忙，请稍后重试。")

_agent: Optional[CustomerServiceAgent] = None

def get_agent() -> CustomerServiceAgent:
    global _agent
    if not _agent:
        _agent = CustomerServiceAgent()
    return _agent
