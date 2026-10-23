import { useLayoutEffect, useRef, useState } from 'react';
import { flushSync } from 'react-dom';

type MotionKind = 'stage' | 'topic';
type VisualTransition = { skipTransition: () => void; finished: Promise<void>; ready?: Promise<void>; updateCallbackDone?: Promise<void> };
type MotionDocument = Document & { startViewTransition?: (update: () => void) => VisualTransition };
let active: VisualTransition | undefined;

/** Only presentation waits for a browser snapshot. Requests and controls stay immediate.
 * A superseded callback may still run after skipTransition(), so guard every commit.
 */
export function useMotionValue<T extends string | number>(target: T, kind: MotionKind): T {
  const [value, setValue] = useState(target);
  const current = useRef(target);
  const generation = useRef(0);
  const transition = useRef<VisualTransition | undefined>(undefined);
  const mounted = useRef(true);
  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; ++generation.current; transition.current?.skipTransition(); };
  }, []);
  useLayoutEffect(() => {
    const request = ++generation.current;
    transition.current?.skipTransition();
    if (current.current === target) return;
    const apply = () => {
      if (!mounted.current || request !== generation.current) return;
      current.current = target;
      setValue(target);
    };
    const doc = document as MotionDocument;
    if (typeof doc.startViewTransition !== 'function' || document.visibilityState === 'hidden') {
      apply();
      return;
    }
    active?.skipTransition();
    document.documentElement.dataset.motionKind = kind;
    document.documentElement.dataset.motionDirection = typeof target === 'number' && typeof current.current === 'number' && target < current.current ? 'back' : 'forward';
    try {
      const next = doc.startViewTransition(() => flushSync(apply));
      active = transition.current = next;
      void next.ready?.catch(() => {});
      void next.updateCallbackDone?.catch(() => {});
      void next.finished.catch(() => { apply(); }).finally(() => {
        if (active !== next) return;
        active = undefined;
        delete document.documentElement.dataset.motionKind;
        delete document.documentElement.dataset.motionDirection;
      });
    } catch {
      apply();
      if (!active) delete document.documentElement.dataset.motionKind;
    }
  }, [target, kind]);
  return value;
}

export const nativeMotionAvailable = () => typeof (document as MotionDocument).startViewTransition === 'function';
