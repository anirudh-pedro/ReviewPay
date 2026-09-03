/** Typed calls for the separately labelled Razorpay Sandbox gateway route. */

import { API_PREFIX, apiPost } from './client';
import { isRazorpayOrderResponse, isRazorpayVerificationResponse } from './validators';
import type { RazorpayOrderResponse, RazorpayVerificationResponse } from '@/types/api';

const PREFIX = API_PREFIX;

export interface CreateRazorpayOrderRequest {
  amount: number;
  currency: 'INR';
  customer_id?: string;
  merchant_id?: string;
}

export interface VerifyRazorpayCheckoutRequest {
  razorpay_order_id: string;
  razorpay_payment_id: string;
  razorpay_signature: string;
}

export function createRazorpayOrder(
  request: CreateRazorpayOrderRequest,
  idempotencyKey: string,
): Promise<RazorpayOrderResponse> {
  return apiPost<RazorpayOrderResponse>(
    `${PREFIX}/gateway/razorpay/orders`,
    request,
    undefined,
    isRazorpayOrderResponse,
    { 'Idempotency-Key': idempotencyKey },
  );
}

export function verifyRazorpayCheckout(
  request: VerifyRazorpayCheckoutRequest,
): Promise<RazorpayVerificationResponse> {
  return apiPost<RazorpayVerificationResponse>(
    `${PREFIX}/gateway/razorpay/verify`,
    request,
    undefined,
    isRazorpayVerificationResponse,
  );
}

export function simulateGatewayOrderFailure(
  orderId: string,
  request: import('@/types/api').GatewayFailureSimulationRequest,
): Promise<import('@/types/api').GatewayFailureSimulationResponse> {
  return apiPost<import('@/types/api').GatewayFailureSimulationResponse>(
    `${PREFIX}/gateway/razorpay/orders/${orderId}/simulate-failure`,
    request,
  );
}

