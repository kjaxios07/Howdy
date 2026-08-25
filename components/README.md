# React components — staged, not running

**Read this first: Howdy is not a React project.** There is no Tailwind, no
TypeScript, no shadcn, and no build step of any kind. The front end is three
hand-written HTML files served by Caddy:

```
web/index.html    the site
web/auth.html     sign in
web/chat.html     the chat screen
```

Everything in `components/ui/` is a **staged translation** of a page that
already works in that plain stack. Nothing here is imported, compiled or
served. It exists so that if the front end ever moves to React, the work
starts from something rather than nothing.

Adding these files did not make this a React project, and pasting a `.tsx`
file into a repo that cannot compile it produces a file nobody runs — which
is worse than not having it, because it looks finished.

## What is here

| File | The page it mirrors |
|---|---|
| `sign-in-page.tsx` | `web/auth.html` |
| `glow-horizon.tsx` | the rising horizon on that page |
| `border-beam.tsx` | the beam on the site's cards |
| `kip-beam-demo.tsx` | usage example for the beam |

## If you do want to set React up

The current front end is fast, has no build step, and nothing to break in CI.
Moving is a real decision, not a formality — it makes sense when a designer
joins or the UI outgrows hand-written HTML, and not much before. The roadmap
has it under **Phase 4 · later** for that reason.

If you go ahead:

```bash
# 1. A Vite + React + TypeScript app, alongside the current web/ directory
npm create vite@latest app -- --template react-ts
cd app && npm install

# 2. Tailwind
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p

# 3. shadcn — this is what creates components/ui and wires the @/ alias
npx shadcn@latest init

# 4. What the staged components import
npm install lucide-react
```

**Why `components/ui` specifically.** `shadcn init` writes that path into
`components.json`, and every `shadcn add` drops its output there. The `@/`
alias in `tsconfig.json` and `vite.config.ts` resolves against it. Put a
component somewhere else and the generated imports (`@/components/ui/button`)
break, and the next `shadcn add` will not find what is already there — you
end up with two copies of the same primitive drifting apart.

## Three things that changed in translation, and why

The pasted originals were adapted rather than copied. Each departure is a
decision worth keeping if these are ever revived.

**No password field, no GitHub button.** The server is Google OIDC and there
are no passwords in the system at all (`server/app/routers/auth.py`). A
password form would be a form that cannot submit, and GitHub is a door almost
no international student has a key to. One honest option beats three when two
of them lie.

**No remote images.** The deployed CSP is `img-src 'self' data:`, so an image
from an external host silently fails to load and leaves half a blank screen
with nothing in the console to explain it. The artwork is inline SVG, which
also follows the theme and raises no question about whose photograph it is.

**No `framer-motion`, and no animated blur.** The original horizon animated
`filter: blur()` across four stacked full-screen layers. Blur is not
compositor-animatable, so every frame is a fresh rasterisation — on a
mid-range Android phone that is the difference between a sign-in page and a
slideshow. It is the same problem that made the chat prototype feel heavy
earlier in this project, and it has the same fix: animate transform and
opacity, keep blur constant. Eight lines of CSS, no dependency.

## Before reviving any of this

Check it against the live page first. `web/auth.html` is the source of truth
and has moved on since these were written — the honest thing is to translate
the current page, not to trust a snapshot.
