'use strict';

const workspace = $('workspace');
const chatModes = {
  ask: ['Спросить', 'Что хочешь понять?', 'Задай вопрос по выбранным источникам.', 'Объясни главное простыми словами'],
  learn: ['Изучить', 'Разберём тему по шагам', 'Выбери понятие или продолжи текущий урок.', 'С чего начать изучение этой темы?'],
  practice: ['Практика', 'Примени знания', 'Попроси задачу по текущему уроку или открой готовые тесты.', 'Дай задачу по текущему уроку'],
  review: ['Повторить', 'Что стоит повторить?', 'Начни с ключевых понятий текущего урока.', 'Какие термины мне нужно повторить?']
};
const selectedSources = new Set([chapter.id]);
let localSourceId = 0;
let previewURL;
let previewRequest = 0;

function updateChatContext() {
  $('chatLesson').textContent = current.title;
  $('chatSources').textContent = 'Выбрано источников: ' + selectedSources.size;
}

function showWorkspace(chat) {
  $('chatPane').hidden = !chat;
  $('lessonPane').hidden = chat;
  $('showLesson').setAttribute('aria-pressed', String(!chat));
  $('showChat').setAttribute('aria-pressed', String(chat));
  workspace.dataset.chat = String(chat);
}

function setChatMode(mode) {
  const [, heading, help, suggestion] = chatModes[mode];
  state.chatMode = mode;
  save();
  $('chatHeading').textContent = heading;
  $('chatHelp').textContent = help;
  for (const control of $('chatModes').children) {
    control.setAttribute('aria-pressed', String(control.dataset.mode === mode));
  }
  const suggestions = $('chatSuggestions');
  suggestions.replaceChildren();
  button(suggestions, suggestion, () => {
    if (!$('chatDraft').value.trim()) $('chatDraft').value = suggestion;
    saveDraft();
    $('chatDraft').focus();
  });
  if (mode !== 'ask') {
    const viewsByMode = {learn: 'lesson', practice: 'practice', review: 'cards'};
    const labels = {learn: 'К уроку', practice: 'Открыть тесты', review: 'Открыть карточки'};
    button(suggestions, labels[mode], () => openView(viewsByMode[mode]));
  }
}

function saveDraft() {
  state.chatDraft = $('chatDraft').value;
  $('chatStatus').textContent = save()
    ? 'Модель пока не подключена. Черновик сохранён на устройстве.'
    : 'Модель пока не подключена. Черновик доступен до закрытия страницы.';
}

function panel(name) {
  document.body.dataset.panel = name;
  for (const control of $('mobileNav').children) {
    control.setAttribute('aria-pressed', String(control.dataset.panel === name));
  }
}

for (const [id, title] of [['sources', 'Источники'], ['read', 'Тьютор'], ['tools', 'Студия']]) {
  const control = button($('mobileNav'), title, () => panel(id));
  control.dataset.panel = id;
}
panel('read');

function syncExpanded(control) {
  const expanded = workspace.dataset.expanded === 'true';
  control.textContent = expanded ? 'Свернуть' : 'Развернуть';
  control.setAttribute('aria-pressed', String(expanded));
}

function toggleExpanded(control) {
  workspace.dataset.expanded = String(workspace.dataset.expanded !== 'true');
  syncExpanded(control);
}

function setupPanel(panelName, element, toggle, grip, width, direction) {
  const property = '--' + panelName + '-width';
  const minimum = 206;
  const maximum = 330;

  function resize(value) {
    width = Math.max(minimum, Math.min(maximum, value));
    workspace.style.setProperty(property, width + 'px');
    grip.setAttribute('aria-valuenow', width);
  }

  grip.setAttribute('aria-valuemin', minimum);
  grip.setAttribute('aria-valuemax', maximum);
  resize(width);

  toggle.onclick = () => {
    const collapsed = toggle.getAttribute('aria-expanded') === 'true';
    workspace.dataset[panelName + 'Collapsed'] = String(collapsed);
    toggle.setAttribute('aria-expanded', String(!collapsed));
  };
  grip.onkeydown = event => {
    const steps = {ArrowLeft: -16, ArrowRight: 16};
    if (event.key in steps) resize(width + direction * steps[event.key]);
    else if (event.key === 'Home') resize(minimum);
    else if (event.key === 'End') resize(maximum);
    else return;
    event.preventDefault();
  };
  grip.onpointerdown = event => {
    if (event.button !== 0) return;
    grip.focus();
    grip.setPointerCapture(event.pointerId);
    const origin = event.clientX;
    const start = element.getBoundingClientRect().width;
    grip.onpointermove = move => resize(start + direction * (move.clientX - origin));
  };
  grip.onlostpointercapture = () => { grip.onpointermove = null; };
}

setupPanel('sources', $('sourcesPanel'), $('toggleSources'), $('resizeSources'), 246, 1);
setupPanel('studio', $('studioPanel'), $('toggleStudio'), $('resizeStudio'), 260, -1);

function sourceRow(parent, id, name, metadata) {
  const label = add(parent, 'label', '', 'sourceChoice');
  const check = add(label, 'input');
  check.type = 'checkbox';
  check.checked = selectedSources.has(id);
  check.onchange = () => {
    if (check.checked) selectedSources.add(id);
    else selectedSources.delete(id);
    updateChatContext();
  };
  add(label, 'strong', name);
  add(parent, 'small', metadata, 'sourceMeta');
}

function openPDF(parent, url) {
  const link = add(parent, 'a', 'Открыть PDF');
  link.href = url;
  link.target = '_blank';
  link.rel = 'noopener';
}

function previewContainer(name) {
  URL.revokeObjectURL(previewURL);
  previewURL = undefined;
  const preview = $('sourcePreview');
  preview.replaceChildren();
  preview.hidden = false;
  const head = add(preview, 'div', '', 'panelHeader');
  add(head, 'strong', name);
  button(head, 'Закрыть', () => {
    previewRequest++;
    URL.revokeObjectURL(previewURL);
    previewURL = undefined;
    preview.hidden = true;
    const trigger = $('sourcePreview').trigger;
    trigger?.focus();
  });
  preview.focus();
  return preview;
}

const book = $('book');
sourceRow(book, chapter.id, chapter.book, chapter.author + ' · стр. ' + chapter.pages.join('–'));
if (chapter.pdf && localPath(chapter.pdf)) {
  const trigger = button(book, 'Предпросмотр', () => {
    previewRequest++;
    const preview = previewContainer(chapter.book);
    preview.trigger = trigger;
    const url = chapter.pdf + '#page=' + pdfPage(chapter.pages[0]);
    const frame = add(preview, 'iframe');
    frame.title = 'Предпросмотр книги';
    frame.src = url;
    openPDF(preview, url);
  });
}

$('addSource').onclick = () => $('sourceFiles').click();
$('sourceFiles').onchange = event => {
  const files = Array.from(event.target.files);
  let added = 0;
  for (const file of files) {
    const extension = file.name.split('.').pop().toLowerCase();
    if (!['pdf', 'docx', 'txt', 'md'].includes(extension)) continue;
    const id = Symbol(++localSourceId);
    selectedSources.add(id);
    const row = add($('localSources'), 'div', '', 'book localSource');
    sourceRow(row, id, file.name, 'Локальный файл · ожидает обработки');
    const trigger = button(row, 'Предпросмотр', async () => {
      const request = ++previewRequest;
      const preview = previewContainer(file.name);
      preview.trigger = trigger;
      if (extension === 'pdf') {
        previewURL = URL.createObjectURL(new Blob([file], {type: 'application/pdf'}));
        const frame = add(preview, 'iframe');
        frame.title = 'Предпросмотр PDF';
        frame.src = previewURL;
        openPDF(preview, previewURL);
      } else if (extension === 'docx') {
        add(preview, 'p', 'Предпросмотр DOCX доступен после серверной обработки.');
      } else {
        const status = add(preview, 'p', 'Читаем файл…');
        status.setAttribute('role', 'status');
        try {
          const excerpt = await file.slice(0, 32768).text();
          if (request !== previewRequest) return;
          status.remove();
          add(preview, 'pre', excerpt + (file.size > 32768 ? '\n…' : ''));
        } catch {
          if (request === previewRequest) status.textContent = 'Не удалось прочитать файл.';
        }
      }
    });
    added++;
  }
  $('sourceStatus').textContent = added
    ? 'Добавлено локально: ' + added + '. Обработка на сервере пока недоступна.'
    : 'Поддерживаются PDF, DOCX, TXT и Markdown.';
  event.target.value = '';
  updateChatContext();
};

for (const [mode, [label]] of Object.entries(chatModes)) {
  const control = button($('chatModes'), label, () => setChatMode(mode));
  control.dataset.mode = mode;
}
$('chatDraft').value = state.chatDraft || '';
$('chatDraft').oninput = saveDraft;
$('chatForm').onsubmit = event => event.preventDefault();
$('showChat').onclick = () => showWorkspace(true);
$('showLesson').onclick = () => showWorkspace(false);
setChatMode(Object.hasOwn(chatModes, state.chatMode) ? state.chatMode : 'ask');

function setTheme(dark) {
  document.documentElement.dataset.dark = String(dark);
  $('theme').setAttribute('aria-pressed', String(dark));
}
setTheme(state.dark === true);
$('theme').onclick = () => {
  state.dark = document.documentElement.dataset.dark !== 'true';
  setTheme(state.dark);
  save();
};

showWorkspace(false);
new ResizeObserver(cover).observe(document.querySelector('.cover'));
render();
