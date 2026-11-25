'use strict';
// Ролики шага (nodes[].videos): {src, poster?, captions?, title, format, passport?}. Показ над текстом шага.
(function () {
  function place() {
    const box = document.getElementById('content');
    if (!box || typeof current === 'undefined') return;
    box.querySelectorAll('.stepVideo').forEach(e => e.remove());
    for (const v of current.videos || []) {
      const fig = document.createElement('figure');
      fig.className = 'stepVideo';
      const video = document.createElement('video');
      video.controls = true;
      video.preload = 'metadata';
      video.src = v.src;
      if (v.poster) video.poster = v.poster;
      video.style.cssText = 'max-width:100%;max-height:70vh;border-radius:12px;display:block;margin:auto;background:#000';
      if (v.captions) {
        const tr = document.createElement('track');
        tr.kind = 'subtitles'; tr.srclang = 'ru'; tr.label = 'Русские'; tr.src = v.captions; tr.default = true;
        video.append(tr);
      }
      const cap = document.createElement('figcaption');
      cap.textContent = (v.format === 'shorts' ? 'Шортс · ' : 'Разбор · ') + v.title + (v.passport ? ' · ' : '');
      if (v.passport) {
        const a = document.createElement('a'); a.href = v.passport; a.target = '_blank'; a.textContent = 'паспорт ролика';
        cap.append(a);
      }
      cap.style.cssText = 'text-align:center;color:var(--muted);font-size:.9rem;margin-top:6px';
      fig.append(video, cap);
      fig.style.margin = '12px 0 20px';
      const h = box.querySelector('h2');
      (h ? h.nextSibling : box.firstChild) ? box.insertBefore(fig, h ? h.nextSibling : box.firstChild) : box.append(fig);
    }
  }
  new MutationObserver(() => { if (!document.querySelector('#content .stepVideo') && (current.videos || []).length) place(); })
    .observe(document.getElementById('content'), {childList: true});
  place();
})();
