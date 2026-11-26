'use strict';

const labCalculations = {
  porosity: {
    title: 'Пористость керна', formula: 'φ = объём пор / объём керна × 100%',
    fields: [['Объём пор, см³', 24], ['Объём керна, см³', 120]],
    source: 'https://glossary.slb.com/terms/p/porosity'
  },
  saturation: {
    title: 'Водонасыщенность', formula: 'Sᵥ = объём воды / объём пор × 100%',
    fields: [['Объём воды, см³', 9], ['Объём пор, см³', 24]],
    source: 'https://glossary.slb.com/en/terms/w/water_saturation'
  },
  net: {
    title: 'Доля коллектора в интервале', formula: 'N/G = мощность коллектора / мощность всего интервала × 100%',
    fields: [['Суммарная мощность коллектора, м', 12], ['Общая мощность интервала, м', 30]],
    source: 'https://pubs.usgs.gov/publication/sir20255108/full'
  }
};

function labRatio(part, total) {
  return Number.isFinite(part) && Number.isFinite(total) && part >= 0 && total > 0 && part <= total
    ? part / total * 100 : null;
}

function labCalculation(parent) {
  const options = Object.entries(labCalculations).map(([id, exercise]) => [id, exercise.title]);
  const selector = labSelect(parent, 'Величина', options);
  const pane = add(parent, 'section', '', 'labReading');
  function show() {
    pane.replaceChildren();
    const exercise = labCalculations[selector.value];
    add(pane, 'h3', exercise.title);
    const formula = details(pane, 'Показать формулу');
    add(formula, 'p', exercise.formula);
    labLink(formula, 'Определение', exercise.source);
    const form = add(pane, 'form', '', 'labForm');
    const inputs = exercise.fields.map(([label, sample]) => {
      const input = add(add(form, 'label', label), 'input');
      Object.assign(input, {type: 'number', value: sample, min: 0, step: 'any', required: true, inputMode: 'decimal'});
      return input;
    });
    const answer = add(add(form, 'label', 'Мой ответ, %'), 'input');
    Object.assign(answer, {type: 'number', min: 0, max: 100, step: 'any', required: true, inputMode: 'decimal'});
    const result = add(form, 'output');
    result.setAttribute('aria-live', 'polite');
    form.oninput = () => { result.textContent = ''; };
    add(form, 'button', 'Проверить расчёт', 'primary').type = 'submit';
    form.onsubmit = event => {
      event.preventDefault();
      const [part, total] = inputs.map(input => input.valueAsNumber);
      const value = labRatio(part, total);
      if (value === null) {
        result.textContent = 'Общий объём или мощность должны быть больше нуля. Часть не может превышать целое.';
        return;
      }
      const number = new Intl.NumberFormat('ru', {maximumFractionDigits: 2}).format(value);
      result.textContent = (Math.abs(answer.valueAsNumber - value) <= .05 ? 'Верно. ' : 'Перепроверь деление. ')
        + part + ' ÷ ' + total + ' × 100 = ' + number + '%.';
    };
  }
  selector.onchange = show;
  show();
}

const labSections = {
  anticline: {title: 'Антиклинальная складка', prompt: 'Как ведёт себя слой в центре?', correct: 0,
    explanation: 'Слои выгнуты вверх. На обоих крыльях они падают от оси складки.'},
  syncline: {title: 'Синклинальная складка', prompt: 'Как ведёт себя слой в центре?', correct: 1,
    explanation: 'Слои прогибаются вниз. На обоих крыльях они падают к оси складки.'},
  fault: {title: 'Разлом', prompt: 'Что происходит с одним и тем же слоем справа от разлома?', correct: 2,
    explanation: 'По тому же цвету можно проследить слой. Правая часть смещена вниз относительно левой.'}
};

function labCrossSection(parent) {
  const selector = labSelect(parent, 'Структура', Object.entries(labSections).map(([id, model]) => [id, model.title]));
  add(parent, 'p', 'Упрощённый учебный разрез. Расстояния и толщина слоёв не в масштабе.', 'muted');
  const label = add(parent, 'label', 'Выраженность структуры');
  const slider = add(label, 'input');
  Object.assign(slider, {type: 'range', min: 10, max: 100, value: 70});
  const canvas = add(parent, 'canvas', '', 'labSection');
  canvas.width = 760;
  canvas.height = 315;
  const context = canvas.getContext('2d');
  if (!context) { add(parent, 'p', 'Браузер не может отобразить разрез.'); return; }
  canvas.setAttribute('role', 'img');
  const exercises = add(parent, 'div');
  const colors = ['#e6cb88', '#b37853', '#818abb', '#6b9f96', '#bea398'];

  function paint() {
    const type = selector.value;
    const amount = Number(slider.value) * .8;
    canvas.setAttribute('aria-label', labSections[type].title + '. Выраженность ' + slider.value + '%.');
    context.fillStyle = '#eceaf2';
    context.fillRect(0, 0, canvas.width, canvas.height);
    const top = (y, x) => y + (type === 'fault' ? (x >= 380 ? amount : 0)
      : (type === 'anticline' ? -amount : amount) * Math.sin(Math.PI * x / canvas.width) ** 2);
    const halves = type === 'fault' ? [[0, 379], [380, 760]] : [[0, 760]];
    for (const [start, end] of halves) {
      colors.forEach((color, i) => {
        const y = 90 + 40 * i;
        const points = [...Array.from({length: Math.ceil((end - start) / 6)}, (_, j) => start + j * 6), end];
        context.beginPath();
        points.forEach((x, j) => j === 0 ? context.moveTo(x, top(y, x)) : context.lineTo(x, top(y, x)));
        points.reverse().forEach(x => context.lineTo(x, top(y + 40, x)));
        context.closePath();
        context.fillStyle = color;
        context.fill();
      });
    }
    if (type === 'fault') {
      context.beginPath();
      context.moveTo(380, 36);
      context.lineTo(380, canvas.height);
      context.strokeStyle = '#30263c';
      context.lineWidth = 2;
      context.setLineDash([6, 6]);
      context.stroke();
      context.setLineDash([]);
    }
  }

  function show() {
    paint();
    exercises.replaceChildren();
    const model = labSections[selector.value];
    quiz(exercises, {id: 'lab-section', type: 'single', question: model.prompt,
      options: ['Выгибается вверх', 'Прогибается вниз', 'Смещается вниз относительно левой части'],
      answer: model.correct, explanation: model.explanation});
  }
  slider.oninput = paint;
  selector.onchange = show;
  show();
}
