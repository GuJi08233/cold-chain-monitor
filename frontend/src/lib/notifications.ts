export const NOTIFICATION_SYNC_EVENT = "notifications:sync-unread";

export function dispatchUnreadSync(count: number): void {
  window.dispatchEvent(
    new CustomEvent<{ count: number }>(NOTIFICATION_SYNC_EVENT, {
      detail: { count: Math.max(0, Math.floor(count)) },
    }),
  );
}
