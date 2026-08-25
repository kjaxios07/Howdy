'use client'

/**
 * First light on the horizon — an arc that rises once and settles.
 *
 * STAGED, NOT RUNNING. This repo is plain HTML and FastAPI. The effect is
 * live on `web/auth.html` as about eight lines of CSS; this is the React
 * version for whenever the front end moves.
 *
 * Two changes from the component this was adapted from:
 *
 * 1. **No framer-motion.** The original animated `filter: blur()` on four
 *    stacked layers for two seconds. Blur is not compositor-animatable, so
 *    every frame is a fresh rasterisation of a full-screen element — on a
 *    mid-range Android that is the difference between a sign-in page and a
 *    slideshow. That exact class of problem is what made the chat prototype
 *    feel heavy earlier in this project, and the fix was the same: animate
 *    transform and opacity, and let blur be a constant. It also removes a
 *    dependency from a page whose entire job is one button press.
 *
 * 2. **Colours come from CSS variables.** The original hard-coded purples.
 *    Kip has four themes and the horizon has to be dawn in one and dusk in
 *    another, so the palette is `--glow`, set by whichever theme is active.
 *
 * Honours `prefers-reduced-motion`: the arc simply starts where it ends.
 */

export type GlowHorizonVariant = 'top' | 'bottom' | 'left' | 'right'

const PLACEMENT: Record<GlowHorizonVariant, string> = {
  bottom: 'left-1/2 -bottom-[42%] w-[150%] aspect-[2/1] -translate-x-1/2',
  top: 'left-1/2 -top-[42%] w-[150%] aspect-[2/1] -translate-x-1/2',
  left: 'top-1/2 -left-[42%] h-[150%] aspect-[1/2] -translate-y-1/2',
  right: 'top-1/2 -right-[42%] h-[150%] aspect-[1/2] -translate-y-1/2',
}

export interface GlowHorizonProps {
  /** Which edge the light rises from. Defaults to the horizon: bottom. */
  variant?: GlowHorizonVariant
  /** Any CSS colour, or a custom property. Defaults to the active theme's. */
  color?: string
  className?: string
}

export function GlowHorizon({
  variant = 'bottom',
  color = 'var(--glow, #8B7BFF)',
  className = '',
}: GlowHorizonProps) {
  return (
    <div
      aria-hidden
      className={
        'pointer-events-none absolute rounded-[50%] opacity-[0.78] blur-[38px] ' +
        'motion-safe:animate-[kip-rise_2.4s_cubic-bezier(.16,1,.3,1)_both] ' +
        PLACEMENT[variant] +
        ' ' +
        className
      }
      style={{ background: `radial-gradient(closest-side, ${color}, transparent 70%)` }}
    />
  )
}

export default GlowHorizon

/**
 * Add to your Tailwind config — transform and opacity only, no blur:
 *
 *   theme: { extend: { keyframes: { 'kip-rise': {
 *     from: { transform: 'translateY(26%) scaleY(1.5)', opacity: '0' },
 *     to:   { transform: 'none', opacity: '0.78' },
 *   } } } }
 */
