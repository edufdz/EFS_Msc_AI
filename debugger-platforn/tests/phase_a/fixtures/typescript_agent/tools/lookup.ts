/** Look up an order by its ID - read only */
export async function lookupOrder(orderId: string): Promise<OrderInfo> {
    const result = await fetch(`/api/orders/${orderId}`);
    return result.json();
}

interface OrderInfo {
    id: string;
    status: string;
    total: number;
}
