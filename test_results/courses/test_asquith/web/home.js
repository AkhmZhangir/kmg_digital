'use strict';

const get = id => document.getElementById(id);
const status = get('homeStatus');
let pendingUpload;
let busy = false;
let collectionRequest = 0;
let documentsId;

function element(parent, tag, text = '', css = '') {
  const node = document.createElement(tag);
  node.textContent = text;
  if (css) node.className = css;
  parent.append(node);
  return node;
}

function action(parent, label, handler) {
  const control = element(parent, 'button', label);
  control.onclick = handler;
  return control;
}

function showTheme(dark) {
  document.documentElement.dataset.dark = String(dark);
  get('theme').setAttribute('aria-pressed', String(dark));
}
showTheme(readGeoTheme());
get('theme').onclick = () => {
  const dark = document.documentElement.dataset.dark !== 'true';
  writeGeoTheme(dark);
  showTheme(dark);
};

async function refreshSpaces() {
  const sequence = ++collectionRequest;
  try {
    const {spaces, documents} = await spaceRequest('');
    if (sequence !== collectionRequest) return;
    const target = get('uploadLibrary');
    const selected = target.value;
    documentsId = documents.id;
    target.replaceChildren(new Option('Без библиотеки', documentsId));
    const documentsLink = get('homeDocuments');
    documentsLink.href = '/spaces/' + documentsId + '?panel=sources';
    documentsLink.hidden = false;
    get('homeDocumentsCount').textContent = String(documents.sources);
    for (const library of spaces) target.add(new Option(library.name, library.id));
    if (spaces.some(library => library.id === selected)) target.value = selected;
    const grid = get('spaces');
    grid.replaceChildren();
    get('emptySpaces').hidden = Boolean(spaces.length);
    for (const space of spaces) {
      const card = element(grid, 'article', '', 'homeLibrary');
      const link = element(element(card, 'h3'), 'a', space.name);
      link.href = '/spaces/' + space.id;
      const count = new Intl.NumberFormat('ru').format(space.sources);
      element(card, 'p', 'Источников: ' + count, 'muted');
      const actions = element(card, 'div', '', 'spaceActions');
      action(actions, 'Переименовать', async () => {
        const name = await askName('Переименовать библиотеку', space.name);
        if (name !== null) await updateSpace(space.id, {action: 'rename_space', name});
      });
      action(actions, 'Удалить', async () => {
        const result = await spaceDialog('Удалить «' + space.name + '»?',
          'Библиотека, папки и загруженные документы будут удалены.', [['delete', 'Удалить библиотеку']]);
        if (result) await updateSpace(space.id, {action: 'delete_space'});
      });
    }
  } catch (error) { status.textContent = error.message; }
}

async function updateSpace(id, values) {
  try {
    await spaceRequest('/' + id, values);
    status.textContent = values.action === 'delete_space' ? 'Библиотека удалена.' : 'Название сохранено.';
    await refreshSpaces();
  } catch (error) { status.textContent = error.message; }
}

get('createSpace').onclick = async () => {
  try { await createLibrary(); }
  catch (error) { status.textContent = error.message; }
};

async function uploadFromHome() {
  if (busy || !pendingUpload) return;
  busy = true;
  const controls = ['uploadHome', 'retryHome', 'uploadLibrary'].map(get);
  controls.forEach(control => { control.disabled = true; });
  get('uploadRecovery').hidden = true;
  try {
    pendingUpload.id ||= documentsId || (await spaceRequest('')).documents.id;
    const failed = [];
    const messages = [];
    for (const file of pendingUpload.files) {
      status.textContent = 'Загрузка: ' + file.name;
      try {
        await uploadSpaceFile(pendingUpload.id, file, null, () => {
          status.textContent = 'Извлекаем текст: ' + file.name;
        });
      } catch (error) {
        failed.push(file);
        messages.push(file.name + ' · ' + error.message);
      }
    }
    pendingUpload.files = failed;
    if (failed.length) throw Error(messages.join(' '));
    location.assign('/spaces/' + pendingUpload.id + '?panel=sources');
  } catch (error) {
    status.textContent = error.message;
    get('openAfterFailure').hidden = !pendingUpload.id;
    if (pendingUpload.id) get('openAfterFailure').href = '/spaces/' + pendingUpload.id + '?panel=sources';
    get('uploadRecovery').hidden = false;
    await refreshSpaces();
  } finally {
    controls.forEach(control => { control.disabled = false; });
    busy = false;
  }
}

function startUpload(files) {
  if (busy || !files.length) return;
  pendingUpload = {id: get('uploadLibrary').value, files};
  uploadFromHome();
}

get('uploadHome').onclick = () => get('homeFile').click();
get('homeFile').onchange = event => {
  const files = Array.from(event.target.files);
  event.target.value = '';
  startUpload(files);
};
const drop = get('homeDrop');
drop.ondragover = event => {
  if (!event.dataTransfer.types.includes('Files')) return;
  event.preventDefault();
  if (!busy) drop.dataset.drop = 'allowed';
  event.dataTransfer.dropEffect = busy ? 'none' : 'copy';
};
drop.ondragleave = event => { if (!drop.contains(event.relatedTarget)) delete drop.dataset.drop; };
drop.ondrop = event => {
  event.preventDefault();
  delete drop.dataset.drop;
  startUpload(Array.from(event.dataTransfer.files));
};
get('retryHome').onclick = uploadFromHome;
let catalogRequest = 0;
async function refreshCatalog() {
  const request = ++catalogRequest;
  try {
    const response = await fetch('/api/catalog', {cache: 'no-store'});
    if (!response.ok) throw Error('Каталог курсов недоступен.');
    const {courses} = await response.json();
    if (request !== catalogRequest) return;
    get('emptyCatalog').hidden = Boolean(courses.length);
    const catalog = get('catalog');
    catalog.replaceChildren();
    for (const course of courses) {
      const data = course.chapter;
      const card = element(catalog, 'article', '', 'spaceCard');
      const heading = element(element(card, 'h3'), 'a', data.title_short || data.title || course.name);
      heading.href = '/' + encodeURIComponent(course.folder) + '/index.html';
      const meta = [data.author, course.pages?.length ? 'стр. ' + course.pages.join('–') : '', 'Шагов: ' + course.nodes];
      element(card, 'p', meta.filter(Boolean).join(' · '), 'muted');
      if (course.needs_review) element(card, 'small', 'Требует проверки', 'qualityBadge');
      else if (data.built_with?.model === 'mock') element(card, 'small', 'Черновик', 'qualityBadge');
    }
  } catch (error) {
    if (request === catalogRequest) status.textContent = error.message;
  }
}

window.addEventListener('pageshow', () => {
  showTheme(readGeoTheme());
  refreshSpaces();
  refreshCatalog();
});
window.addEventListener('focus', refreshCatalog);
startCoverAnimation();
