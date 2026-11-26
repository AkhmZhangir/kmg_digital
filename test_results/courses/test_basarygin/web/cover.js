'use strict';

function startCoverAnimation() {
  const banner = document.querySelector('.cover');
  const canvas = banner.querySelector('canvas');
  const context = canvas.getContext('2d');
  if (!context) return;

  const layers = [
    { color: '#a8a6d4', period: 6.7, amplitude: 27 },
    { color: '#cbc8e7', period: 4.9, amplitude: 20 },
    { color: '#dedcf0', period: 3.6, amplitude: 15 },
    { color: '#bcb8dc', period: 5.8, amplitude: 25 },
    { color: '#a7a3cd', period: 2.8, amplitude: 12 },
    { color: '#cbc8e6', period: 4.2, amplitude: 20 },
    { color: '#bab7d9', period: 6.2, amplitude: 24 },
    { color: '#9692be', period: 3.2, amplitude: 14 },
    { color: '#817dab', period: 5.3, amplitude: 18 }
  ];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const tau = Math.PI * 2;
  let columns = [];
  let width = 0;
  let height = 0;
  let frame = null;
  let previousTime = null;
  let elapsed = 0;
  let inView = !('IntersectionObserver' in window);

  function draw(animate) {
    if (!columns.length) return;
    const left = columns[0].x;
    context.clearRect(left - 1, 0, width - left + 1, height);
    const spacing = height / 13;
    const minimumGap = spacing * .34;
    const strength = animate ? Math.min(1, height / 160) * Math.min(1, elapsed / .7) : 0;

    layers.forEach(({ color, period, amplitude }, index) => {
      const phase = index * 2.39996;
      const tide = elapsed * tau / period;
      // The slower drift and traveling waves keep the layers from settling into a shared loop.
      const lift = .68 * Math.sin(tide + phase) + .22 * Math.sin(tide * .437 - phase);
      context.beginPath();
      context.moveTo(left, height + 2);
      for (const column of columns) {
        const wave = .34 * Math.sin(column.position * (9 + index * .85) - tide * 1.13 + phase);
        const bend = .21 * Math.sin(column.position * 4.5 + tide * .71 - phase);
        let edge = column.baseline + index * spacing + strength * column.envelope * amplitude * (lift + wave + bend);
        if (animate && index > 0) {
          // A soft minimum clearance absorbs compression without crossing adjacent boundaries.
          const floor = column.edge + minimumGap;
          const distance = edge - floor;
          if (distance < 2) edge = floor + 4 / (4 - distance);
        }
        column.edge = edge;
        context.lineTo(column.x, edge);
      }
      context.lineTo(width, height + 2);
      context.closePath();
      context.fillStyle = color;
      context.fill();
    });
  }

  function resize() {
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    columns = [];
    if (!width || !height) return;
    const segments = Math.max(1, Math.ceil(width * .64 / 8));
    for (let i = 0; i <= segments; i++) {
      const position = i / segments;
      const t = .36 + .64 * position;
      columns.push({
        x: i === segments ? width : width * t,
        position,
        baseline: height * (1.48 - (t - .36) * 2 + .095 * Math.sin(t * 21) + .033 * Math.sin(t * 54)),
        envelope: Math.sin(Math.min(1, position * 2) * Math.PI / 2),
        edge: 0
      });
    }
    draw(!reducedMotion.matches);
  }

  function tick(time) {
    if (previousTime !== null) elapsed += Math.min(time - previousTime, 50) / 1000;
    previousTime = time;
    draw(true);
    frame = requestAnimationFrame(tick);
  }

  function syncAnimation() {
    if (inView && !document.hidden && !reducedMotion.matches) {
      if (frame === null) frame = requestAnimationFrame(tick);
    } else {
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      previousTime = null;
      if (reducedMotion.matches) draw(false);
    }
  }

  resize();
  new ResizeObserver(resize).observe(banner);
  if ('IntersectionObserver' in window) {
    new IntersectionObserver(([entry]) => {
      inView = entry.isIntersecting;
      syncAnimation();
    }).observe(banner);
  }
  reducedMotion.addEventListener('change', syncAnimation);
  document.addEventListener('visibilitychange', syncAnimation);
  syncAnimation();
}
