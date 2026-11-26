'use strict';

let labMode = 'specimens';
let labCatalogue;
const labCategories = {
  mineral: 'Минералы', sedimentary_rock: 'Осадочные', igneous_rock: 'Магматические',
  metamorphic_rock: 'Метаморфические', core: 'Керн'
};

function openCourseLab() {
  labMode = 'course';
  if (view === 'lab') render();
  openView('lab');
}

function renderLabWorkspace(parent) {
  const nav = add(parent, 'nav', '', 'labModes');
  nav.setAttribute('aria-label', 'Режим лаборатории');
  for (const [id, label] of [
    ['specimens', 'Образцы'], ['microscope', 'Микроскоп'], ['compare', 'Сравнение'],
    ['calculation', 'Расчёты'], ['section', 'Разрезы'], ['course', 'Практика по курсу']
  ]) {
    const tab = button(nav, label, () => {
      if (labMode === id) return;
      labMode = id;
      render();
      content.querySelector('.labModes [aria-pressed=true]')?.focus();
    });
    tab.setAttribute('aria-pressed', String(id === labMode));
  }
  const workspace = add(parent, 'section', '', 'labWorkspace');
  if (labMode === 'calculation') labCalculation(workspace);
  else if (labMode === 'section') labCrossSection(workspace);
  else if (labMode === 'course') {
    specimenLab(workspace);
    renderLab();
  } else loadCatalogue(workspace);
}

async function loadCatalogue(parent) {
  if (layer.offline_demo) {
    add(parent, 'p', 'Коллекция фотографий доступна в серверной версии QABAT.');
    return;
  }
  const status = add(parent, 'p', 'Загружаем коллекцию…', 'muted');
  status.setAttribute('role', 'status');
  try {
    labCatalogue ||= api('lab/catalogue', undefined, 8000);
    const {assets} = await labCatalogue;
    if (!parent.isConnected) return;
    status.remove();
    if (labMode === 'microscope') labMicroscope(parent, assets.filter(asset => asset.views));
    else if (labMode === 'compare') labCompare(parent, assets.filter(asset => !asset.views));
    else labSpecimens(parent, assets.filter(asset => !asset.views));
  } catch (error) {
    labCatalogue = null;
    status.textContent = 'Коллекция недоступна. ' + error.message;
    button(parent, 'Повторить', () => { parent.replaceChildren(); loadCatalogue(parent); });
  }
}

function labSelect(parent, caption, options) {
  const label = add(parent, 'label', caption);
  const select = add(label, 'select');
  for (const [value, name] of options) add(select, 'option', name).value = value;
  return select;
}

function specimenDetails(parent, asset) {
  const panel = add(parent, 'div', '', 'labReading');
  for (const property of Object.values(asset.properties)) add(panel, 'p', property);
  if (asset.reference !== asset.source_url) labLink(panel, 'Справочник', asset.reference);
}

function labSpecimens(parent, assets) {
  const filters = add(parent, 'div', '', 'labFilters');
  const queryLabel = add(filters, 'label', 'Поиск образца');
  const query = add(queryLabel, 'input');
  query.type = 'search';
  query.placeholder = 'Например, кварц';
  const filter = labSelect(filters, 'Группа', [['', 'Все группы'], ...Object.entries(labCategories)]);
  const pickLabel = add(filters, 'label', 'Образец');
  const picker = add(pickLabel, 'select');
  const reading = add(parent, 'div');
  function show() {
    reading.replaceChildren();
    const asset = assets.find(item => item.asset_id === picker.value);
    if (!asset) { add(reading, 'p', 'Образцы по этому запросу не найдены.'); return; }
    add(reading, 'h3', asset.name);
    specimenViewer(reading, asset, () => add(reading, 'p', 'Снимок недоступен. Оригинал доступен по ссылке.'));
    specimenDetails(reading, asset);
    labObservation(reading, asset);
  }
  function filterList() {
    const selected = picker.value;
    const text = query.value.trim().toLocaleLowerCase('ru').replaceAll('ё', 'е');
    const matches = assets.filter(asset => (!filter.value || filter.value === asset.category)
      && [asset.name, asset.locality, ...Object.values(asset.properties)].join(' ')
        .toLocaleLowerCase('ru').replaceAll('ё', 'е').includes(text));
    picker.replaceChildren(...matches.map(asset => new Option(asset.name, asset.asset_id)));
    picker.disabled = !matches.length;
    if (matches.some(asset => asset.asset_id === selected)) picker.value = selected;
    show();
  }
  query.oninput = filter.onchange = filterList;
  picker.onchange = show;
  filterList();
}

function labObservation(parent, asset) {
  const section = details(parent, 'Задание на наблюдение', 'labReading');
  add(section, 'p', asset.question);
  const note = add(add(section, 'label', 'Моё наблюдение'), 'textarea');
  note.rows = 2;
  const storageKey = 'specimen/' + asset.asset_id;
  note.value = state.labNotes?.[storageKey] || '';
  note.oninput = () => { (state.labNotes ||= {})[storageKey] = note.value; save(); };
  const question = add(add(section, 'label', 'Вопрос тьютору'), 'input');
  question.maxLength = 400;
  const status = add(section, 'p');
  status.setAttribute('role', 'status');
  const ask = button(section, 'Получить подсказку', async () => {
    ask.disabled = true;
    status.textContent = 'Готовим подсказку…';
    try {
      const result = await labPost('observation', {asset_id: asset.asset_id, question: question.value.trim() || asset.question});
      status.textContent = result.by + ' · ' + result.hint;
    } catch (error) { status.textContent = error.message; }
    finally { ask.disabled = false; }
  });
}

function labMicroscope(parent, slides) {
  if (!slides.length) { add(parent, 'p', 'Шлифы пока недоступны.'); return; }
  const pick = labSelect(parent, 'Шлиф', slides.map(asset => [asset.asset_id, asset.name]));
  const content = add(parent, 'div');
  const modes = [
    ['ppl', 'PPL · плоская поляризация'], ['xpl', 'XPL · скрещённые поляризаторы']
  ];
  function show() {
    content.replaceChildren();
    const asset = slides.find(item => item.asset_id === pick.value);
    const selector = add(content, 'div', '', 'labModes');
    const caption = add(content, 'p', '', 'muted');
    const missing = add(content, 'p', 'Снимок недоступен. Открой оригинал по ссылке.');
    missing.hidden = true;
    const viewer = specimenViewer(content, {...asset, media_url: asset.views.ppl, alt: asset.name + ' · PPL'}, () => { missing.hidden = false; });
    modes.forEach(([value, title]) => {
      const control = button(selector, title, () => {
        missing.hidden = true;
        viewer.setImage(asset.views[value], asset.name + ' · ' + value.toUpperCase());
        for (const other of selector.children) other.setAttribute('aria-pressed', String(other === control));
        caption.textContent = value === 'ppl' ? 'Сравни форму зёрен, трещины и окраску.' : 'Найди интерференционные цвета на том же участке.';
      });
      control.setAttribute('aria-pressed', String(value === 'ppl'));
    });
    caption.textContent = 'Сравни форму зёрен, трещины и окраску.';
    specimenDetails(content, asset);
    labObservation(content, asset);
    quiz(content, {id: 'lab-xpl', type: 'single', question: 'В каком режиме наблюдаются интерференционные цвета?',
      options: ['PPL', 'XPL'], answer: 1, explanation: 'Скрещённые поляризаторы позволяют увидеть интерференционные цвета. Сравни один и тот же участок в обоих режимах.'});
  }
  pick.onchange = show;
  show();
  labLink(parent, 'Больше шлифов в Virtual Microscope ↗', 'https://www.virtualmicroscope.org/');
}

function labCompare(parent, assets) {
  if (assets.length < 2) { add(parent, 'p', 'Для сравнения нужны два снимка.'); return; }
  const options = assets.map(asset => [asset.asset_id, asset.name]);
  const filters = add(parent, 'div', '', 'labFilters');
  const left = labSelect(filters, 'Образец слева', options);
  const right = labSelect(filters, 'Образец справа', options);
  right.selectedIndex = 1;
  const link = add(filters, 'label', '', 'choice');
  const sync = add(link, 'input');
  sync.type = 'checkbox';
  link.append(' Связать масштаб');
  const pair = add(parent, 'div', '', 'labPair');
  function show() {
    for (const option of right.options) option.disabled = option.value === left.value;
    if (left.value === right.value) right.value = assets.find(asset => asset.asset_id !== left.value).asset_id;
    pair.replaceChildren();
    const views = [];
    for (const [i, selection] of [left, right].entries()) {
      const asset = assets.find(item => item.asset_id === selection.value);
      const column = add(pair, 'section');
      add(column, 'h3', asset.name);
      views.push(specimenViewer(column, asset, () => add(column, 'p', 'Нет снимка.'), scale => {
        if (sync.checked) views[1 - i]?.setZoom(scale);
      }));
      specimenDetails(column, asset);
    }
    sync.onchange = () => { if (sync.checked) views[1].setZoom(views[0].scale()); };
  }
  left.onchange = right.onchange = show;
  show();
  const note = add(add(parent, 'label', 'Какие различия заметны в форме, блеске или структуре?'), 'textarea');
  note.rows = 3;
  note.value = state.labNotes?.comparison || '';
  note.oninput = () => { (state.labNotes ||= {}).comparison = note.value; save(); };
}
