'use strict';

const formatLabels = {
  text: 'Текст', short: 'Шортс', long: 'Длинное видео',
  interactive: 'Интерактив', data: 'Практикум на данных', cards: 'Карточки'
};
const taskLabels = {
  single: 'Один ответ', multi: 'Несколько ответов', order: 'Порядок действий',
  cloze: 'Заполнение пропусков', calc: 'Расчёт'
};
const officialFiles = {
  'layer.json': 'Учебный слой', 'coverage.json': 'Покрытие', 'routing.json': 'Маршрутизация',
  'tasks.json': 'Задания', 'illustrations.json': 'Иллюстрации'
};

function renderStepFormat(parent, format) {
  if (!format?.primary) return;
  const label = 'Формат · ' + (formatLabels[format.primary] || format.primary);
  if (!format.reason) { add(parent, 'p', label, 'muted'); return; }
  const panel = details(parent, label, 'stepFormat');
  panel.firstElementChild.title = format.reason;
  bookText(panel, 'p', format.reason, 'muted');
}

function renderCourseAudit(parent) {
  const {report, coverage, validation} = layer.course_audit || {};
  const stats = add(parent, 'dl', '', 'auditStats');
  const stat = (label, value) => {
    if (value == null) return;
    const item = add(stats, 'div', '', 'box');
    add(item, 'dt', label, 'muted');
    add(item, 'dd', String(value));
  };
  stat('Модель', chapter.built_with?.model ?? report?.model);
  if (Number.isFinite(report?.claims_verified_share)) {
    const verified = new Intl.NumberFormat('ru', {style: 'percent', maximumFractionDigits: 1});
    stat('Проверенные цитаты', verified.format(report.claims_verified_share));
  }
  if (report?.coverage) {
    const {units, linked, skipped_with_reason} = report.coverage;
    stat('Единиц в главе', units);
    stat('Связаны с шагами', linked);
    stat('Пропущены с причиной', skipped_with_reason);
  }
  stat('Иллюстрации', report?.illustrations ?? nodes.reduce((sum, node) => sum + (node.illustrations?.length || 0), 0));

  if (report?.task_types) {
    add(parent, 'h3', 'Задания по типам');
    const list = add(parent, 'ul');
    for (const [type, count] of Object.entries(report.task_types)) {
      add(list, 'li', (taskLabels[type] || type) + ' · ' + count);
    }
  }

  const files = Object.entries(officialFiles);
  if (validation || report?.official) {
    const passed = name => validation ? validation[name]?.ok : report?.official?.[name];
    const count = files.filter(([name]) => passed(name) === true).length;
    const official = details(parent, 'Официальные форматы · ' + count + '/' + files.length + (count === files.length ? ' ✓' : ''));
    const list = add(official, 'ul');
    for (const [name, label] of files) {
      const status = passed(name);
      add(list, 'li', label + ' · ' + (status === true ? 'проверен' : status === false ? 'есть ошибки' : 'нет отчёта'));
    }
  }
  if (Array.isArray(coverage) && coverage.length) renderCoverage(parent, coverage);
  if (!report) add(parent, 'p', 'Для этой версии главы отчёт о сборке недоступен.', 'muted');
}

function renderCoverage(parent, coverage) {
  const panel = details(parent, 'Таблица покрытия');
  const label = add(panel, 'label', '', 'choice');
  const filter = add(label, 'input');
  filter.type = 'checkbox';
  label.append(' Только единицы без шага');
  const count = add(panel, 'p', '', 'muted');
  count.setAttribute('role', 'status');
  const table = add(add(panel, 'div', '', 'table-scroll'), 'table', '', 'coverageTable');
  table.setAttribute('aria-label', 'Покрытие материала главы');
  const header = add(add(table, 'thead'), 'tr');
  for (const title of ['Единица', 'Страница', 'Шаг или причина']) add(header, 'th', title).scope = 'col';
  const body = add(table, 'tbody');
  function draw() {
    const rows = filter.checked ? coverage.filter(row => !nodeById.has(row.node)) : coverage;
    count.textContent = 'Показано ' + rows.length + ' из ' + coverage.length;
    body.replaceChildren();
    for (const row of rows) {
      const line = add(body, 'tr');
      add(line, 'th', row.unit).scope = 'row';
      const reference = add(line, 'td');
      source(reference, row.page);
      const destination = add(line, 'td');
      const node = nodeById.get(row.node);
      if (node) stepButton(destination, node);
      else destination.textContent = row.reason || 'Шаг не указан';
    }
  }
  panel.ontoggle = () => { if (panel.open && !body.childElementCount) draw(); };
  filter.onchange = draw;
}
