# React components

**This repository is not a React project.** The site is hand-written HTML +
CSS + vanilla JS in `web/`, and the backend is Python (FastAPI) in `server/`.
There is no `package.json` app, no TypeScript, no Tailwind and no shadcn.

The files in `ui/` are staged for a future migration. They will not compile or
run until the setup below is done. Nothing on the live site imports them — the
same beam effect is implemented in plain CSS in `web/index.html`, so the
current site has the visual without the dependency.

## Why `components/ui/`

shadcn/ui resolves generated components to `components/ui` by default and its
CLI writes there. Keeping the path means `npx shadcn@latest add <component>`
drops files exactly where imports already point, and every `@/components/ui/x`
import from the docs or the registry works unchanged. Renaming it means editing
`components.json` aliases and every generated import forever after.

## Setting the project up

Only do this if we decide to move the front end to React (see the roadmap —
it is deliberately **not** on the critical path).

```bash
# 1. A React + TypeScript app
npm create vite@latest web-next -- --template react-ts
cd web-next && npm install

# 2. Tailwind
npm install -D tailwindcss @tailwindcss/postcss postcss
# then add "@import 'tailwindcss';" to your CSS entry

# 3. Path alias so @/ resolves — tsconfig.json
#   "baseUrl": ".", "paths": { "@/*": ["./src/*"] }
#   and the matching resolve.alias in vite.config.ts

# 4. shadcn
npx shadcn@latest init      # writes components.json, sets components/ui

# 5. This component's dependencies
npm install border-beam lucide-react
```

`border-beam` is a real package (v1.3.0, peer deps react >= 18 / react-dom >= 18).
It renders its own animated border, so it needs no Tailwind plugin or keyframes
of its own.

## Props

| Prop | Values | Notes |
|---|---|---|
| `size` | `BorderBeamSize` | `"md"` in our usage |
| `colorVariant` | `BorderBeamColorVariant` | `"colorful"` in our usage |
| `theme` | `BorderBeamTheme` | left default |

It is a wrapper: pass the card as `children` and it draws the beam around it.
No state, no context, no provider. Responsive behaviour comes from the child —
ours is `w-[348px] max-w-full`, so it shrinks on a phone.

## Where to use it

Around the ask box, and nowhere else. It is an attention device; a second one
on the same screen cancels the first out.
