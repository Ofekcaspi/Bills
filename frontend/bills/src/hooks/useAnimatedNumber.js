// Smoothly counts a number up/down to a new value instead of 
// jumping straight to it (e.g. a total that just changed).
import { useEffect, useRef, useState } from "react";

export function useAnimatedNumber(target, { duration = 700, decimals = 0 } = {}) {
    const safeTarget = Number.isFinite(target) ? target : 0;
    const [value, setValue] = useState(safeTarget);
    const previousTarget = useRef(safeTarget);

    useEffect(() => {
        const from = Number.isFinite(previousTarget.current) ? previousTarget.current : 0;
        const to = safeTarget;
        previousTarget.current = to;

        // Barely changed — just snap to it instead of animating.
        if (Math.abs(to - from) < 0.001) {
            const rafId = window.requestAnimationFrame(() => setValue(to));
            return () => window.cancelAnimationFrame(rafId);
        }

        let rafId = 0;
        let startTs = 0;

        const tick = (ts) => {
            if (!startTs) startTs = ts;
            const elapsed = ts - startTs;
            const progress = Math.min(elapsed / duration, 1);
            // Slows down near the end instead of stopping abruptly.
            const eased = 1 - (1 - progress) * (1 - progress);
            const nextValue = from + (to - from) * eased;
            setValue(nextValue);
            if (progress < 1) {
                rafId = window.requestAnimationFrame(tick);
            }
        };

        rafId = window.requestAnimationFrame(tick);
        return () => window.cancelAnimationFrame(rafId);
    }, [safeTarget, duration]);

    if (decimals > 0) return Number(value.toFixed(decimals));
    return Math.round(value);
}
