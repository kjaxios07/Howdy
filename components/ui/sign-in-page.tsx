'use client'

/**
 * Kip sign-in, as a React component.
 *
 * STAGED, NOT RUNNING. This repo is plain HTML and FastAPI — no React, no
 * Tailwind, no shadcn. The page that actually serves is `web/auth.html`, and
 * this file exists so the migration has somewhere to start. See
 * components/README.md for what setting React up would involve.
 *
 * Three deliberate departures from the component this was adapted from:
 *
 * 1. **Google only — no email, no password, no GitHub.** The server is Google
 *    OIDC and there are no passwords in the system (`server/app/routers/
 *    auth.py`). A password field would be a form that cannot submit, and a
 *    GitHub button on a product for international students is a door almost
 *    nobody here has a key to. One honest option beats three, two of which lie.
 *
 * 2. **The artwork is drawn, not fetched.** The original pointed at an image
 *    host; the deployed CSP is `img-src 'self' data:`, so a remote image
 *    silently fails to load and you get a blank half-screen with no error.
 *    Inline SVG also follows the theme and raises no licensing question.
 *
 * 3. **Guest mode is on the page.** Someone frightened enough to be reading
 *    this at 2am should not have to hand over an identity first. The route to
 *    asking without an account is the third thing they see.
 */

import { ArrowLeft, Check } from 'lucide-react'

const GOOGLE_START = '/api/auth/google'

function SouthernCrossScene() {
  return (
    <svg
      viewBox="0 0 800 1000"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      className="absolute inset-0 h-full w-full"
    >
      <defs>
        <linearGradient id="kip-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#070B12" />
          <stop offset="58%" stopColor="#131B2E" />
          <stop offset="100%" stopColor="#2A2140" />
        </linearGradient>
      </defs>
      <rect width="800" height="1000" fill="url(#kip-sky)" />

      {/* The Southern Cross — the one thing in this sky that is not in the
          sky they left. */}
      <g fill="#EAF1F7" opacity="0.9">
        <circle cx="486" cy="188" r="4.2" />
        <circle cx="452" cy="286" r="5.4" />
        <circle cx="536" cy="300" r="3.4" />
        <circle cx="474" cy="368" r="6" />
        <circle cx="500" cy="252" r="2.4" />
      </g>
      <g fill="#EAF1F7" opacity="0.28">
        <circle cx="140" cy="120" r="1.8" />
        <circle cx="640" cy="150" r="2" />
        <circle cx="92" cy="330" r="1.4" />
        <circle cx="330" cy="96" r="1.7" />
        <circle cx="712" cy="330" r="1.6" />
      </g>

      {/* A ridge, and gums on it. */}
      <path
        d="M0 720 Q140 664 268 700 T520 686 Q652 660 800 706 L800 1000 L0 1000 Z"
        fill="#0A0F17"
      />
      <g fill="#0A0F17" stroke="#0A0F17" strokeLinecap="round">
        <path d="M124 722 L131 600" strokeWidth="9" fill="none" />
        <path d="M131 622 L104 592 M131 640 L158 606" strokeWidth="5" fill="none" />
        <ellipse cx="128" cy="566" rx="52" ry="31" />
        <path d="M652 708 L644 546" strokeWidth="11" fill="none" />
        <path d="M646 578 L610 542 M646 600 L686 560" strokeWidth="6" fill="none" />
        <ellipse cx="648" cy="510" rx="62" ry="36" />
        <path d="M386 694 L390 632" strokeWidth="6" fill="none" />
        <ellipse cx="389" cy="618" rx="32" ry="19" />
      </g>
    </svg>
  )
}

const PERKS = [
  'Your chats saved, and readable only by you',
  'Answers for your city, not a generic one',
  'Delete the lot whenever you want',
]

export function SignInPage() {
  return (
    <div className="grid min-h-dvh grid-cols-1 bg-[#070B12] md:grid-cols-[1.05fr_1fr]">
      {/* The country */}
      <section className="relative flex min-h-[270px] flex-col justify-end overflow-hidden p-7 md:p-11">
        <SouthernCrossScene />

        {/* First light on the ridge. Transform and opacity only. */}
        <div
          aria-hidden
          className="pointer-events-none absolute -bottom-[42%] left-1/2 aspect-[2/1] w-[150%] -translate-x-1/2 rounded-[50%] opacity-[0.78] blur-[38px] motion-safe:animate-[kip-rise_2.4s_cubic-bezier(.16,1,.3,1)_both]"
          style={{ background: 'radial-gradient(closest-side,#8B7BFF,transparent 70%)' }}
        />

        <a
          href="/"
          className="absolute left-6 top-6 z-10 inline-flex items-center gap-2 rounded-full border border-white/20 bg-black/40 px-4 py-2 text-sm font-semibold text-slate-50 backdrop-blur-md hover:bg-black/60"
        >
          <ArrowLeft className="h-4 w-4 shrink-0" />
          Back
        </a>

        <div className="relative z-10 max-w-[30ch]">
          <h2 className="text-balance text-2xl font-bold leading-tight tracking-tight text-slate-50 drop-shadow-lg md:text-3xl">
            Somewhere new, and a lot to work out.
          </h2>
          <p className="mt-2.5 text-slate-200/80 drop-shadow">
            Kip is here for the bits nobody explains.
          </p>
        </div>
      </section>

      {/* The one thing to do */}
      <section className="flex items-center justify-center bg-[#070B12] px-8 py-11">
        <div className="w-full max-w-[400px]">
          <h1 className="text-3xl font-extrabold tracking-tight text-[#EAF1F7]">
            Good to see you.
          </h1>
          <p className="mt-2 text-[#93A5B5]">
            Sign in and Kip remembers what you asked, so you don&apos;t start over
            every time.
          </p>

          {/* A link, not a button with an onSubmit — the OAuth dance starts on
              the server, and there is no client-side credential to collect. */}
          <a
            href={GOOGLE_START}
            className="mt-7 flex w-full items-center justify-center gap-3 rounded-2xl border border-white/15 bg-[#0D131D] px-5 py-4 font-bold text-[#EAF1F7] transition hover:border-[#2FD3AE]"
          >
            <svg className="h-5 w-5 shrink-0" viewBox="0 0 24 24" aria-hidden="true">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
            </svg>
            Continue with Google
          </a>

          <div className="mt-7 border-t border-white/10 pt-6">
            <h3 className="mb-3 text-xs font-extrabold uppercase tracking-widest text-[#5B6E7E]">
              What you get
            </h3>
            <ul className="flex flex-col gap-2.5">
              {PERKS.map((p) => (
                <li key={p} className="flex gap-2.5 text-sm text-[#93A5B5]">
                  <Check className="mt-0.5 h-4 w-4 shrink-0 text-[#2FD3AE]" />
                  {p}
                </li>
              ))}
            </ul>
          </div>

          <p className="mt-7 rounded-xl border border-white/10 bg-white/[0.045] px-4 py-4 text-sm leading-relaxed text-[#93A5B5]">
            Don&apos;t want an account?{' '}
            <a href="/chat" className="font-bold text-[#2FD3AE]">
              Just ask Kip
            </a>{' '}
            — nothing is written down, and you can sign in later if you change
            your mind.
          </p>

          <p className="mt-6 text-xs leading-relaxed text-[#5B6E7E]">
            Every answer comes from a verified source. Guidance, never legal
            advice. We only ever see your name and email from Google.
          </p>
        </div>
      </section>
    </div>
  )
}

export default SignInPage
