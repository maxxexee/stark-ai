import { type QueryClient, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { queryKeys } from "./queries";
import type {
  ApprovedPayment,
  BankAccount,
  BillPatch,
  CryptoWithdrawInput,
  LimitsPatch,
  LinkedChat,
  NewBill,
  PaymentInput,
  PaymentRequest,
  StartDeposit,
  TopUpInput,
  WithdrawInput,
} from "./types";

export function invalidateMoney(qc: QueryClient) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: queryKeys.state }),
    qc.invalidateQueries({ queryKey: queryKeys.bills }),
    qc.invalidateQueries({ queryKey: queryKeys.activity }),
    qc.invalidateQueries({ queryKey: queryKeys.payees }),
    qc.invalidateQueries({ queryKey: queryKeys.wallet }),
    qc.invalidateQueries({ queryKey: queryKeys.limits }),
    qc.invalidateQueries({ queryKey: queryKeys.suggestions }),
  ]);
}

export function usePayBill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: PaymentInput) => api.pay(input),
    onSettled: () => invalidateMoney(qc),
  });
}

export function useAddBill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: NewBill) => api.addBill(input),
    onSuccess: () => invalidateMoney(qc),
  });
}

export function useUpdateBill(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: BillPatch) => api.updateBill(id, patch),
    onSuccess: (bill) => {
      qc.setQueryData(queryKeys.bill(id), bill);
      return invalidateMoney(qc);
    },
  });
}

export function useConfirmBill(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.confirmBill(id),
    onSuccess: (bill) => {
      qc.setQueryData(queryKeys.bill(id), bill);
      return invalidateMoney(qc);
    },
  });
}

export function useDeleteBill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteBill(id),
    onSuccess: () => invalidateMoney(qc),
  });
}

export function useUpdateLimits() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: LimitsPatch) => api.updateLimits(patch),
    onSuccess: (limits) => {
      qc.setQueryData(queryKeys.limits, limits);
      return invalidateMoney(qc);
    },
  });
}

export function useTopUp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: TopUpInput) => api.topUp(input),
    onSuccess: () => invalidateMoney(qc),
  });
}

/** Nothing moves yet: the balance changes when the deposit reads `credited`. */
export function useStartDeposit() {
  return useMutation({ mutationFn: (input: StartDeposit) => api.startDeposit(input) });
}

export function useResolveBankAccount() {
  return useMutation({ mutationFn: (input: BankAccount) => api.resolveBankAccount(input) });
}

export function useWithdraw() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: WithdrawInput) => api.withdraw(input),
    onSuccess: () => invalidateMoney(qc),
  });
}

export function useWithdrawCrypto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CryptoWithdrawInput) => api.withdrawCrypto(input),
    onSuccess: () => invalidateMoney(qc),
  });
}

export function useVoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (transcript: string) => api.voice(transcript, { speak: false }),
    onSuccess: (reply) => {
      if (reply.receipt_id) return invalidateMoney(qc);
    },
  });
}

/** Same contract as useVoice, but the clip goes up and the server does the
 *  hearing — for browsers without the Web Speech API. */
export function useVoiceAudio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (audio: Blob) => api.voiceAudio(audio, { speak: false }),
    onSuccess: (reply) => {
      if (reply.receipt_id) return invalidateMoney(qc);
    },
  });
}

/**
 * Mint a link code on demand. Deliberately not a query: each call creates a
 * new code, and a cached one would be a code the user cannot see.
 */
export function useLinkCode() {
  return useMutation({
    mutationFn: () => api.linkCode(),
  });
}

/** The chat can no longer see or move money from its next message on. */
export function useUnlinkChat() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (chat: LinkedChat) => api.unlinkChat(chat),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.linkedChats }),
  });
}

/** An approval pays, so it moves money; a denial adds a declined row to activity. */
export function useDecideRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      approve,
    }: {
      id: string;
      approve: boolean;
    }): Promise<ApprovedPayment | PaymentRequest> => (approve ? api.approve(id) : api.deny(id)),
    onSettled: () =>
      Promise.all([qc.invalidateQueries({ queryKey: queryKeys.approvals }), invalidateMoney(qc)]),
  });
}

export function useSetPaused() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (paused: boolean) => (paused ? api.pause() : api.resume()),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.state }),
  });
}

export function useResetDemo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resetDemo(),
    onSuccess: () => qc.invalidateQueries(),
  });
}
