'use strict';

function labFullscreen(parent, target) {
  if (!document.fullscreenEnabled) return;
  button(parent, 'Полный экран', async () => {
    try {
      if (document.fullscreenElement === target) await document.exitFullscreen();
      else await target.requestFullscreen();
    } catch { add(parent, 'small', 'Браузер не разрешил полноэкранный режим.'); }
  });
}

function specimenViewer(parent, task, missing, onZoom, {inlineImage = false} = {}) {
  const figure = add(parent, 'figure', '', 'specimen');
  const frame = add(figure, 'div', '', 'specimenFrame');
  frame.tabIndex = 0;
  frame.setAttribute('aria-label', 'Образец. Колесо и щипок меняют масштаб, стрелки и перетаскивание перемещают снимок.');
  frame.setAttribute('role', 'region');
  const img = add(frame, 'img');
  img.alt = task.alt || task.locality;
  img.draggable = false;
  img.loading = 'lazy';
  const bar = add(figure, 'div', '', 'viewerTools');
  const pointers = new Map();
  let scale = 1, panX = 0, panY = 0;
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));

  function paint() {
    const w = frame.clientWidth, h = frame.clientHeight;
    if (!img.naturalWidth || !w || !h) return;
    const fit = Math.min(w / img.naturalWidth, h / img.naturalHeight);
    const iw = img.naturalWidth * fit, ih = img.naturalHeight * fit;
    const limitX = Math.max(0, (iw * scale - w) / 2);
    const limitY = Math.max(0, (ih * scale - h) / 2);
    panX = clamp(panX, -limitX, limitX);
    panY = clamp(panY, -limitY, limitY);
    img.style.width = iw + 'px';
    img.style.height = ih + 'px';
    img.style.transform = 'translate(-50%, -50%) translate(' + panX + 'px,' + panY + 'px) scale(' + scale + ')';
    frame.style.cursor = scale > 1 ? 'grab' : 'zoom-in';
  }

  function zoom(value, anchor = {x: 0, y: 0}, notify = true) {
    const next = clamp(value, 1, 5), ratio = next / scale;
    panX = anchor.x - (anchor.x - panX) * ratio;
    panY = anchor.y - (anchor.y - panY) * ratio;
    scale = next;
    range.value = Math.round(scale * 100);
    output.textContent = range.value + '%';
    minus.disabled = scale <= 1;
    plus.disabled = scale >= 5;
    paint();
    if (notify) onZoom?.(scale);
  }

  const minus = button(bar, '−', () => zoom(scale - .25));
  minus.setAttribute('aria-label', 'Уменьшить');
  const range = add(bar, 'input');
  Object.assign(range, {type: 'range', min: 100, max: 500, value: 100});
  range.setAttribute('aria-label', 'Масштаб фотографии');
  range.oninput = () => zoom(+range.value / 100);
  const plus = button(bar, '+', () => zoom(scale + .25));
  plus.setAttribute('aria-label', 'Увеличить');
  const output = add(bar, 'output');
  button(bar, 'Сбросить вид', () => zoom(1));
  if (!inlineImage) labFullscreen(bar, figure);
  const point = e => {
    const rect = frame.getBoundingClientRect();
    return {x: e.clientX - rect.left - rect.width / 2, y: e.clientY - rect.top - rect.height / 2};
  };
  frame.addEventListener('wheel', e => {
    e.preventDefault();
    zoom(scale * Math.exp(-e.deltaY * (e.deltaMode === 1 ? .045 : .003)), point(e));
  }, {passive: false});
  function gesture() {
    const [a, b] = pointers.values();
    return b ? {x: (a.x+b.x)/2, y: (a.y+b.y)/2, length: Math.hypot(a.x-b.x,a.y-b.y)} : a;
  }
  frame.onpointerdown = e => {
    if (e.button !== 0 || pointers.size >= 2) return;
    pointers.set(e.pointerId, point(e));
    frame.setPointerCapture(e.pointerId);
  };
  frame.onpointermove = e => {
    if (!pointers.has(e.pointerId)) return;
    const before = gesture();
    pointers.set(e.pointerId, point(e));
    const after = gesture();
    if (before.length > 0 && after.length > 0) zoom(scale * after.length / before.length, before);
    panX += after.x - before.x; panY += after.y - before.y;
    paint();
  };
  frame.onlostpointercapture = frame.onpointercancel = frame.onpointerup = e => pointers.delete(e.pointerId);
  frame.onkeydown = e => {
    const step = {ArrowLeft:[32,0], ArrowRight:[-32,0], ArrowUp:[0,32], ArrowDown:[0,-32]}[e.key];
    if (step) { e.preventDefault(); panX += step[0]; panY += step[1]; paint(); }
  };
  const observer = new ResizeObserver(() => { if (frame.isConnected) paint(); else observer.disconnect(); });
  observer.observe(frame);
  img.onload = () => {
    frame.hidden = bar.hidden = false;
    paint();
  };
  img.onerror = () => { frame.hidden = bar.hidden = true; missing?.(); };
  if (!inlineImage) {
    const caption = add(figure, 'figcaption');
    add(caption, 'span', task.locality);
    add(caption, 'span', task.attribution + ' · ' + task.license);
    if (task.license_url) labLink(caption, 'Лицензия', task.license_url);
    labLink(caption, 'Оригинал ↗', task.source_url);
  }
  img.src = inlineImage ? task.media_url : apiBase + task.media_url;
  zoom(1, undefined, false);
  return {
    setZoom: v => zoom(v, undefined, false),
    scale: () => scale,
    setImage(url, alt) {
      img.alt = alt;
      img.src = apiBase + url;
    }
  };
}
