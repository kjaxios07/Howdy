# Hero media

Drop these here and the hero uses them automatically:

    hero.webm   the looping background clip (Chrome, Firefox)
    hero.mp4    the same clip for Safari

Neither is required, and either one alone works. If they're missing, the hero falls back to the canvas
Southern Cross — that is the designed floor, not a broken state, so the site
is never waiting on a video to look finished.

Get them with:

    ./scripts/add-hero-video.sh "<url of the clip>"

That downloads, trims to a seamless-ish loop, strips audio, sizes it for the
web ffmpeg is required; the script tells
you if it isn't installed.

There is deliberately no poster frame. The canvas starfield sits behind the
video and is a better placeholder than a still image, so a poster would only
be a second request covering something already covered.

## Why local and not a CDN link

The site's Content-Security-Policy is `default-src 'self'`. `media-src` has no
value of its own so it inherits that, which means a video served from another
host is blocked and silently shows nothing. Serving it from `web/` is same
origin, so it just works — and it is one less third party watching students
arrive on the page.

## Budget

Keep hero.mp4 under about 3 MB. It is decoration behind text, and a lot of the
audience is on mobile data in their first week in the country. The script
targets that. The page also skips the video entirely on narrow screens, on
save-data connections and under prefers-reduced-motion.

## Before the files are added

The page requests the clip once, gets a 404, and keeps the starfield. That
single handled console error is expected until you run the script — it is not
a bug, and nothing about the hero looks unfinished because of it.
