import { lazy } from 'react';

export const DeferredChatHistory = lazy(() => import('./DeferredChatHistory'));
export const DeferredInlineContentBlocks = lazy(() => import('./DeferredInlineContentBlocks'));

let deferredChatRenderersWarmPromise: Promise<unknown> | null = null;

export function warmDeferredChatRenderers() {
  if (!deferredChatRenderersWarmPromise) {
    deferredChatRenderersWarmPromise = Promise.all([
      import('./DeferredChatHistory'),
      import('./DeferredInlineContentBlocks'),
    ]).catch((error) => {
      deferredChatRenderersWarmPromise = null;
      throw error;
    });
  }

  return deferredChatRenderersWarmPromise;
}
