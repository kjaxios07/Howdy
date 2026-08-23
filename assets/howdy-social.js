/* Howdy Jobs — Instagram share pack.
 *
 * Draws a 1080x1080 feed post and a 1080x1920 story / Reel cover for a job,
 * straight on a canvas in the browser, and pairs them with the caption,
 * hashtags and Reel script from /api/social. Download, or hit Share on a
 * phone to hand the image and caption straight to Instagram.
 */
(function () {
  'use strict';

  var H = window.Howdy;
  var SIZES = {
    post: { w: 1080, h: 1080, label: 'Feed post 1:1' },
    story: { w: 1080, h: 1920, label: 'Story / Reel cover 9:16' }
  };

  var state = { data: null, format: 'post', tab: 'image' };

  /* ── canvas drawing ───────────────────────────────────────────────────── */
  function wrap(ctx, text, maxWidth, maxLines) {
    var words = String(text).split(' ');
    var lines = [];
    var line = '';
    for (var i = 0; i < words.length; i++) {
      var next = line ? line + ' ' + words[i] : words[i];
      if (ctx.measureText(next).width > maxWidth && line) {
        lines.push(line);
        line = words[i];
        if (lines.length === maxLines - 1 && i < words.length - 1) break;
      } else {
        line = next;
      }
    }
    lines.push(line);
    return lines.slice(0, maxLines);
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function pill(ctx, text, x, y, opts) {
    var padX = opts.padX || 34;
    var height = opts.height || 76;
    ctx.font = opts.font;
    var w = ctx.measureText(text).width + padX * 2;
    ctx.fillStyle = opts.bg;
    roundRect(ctx, x, y, w, height, height / 2);
    ctx.fill();
    if (opts.border) {
      ctx.strokeStyle = opts.border;
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    ctx.fillStyle = opts.color;
    ctx.textBaseline = 'middle';
    ctx.fillText(text, x + padX, y + height / 2 + 2);
    ctx.textBaseline = 'alphabetic';
    return w;
  }

  function draw(canvas, format) {
    var size = SIZES[format];
    var job = state.data.job;
    var w = size.w;
    var h = size.h;
    canvas.width = w;
    canvas.height = h;
    var ctx = canvas.getContext('2d');
    var tall = format === 'story';
    var pad = 90;
    var maxW = w - pad * 2;
    var F = 'Plus Jakarta Sans, system-ui, -apple-system, Segoe UI, sans-serif';
    var titleSize = tall ? 96 : 88;

    /* background */
    var bg = ctx.createLinearGradient(0, 0, w, h);
    bg.addColorStop(0, '#160E3A');
    bg.addColorStop(0.55, '#2A1A63');
    bg.addColorStop(1, '#0C0722');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, w, h);

    var glow = ctx.createRadialGradient(w * 0.85, h * 0.12, 0, w * 0.85, h * 0.12, w * 0.75);
    glow.addColorStop(0, 'rgba(167,139,250,.30)');
    glow.addColorStop(1, 'rgba(167,139,250,0)');
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, w, h);

    /* Lay the body out as blocks so nothing can overlap: each block knows its
       own height and the gap above it, and the gaps shrink if the copy is long. */
    ctx.font = '800 ' + titleSize + 'px ' + F;
    var titleLines = wrap(ctx, job.title, maxW, tall ? 3 : 2);
    var lineH = Math.round(titleSize * 1.14);

    var blocks = [
      { gap: 0, h: 40, draw: function (y) {
        ctx.font = '800 40px ' + F;
        ctx.fillStyle = 'rgba(255,255,255,.55)';
        ctx.fillText('HOWDY JOBS', pad, y + 34);
      } },
      { gap: 46, h: 70, draw: function (y) {
        pill(ctx, 'NOW HIRING', pad, y, {
          font: '800 34px ' + F, bg: 'rgba(167,139,250,.22)', border: 'rgba(167,139,250,.7)',
          color: '#D6C7FF', height: 70
        });
      } },
      { gap: 40, h: 96, draw: function (y) {
        ctx.font = '96px ' + F;
        ctx.fillText(job.emoji, pad, y + 92);
      } },
      { gap: 46, h: titleLines.length * lineH, draw: function (y) {
        ctx.font = '800 ' + titleSize + 'px ' + F;
        ctx.fillStyle = '#FFFFFF';
        titleLines.forEach(function (line, i) {
          ctx.fillText(line, pad, y + lineH * i + titleSize * 0.82);
        });
      } },
      { gap: 18, h: 56, draw: function (y) {
        ctx.font = '600 52px ' + F;
        ctx.fillStyle = 'rgba(255,255,255,.78)';
        ctx.fillText(wrap(ctx, job.business, maxW, 1)[0], pad, y + 46);
      } },
      { gap: 14, h: 50, draw: function (y) {
        ctx.font = '500 46px ' + F;
        ctx.fillStyle = 'rgba(255,255,255,.62)';
        ctx.fillText('📍 ' + job.location, pad, y + 42);
      } },
      { gap: 34, h: tall ? 104 : 92, draw: function (y) {
        var s = tall ? 104 : 92;
        ctx.font = '800 ' + s + 'px ' + F;
        ctx.fillStyle = '#6EE7B7';
        ctx.fillText(job.pay, pad, y + s * 0.82);
      } },
      { gap: 26, h: 76, draw: function (y) {
        var opts = {
          font: '700 38px ' + F, bg: 'rgba(255,255,255,.10)',
          border: 'rgba(255,255,255,.18)', color: '#FFFFFF'
        };
        var used = pill(ctx, job.employmentType, pad, y, opts);
        if (job.hours) pill(ctx, job.hours, pad + used + 20, y, opts);
      } }
    ];

    if (job.days && job.days.length) {
      blocks.push({ gap: 26, h: 46, draw: function (y) {
        ctx.font = '600 40px ' + F;
        ctx.fillStyle = 'rgba(255,255,255,.55)';
        ctx.fillText(job.days.join('  ·  '), pad, y + 38);
      } });
    }

    /* footer is anchored to the bottom; the body flows above it */
    var footerH = job.verified ? 250 : 176;
    var top = tall ? 250 : pad + 20;
    var available = h - top - footerH - 40;
    var content = blocks.reduce(function (sum, b) { return sum + b.gap + b.h; }, 0);

    // Squeeze the gaps (never the type) when a long title pushes the body down.
    var squeeze = content > available
      ? Math.max(0.35, (available - (content - gapTotal(blocks))) / gapTotal(blocks))
      : 1;

    // A 9:16 story has room to spare — centre the stack instead of stranding it
    // at the top of the frame.
    var y = top;
    if (tall && content < available) y += Math.min((available - content) / 2, 260);
    blocks.forEach(function (b) {
      y += b.gap * squeeze;
      b.draw(y);
      y += b.h;
    });

    var footY = h - footerH + 40;
    if (job.verified) {
      pill(ctx, '✓ Verified employer', pad, footY - 92, {
        font: '700 32px ' + F, bg: 'rgba(110,231,183,.16)', border: 'rgba(110,231,183,.5)',
        color: '#6EE7B7', height: 62, padX: 26
      });
    }
    ctx.font = '700 44px ' + F;
    ctx.fillStyle = '#FFFFFF';
    ctx.fillText(tall ? 'Apply — link in bio' : 'Apply free on Howdy Jobs', pad, footY + 36);
    ctx.font = '500 36px ' + F;
    ctx.fillStyle = 'rgba(255,255,255,.5)';
    ctx.fillText('Part-time & casual jobs for students', pad, footY + 92);
  }

  function gapTotal(blocks) {
    return blocks.reduce(function (sum, b) { return sum + b.gap; }, 0);
  }

  /* ── modal ────────────────────────────────────────────────────────────── */
  function ensureModal() {
    if (document.getElementById('shareModal')) return;
    var el = document.createElement('div');
    el.className = 'modal';
    el.id = 'shareModal';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-modal', 'true');
    el.innerHTML = '<div class="modal-box" id="shareBody"></div>';
    document.body.appendChild(el);
  }

  function render() {
    var d = state.data;
    var body = document.getElementById('shareBody');

    body.innerHTML = '<div class="modal-head">'
      + '<div><h2>Promote on Instagram</h2>'
      + '<p class="biz">' + H.esc(d.job.title) + ' · ' + H.esc(d.job.location) + '</p></div>'
      + '<button class="x" data-close="shareModal" aria-label="Close">×</button></div>'
      + '<div class="chips" style="margin-bottom:16px">'
      + '<button class="chip' + (state.tab === 'image' ? ' on' : '') + '" data-tab="image">Post &amp; story</button>'
      + '<button class="chip' + (state.tab === 'reel' ? ' on' : '') + '" data-tab="reel">Reel script</button>'
      + '</div><div id="shareTab"></div>';

    body.querySelector('.chips').addEventListener('click', function (e) {
      var chip = e.target.closest('.chip');
      if (!chip) return;
      state.tab = chip.getAttribute('data-tab');
      render();
    });

    if (state.tab === 'image') renderImageTab();
    else renderReelTab();
  }

  function renderImageTab() {
    var d = state.data;
    document.getElementById('shareTab').innerHTML = '<div class="chips" style="margin-bottom:14px">'
      + Object.keys(SIZES).map(function (key) {
          return '<button class="chip' + (state.format === key ? ' on' : '') + '" data-fmt="' + key + '">'
            + H.esc(SIZES[key].label) + '</button>';
        }).join('')
      + '</div>'
      + '<div class="share-preview"><canvas id="shareCanvas" aria-label="'
      + H.esc(d.post.alt) + '"></canvas></div>'
      + '<div style="display:flex;flex-wrap:wrap;gap:8px;margin:16px 0">'
      + '<button class="btn btn-primary btn-sm" id="dlBtn">Download image</button>'
      + '<button class="btn btn-ghost btn-sm" id="shareBtn" hidden>Share to Instagram</button>'
      + '<button class="btn btn-ghost btn-sm" id="capBtn">Copy caption</button></div>'
      + '<label class="f" for="capText">Caption &amp; hashtags</label>'
      + '<textarea class="input" id="capText" rows="12" style="min-height:220px;font-size:13px">'
      + H.esc(d.post.caption) + '</textarea>'
      + '<p class="hint">Edit before posting if you like. Alt text: ' + H.esc(d.post.alt) + '</p>';

    var canvas = document.getElementById('shareCanvas');
    var paint = function () { draw(canvas, state.format); };
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(paint);
    else paint();
    paint();

    document.getElementById('shareTab').querySelector('.chips').addEventListener('click', function (e) {
      var chip = e.target.closest('.chip');
      if (!chip) return;
      state.format = chip.getAttribute('data-fmt');
      renderImageTab();
    });

    var fileName = function () {
      return 'howdy-' + state.format + '-'
        + state.data.job.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') + '.png';
    };

    document.getElementById('dlBtn').addEventListener('click', function () {
      canvas.toBlob(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = fileName();
        a.click();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
        H.toast('Image saved — open Instagram and post it.', 'ok');
      }, 'image/png');
    });

    document.getElementById('capBtn').addEventListener('click', function () {
      var text = document.getElementById('capText').value;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { H.toast('Caption copied.', 'ok'); });
      } else {
        document.getElementById('capText').select();
        H.toast('Press Ctrl/Cmd + C to copy.');
      }
    });

    // Phones can hand the image and caption straight to the Instagram app.
    var shareBtn = document.getElementById('shareBtn');
    if (navigator.canShare && navigator.share) {
      shareBtn.hidden = false;
      shareBtn.addEventListener('click', function () {
        canvas.toBlob(function (blob) {
          var file = new File([blob], fileName(), { type: 'image/png' });
          if (!navigator.canShare({ files: [file] })) {
            return H.toast('This browser cannot share files — use Download instead.', 'err');
          }
          navigator.share({ files: [file], text: document.getElementById('capText').value })
            .catch(function () { /* user dismissed the share sheet */ });
        }, 'image/png');
      });
    }
  }

  function renderReelTab() {
    var reel = state.data.reel;
    document.getElementById('shareTab').innerHTML = '<p class="notice" style="margin-bottom:16px">'
      + '<strong>Hook:</strong> ' + H.esc(reel.hook) + ' — ' + reel.lengthSeconds + ' seconds, shot on a phone.</p>'
      + '<div class="reel-steps">' + reel.scenes.map(function (s) {
          return '<div class="reel-step"><span class="tag">' + H.esc(s.seconds) + 's</span>'
            + '<div><p class="reel-on">' + H.esc(s.onScreen) + '</p>'
            + '<p class="hint" style="margin-top:4px"><strong>Shot:</strong> ' + H.esc(s.shot) + '</p>'
            + '<p class="hint" style="margin-top:2px"><strong>Say:</strong> “' + H.esc(s.say) + '”</p></div></div>';
        }).join('') + '</div>'
      + '<p class="hint" style="margin-top:14px">' + H.esc(reel.audioTip) + '</p>'
      + '<p class="hint">' + H.esc(reel.postingTip) + '</p>'
      + '<button class="btn btn-ghost btn-sm" id="reelCopy" style="margin-top:14px">Copy script</button>';

    document.getElementById('reelCopy').addEventListener('click', function () {
      var text = [reel.hook, ''].concat(reel.scenes.map(function (s) {
        return s.seconds + 's — ' + s.onScreen + '\n  Shot: ' + s.shot + '\n  Say: ' + s.say;
      })).concat(['', reel.audioTip, reel.postingTip]).join('\n');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () { H.toast('Reel script copied.', 'ok'); });
      } else {
        H.toast('Copy not supported in this browser.', 'err');
      }
    });
  }

  /**
   * Opens the share pack for a job. Called straight after a job is published,
   * and from the Promote button on any listing.
   */
  async function open(jobId) {
    ensureModal();
    try {
      state.data = await H.api('/api/social?id=' + encodeURIComponent(jobId));
    } catch (err) {
      return H.toast(err.message, 'err');
    }
    state.tab = 'image';
    state.format = 'post';
    render();
    H.openModal('shareModal');
  }

  H.sharePack = open;
})();
