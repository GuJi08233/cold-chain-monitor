import { api, unwrap } from "./http";
import type { ApiResponse } from "../types/api";

type WsScope = "notifications" | "monitor";

interface WsTicketResponse {
  ticket: string;
  expires_in: number;
  scope: WsScope;
}

export async function issueWsTicket(scope: WsScope, orderId?: string): Promise<string> {
  const payload =
    scope === "monitor"
      ? { scope, order_id: orderId }
      : { scope };
  const data = await unwrap(
    api.post<ApiResponse<WsTicketResponse>>("/auth/ws-ticket", payload),
  );
  return data.ticket;
}

