import logging
import pymysql
from mcp.server.fastmcp import FastMCP
from config import settings

logger = logging.getLogger(__name__)

mcp = FastMCP("Zhiwei-Ecommerce-Skills")

STATUS_MAP = {"shipped": "已发货", "pending": "待发货", "delivered": "已签收", "in_transit": "运输中"}

def get_db():
    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

@mcp.tool()
def query_order(order_id: str) -> str:
    """查询订单状态、金额和商品详情。必须提供 order_id 参数。"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT o.order_id, o.status, o.total_amount, o.pay_amount, o.address,
                   GROUP_CONCAT(p.name SEPARATOR ', ') as items,
                   MAX(l.tracking_no) as tracking_no, MAX(l.carrier) as carrier
            FROM orders o
            LEFT JOIN order_items oi ON o.order_id = oi.order_id
            LEFT JOIN products p ON oi.product_id = p.product_id
            LEFT JOIN logistics l ON o.order_id = l.order_id
            WHERE o.order_id = %s
            GROUP BY o.order_id, o.status, o.total_amount, o.pay_amount, o.address
        """, (order_id.upper(),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return f"未找到订单 {order_id}"
        status_cn = STATUS_MAP.get(row["status"], row["status"])
        res = f"订单 {order_id}: 状态[{status_cn}], 商品[{row['items']}], 金额{row['total_amount']}元"
        if row.get("tracking_no"):
            res += f", 快递{row['carrier']} {row['tracking_no']}"
        return res
    except Exception as e:
        logger.error("查询订单异常: %s", str(e))
        return f"查询订单 {order_id} 失败"

@mcp.tool()
def cancel_order(order_id: str) -> str:
    """取消订单。必须提供 order_id 参数。"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT status FROM orders WHERE order_id = %s", (order_id.upper(),))
        row = cur.fetchone()
        conn.close()
        if not row:
            return f"订单 {order_id} 不存在"
        if row["status"] == "shipped":
            return f"订单 {order_id} 已发货，无法直接取消，请拒收或申请售后"
        if row["status"] == "delivered":
            return f"订单 {order_id} 已签收，无法取消，请申请退货退款"
        return f"订单 {order_id} 取消成功，退款将于1-3个工作日原路退回"
    except Exception as e:
        return f"取消订单 {order_id} 失败"

@mcp.tool()
def query_logistics(order_id: str) -> str:
    """查询物流轨迹。必须提供 order_id 参数。"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT status FROM orders WHERE order_id = %s", (order_id.upper(),))
        order = cur.fetchone()
        if not order:
            conn.close()
            return f"订单 {order_id} 不存在"
        if order["status"] == "pending":
            conn.close()
            return f"订单 {order_id} 尚未发货，暂无物流信息"
        cur.execute("""
            SELECT l.carrier, l.tracking_no, l.status,
                   GROUP_CONCAT(lt.content ORDER BY lt.trace_time DESC SEPARATOR ' -> ') as trace
            FROM logistics l
            LEFT JOIN logistics_trace lt ON l.order_id = lt.order_id
            WHERE l.order_id = %s
            GROUP BY l.carrier, l.tracking_no, l.status
        """, (order_id.upper(),))
        row = cur.fetchone()
        conn.close()
        if row:
            status_cn = STATUS_MAP.get(row["status"], row["status"])
            return f"订单 {order_id}: {row['carrier']} {row['tracking_no']}, 状态[{status_cn}], 轨迹: {row['trace']}"
        return f"订单 {order_id} 已发货，暂无轨迹更新"
    except Exception as e:
        return f"查询物流 {order_id} 失败"

@mcp.tool()
def check_stock(product_id: str) -> str:
    """查询商品库存价格。必须提供 product_id 参数。"""
    try:
        conn = get_db()
        cur = conn.cursor()
        pid = product_id.strip().upper()
        cur.execute("""
            SELECT p.product_id, p.name, p.price, p.description,
                   COALESCE(SUM(s.stock), 0) as total_stock
            FROM products p
            LEFT JOIN product_skus s ON p.product_id = s.product_id
            WHERE p.product_id = %s OR UPPER(p.name) LIKE %s
            GROUP BY p.product_id
        """, (pid, f"%{pid}%"))
        row = cur.fetchone()
        conn.close()
        if not row:
            return f"未找到商品 {product_id}"
        status = "有货" if row["total_stock"] > 0 else "缺货"
        return f"{row['name']}: 价格{row['price']}元, 库存{row['total_stock']}件({status}), {row['description']}"
    except Exception as e:
        return f"查询商品 {product_id} 失败"

@mcp.tool()
def compare_products(product_ids: str) -> str:
    """对比多个商品的参数、价格和库存。输入多个商品编号，用逗号分隔，如 P001,P003。"""
    try:
        conn = get_db()
        cur = conn.cursor()
        pids = [p.strip().upper() for p in product_ids.split(",") if p.strip()]
        results = []
        for pid in pids:
            cur.execute("""
                SELECT p.product_id, p.name, p.price, p.description,
                       COALESCE(SUM(s.stock), 0) as total_stock
                FROM products p
                LEFT JOIN product_skus s ON p.product_id = s.product_id
                WHERE p.product_id = %s
                GROUP BY p.product_id, p.name, p.price, p.description
            """, (pid,))
            row = cur.fetchone()
            if row:
                status = "有货" if row["total_stock"] > 0 else "缺货"
                results.append(f"- {row['name']}({row['product_id']}): {row['price']}元, 库存{row['total_stock']}件({status}), {row['description']}")
            else:
                results.append(f"- {pid}: 未找到")
        conn.close()
        return "商品对比:\n" + "\n".join(results) if results else "未找到相关商品"
    except Exception as e:
        return f"商品对比查询失败: {str(e)}"

@mcp.tool()
def search_knowledge(query: str) -> str:
    """检索知识库，回答运费、售后、退换货政策、商品参数、产品说明等知识类问题。必须提供 query 参数。"""
    try:
        from rag import rag_query
        result = rag_query(query)
        return result.get("answer", "未找到相关信息")
    except Exception as e:
        logger.error("知识库检索异常: %s", str(e))
        return "知识库检索失败，请稍后重试"

if __name__ == "__main__":
    mcp.run()
