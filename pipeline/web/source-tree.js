'use strict';

let sourceEntries = [];
let collapsedFolders = new Set(state.collapsedFolders || []);
let uploadFolder = null;
let failedFiles = [];
let draggedEntry = null;
let uploading = false;
let treeRefresh = 0;

function rememberSelection() {
  state.selected = [...selectedSources];
  save();
}

function showTree(snapshot, refreshStudy = true) {
  sourceEntries = snapshot.entries;
  const sources = sourceEntries.filter(entry => entry.kind === 'source');
  const previous = JSON.stringify([...selectedSources]);
  const hadSources = sourceNames.size > 1;
  sourceNames.clear();
  for (const entry of sources) sourceNames.set(entry.id, entry.name);
  for (const id of selectedSources) if (!sourceNames.has(id)) selectedSources.delete(id);
  if (snapshot.added || (!hadSources && state.selected === undefined)) {
    for (const entry of sources) if (!snapshot.added || snapshot.added === entry.id) selectedSources.add(entry.id);
  }
  rememberSelection();
  document.title = $('title').textContent = snapshot.name;
  renderTree();
  if (refreshStudy || previous !== JSON.stringify([...selectedSources])) render();
}

async function editTree(action, values, message) {
  try {
    const sequence = ++treeRefresh;
    const result = await spaceRequest('/' + spaceId, {action, ...values});
    if (sequence !== treeRefresh) return;
    showTree(result, action === 'delete');
    if (action === 'delete') refreshLibraries();
    $('sourceStatus').textContent = message;
  } catch (error) { $('sourceStatus').textContent = error.message; }
}

async function refreshTree() {
  try {
    const sequence = ++treeRefresh;
    const result = await spaceRequest('/' + spaceId);
    if (sequence === treeRefresh) showTree(result);
  } catch (error) { $('sourceStatus').textContent = error.message; }
}

async function addTreeFolder(parent = null) {
  const name = await askName('Новая папка');
  if (name !== null) {
    if (parent) collapsedFolders.delete(parent);
    await editTree('folder', {name, parent}, 'Папка создана.');
  }
}

function chooseUpload(parent = null) {
  uploadFolder = parent;
  panel('sources');
  $('sourceFiles').click();
}

async function uploadTreeFiles(files, parent) {
  if (uploading || !files.length) return;
  uploading = true;
  $('addSource').disabled = true;
  $('retrySource').hidden = true;
  failedFiles = [];
  const errors = [];
  let count = 0;
  for (const file of files) {
    $('sourceStatus').textContent = 'Загрузка: ' + file.name;
    try {
      treeRefresh++;
      const snapshot = await uploadSpaceFile(spaceId, file, parent, () => {
        $('sourceStatus').textContent = 'Извлекаем текст: ' + file.name;
      });
      if (parent) collapsedFolders.delete(parent);
      showTree(snapshot);
      count++;
    } catch (error) {
      failedFiles.push(file);
      errors.push(file.name + ' · ' + error.message);
    }
  }
  uploadFolder = parent;
  $('sourceStatus').textContent = [count ? 'Добавлено: ' + count + '.' : '', ...errors].filter(Boolean).join(' ');
  $('retrySource').hidden = !failedFiles.length;
  refreshLibraries();
  $('addSource').disabled = false;
  uploading = false;
}

function validTarget(entryId, target) {
  let ancestor = target;
  while (ancestor) {
    if (ancestor === entryId) return false;
    ancestor = sourceEntries.find(item => item.id === ancestor)?.parent;
  }
  return true;
}

function moveTreeEntry(entry) {
  const destinations = document.createElement('select');
  const option = (id, name) => { add(destinations, 'option', name).value = id || ''; };
  option(null, 'Корневой раздел');
  function visit(parent, indent) {
    for (const folder of sourceEntries.filter(row => row.kind === 'folder' && row.parent === parent)) {
      if (!validTarget(entry.id, folder.id)) continue;
      option(folder.id, indent + folder.name);
      visit(folder.id, indent + '　');
    }
  }
  visit(null, '');
  destinations.value = entry.parent || '';
  spaceDialog('Переместить «' + entry.name + '»', 'Папка назначения', [['save', 'Переместить']], destinations)
    .then(target => { if (target !== null) editTree('move', {id: entry.id, parent: target || null}, 'Расположение сохранено.'); });
}

async function deleteTreeEntry(entry) {
  const hasChildren = sourceEntries.some(row => row.parent === entry.id);
  const choices = hasChildren ? [['keep', 'Перенести содержимое в корень'], ['delete', 'Удалить с содержимым']] : [['delete', 'Удалить']];
  const contents = await spaceDialog('Удалить «' + entry.name + '»?',
    hasChildren ? 'Выберите, куда поместить вложенные папки и источники.' : 'Элемент будет удалён из пространства.', choices);
  if (contents) {
    $('sourcePreview').hidden = true;
    previewRequest++;
    await editTree('delete', {id: entry.id, contents}, 'Элемент удалён.');
  }
}

async function openTreeSource(entry, trigger) {
  const request = ++previewRequest;
  const preview = previewContainer(entry.name);
  preview.trigger = trigger;
  const url = '/api/spaces/' + spaceId + '/files/' + entry.id;
  const original = add(preview, 'a', 'Открыть оригинал');
  Object.assign(original, {href: url, target: '_blank', rel: 'noopener'});
  if (entry.ext === '.pdf') {
    const frame = add(preview, 'iframe');
    Object.assign(frame, {title: entry.name, src: url});
    return;
  }
  const loading = add(preview, 'p', 'Читаем текст…');
  try {
    const response = await spaceRequest('/' + spaceId + '/files/' + entry.id + '/text');
    if (request !== previewRequest) return;
    loading.remove();
    add(preview, 'pre', response.text);
  } catch (error) {
    if (request === previewRequest) loading.textContent = error.message;
  }
}

function treeMenu(row, entry) {
  const menu = details(row, '⋯', 'treeMenu');
  const trigger = menu.firstElementChild;
  trigger.setAttribute('aria-label', 'Действия · ' + entry.name);
  menu.addEventListener('toggle', () => {
    if (menu.open) for (const other of $('localSources').querySelectorAll('.treeMenu[open]')) if (other !== menu) other.open = false;
  });
  const actions = add(menu, 'div', '', 'treeMenuActions');
  const action = (label, run) => button(actions, label, () => { menu.open = false; trigger.focus(); run(trigger); });
  if (entry.kind === 'folder') {
    action('Добавить источник', () => chooseUpload(entry.id));
    action('Создать вложенную папку', () => addTreeFolder(entry.id));
  } else action('Открыть', trigger => openTreeSource(entry, trigger));
  action('Переименовать', async () => {
    const name = await askName('Переименовать', entry.name);
    if (name !== null) await editTree('rename', {id: entry.id, name}, 'Название сохранено.');
  });
  action('Переместить в папку', () => moveTreeEntry(entry));
  action('Удалить', () => deleteTreeEntry(entry));
}

function treeDrop(row, target, expand) {
  let hovered;
  function clear() {
    clearTimeout(hovered);
    hovered = undefined;
    delete row.dataset.drop;
  }
  row.ondragover = event => {
    const files = event.dataTransfer.types.includes('Files');
    if (!draggedEntry && !files) return;
    event.preventDefault();
    event.stopPropagation();
    const allowed = files ? !uploading : validTarget(draggedEntry.id, target);
    row.dataset.drop = allowed ? 'allowed' : 'invalid';
    event.dataTransfer.dropEffect = allowed ? (files ? 'copy' : 'move') : 'none';
    if (allowed && expand && !hovered) hovered = setTimeout(expand, 600);
  };
  row.ondragleave = event => { if (!row.contains(event.relatedTarget)) clear(); };
  row.ondragend = clear;
  row.ondrop = event => {
    event.preventDefault();
    event.stopPropagation();
    clear();
    const files = Array.from(event.dataTransfer.files);
    if (files.length) return uploadTreeFiles(files, target);
    if (draggedEntry && validTarget(draggedEntry.id, target) && draggedEntry.parent !== target) {
      editTree('move', {id: draggedEntry.id, parent: target}, 'Расположение сохранено.');
    }
  };
}

const courseBuilds = new Map(Object.entries(state.courseBuilds || {}));
const pollingBuilds = new Set();

function showCourseBuild(entryId, panel, build = courseBuilds.get(entryId)) {
  if (!panel) return;
  panel.replaceChildren();
  if (build?.state === 'ready' && /^up_[a-f0-9]+\/index\.html$/.test(build.course)) {
    add(panel, 'a', 'Открыть курс').href = '/' + build.course;
    return;
  }
  if (build && ['starting', 'queued', 'running'].includes(build.state)) {
    const percent = build.progress?.percent ?? 0;
    const meter = add(panel, 'progress');
    meter.max = 100;
    meter.value = percent;
    meter.setAttribute('aria-label', 'Готовность курса');
    const eta = build.progress?.eta_sec;
    add(panel, 'small', percent + '% · ' + build.stage);
    if (build.state === 'running' && !build.connectionError) {
      add(panel, 'small', Number.isFinite(eta)
        ? 'Осталось около ' + Math.max(1, Math.ceil(eta / 60)) + ' мин'
        : 'Оцениваем время…');
    }
    return;
  }
  if (build?.error) add(panel, 'small', build.error);
  button(panel, build?.error ? 'Повторить сборку' : 'Собрать курс', async () => {
    if (['starting', 'queued', 'running'].includes(courseBuilds.get(entryId)?.state)) return;
    courseBuilds.set(entryId, {state: 'starting', stage: 'Отправляем запрос'});
    showCourseBuild(entryId, $('build-' + entryId));
    try {
      const result = await spaceRequest('/' + spaceId + '/build', {entry: entryId});
      updateCourseBuild(entryId, result);
      pollCourseBuild(entryId, result.job);
    } catch (error) {
      updateCourseBuild(entryId, {state: 'error', error: error.message});
      $('build-' + entryId)?.querySelector('button')?.focus();
    }
  });
}

function updateCourseBuild(entryId, build) {
  courseBuilds.set(entryId, build);
  (state.courseBuilds ||= {})[entryId] = {
    job: build.job, state: build.state, stage: build.stage, progress: build.progress,
    course: build.course, error: build.error
  };
  save();
  showCourseBuild(entryId, $('build-' + entryId));
}

function pollCourseBuild(entryId, job) {
  if (!job || pollingBuilds.has(job)) return;
  pollingBuilds.add(job);
  async function poll() {
    try {
      const response = await fetch('/api/build/' + encodeURIComponent(job),
        {cache: 'no-store', signal: AbortSignal.timeout(10000)});
      if (response.status === 404) {
        updateCourseBuild(entryId, {state: 'error', error: 'Сборка прервана. Запусти её снова.'});
        pollingBuilds.delete(job);
        return;
      }
      if (!response.ok) throw Error('Статус недоступен');
      const build = await response.json();
      updateCourseBuild(entryId, build);
      if (build.state === 'ready' || build.state === 'error') {
        pollingBuilds.delete(job);
        return;
      }
    } catch {
      const build = courseBuilds.get(entryId);
      showCourseBuild(entryId, $('build-' + entryId),
        {...build, stage: 'Связь прервалась. Повторяем запрос…', connectionError: true});
    }
    setTimeout(poll, 4000);
  }
  setTimeout(poll, 4000);
}

function renderTree() {
  const tree = $('localSources');
  tree.replaceChildren();
  const root = add(tree, 'div', '⌂ Корневой раздел', 'treeRoot');
  treeDrop(root, null);
  if (!sourceEntries.length) add(tree, 'p', 'Перетащите файлы сюда или добавьте папку.', 'muted');
  const byParent = new Map();
  for (const entry of sourceEntries) {
    if (!byParent.has(entry.parent)) byParent.set(entry.parent, []);
    byParent.get(entry.parent).push(entry);
  }
  function build(parent, parentId) {
    const list = add(parent, 'ul', '', 'sourceTree');
    for (const entry of byParent.get(parentId) || []) {
      const item = add(list, 'li');
      const row = add(item, 'div', '', 'treeRow');
      row.dataset.entry = entry.id;
      row.draggable = true;
      row.ondragstart = event => {
        draggedEntry = entry;
        row.dataset.dragging = 'true';
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', entry.id);
      };
      row.addEventListener('dragend', () => {
        draggedEntry = null;
        delete row.dataset.dragging;
        for (const drop of tree.querySelectorAll('[data-drop]')) delete drop.dataset.drop;
      });
      if (entry.kind === 'folder') {
        const group = add(item, 'div');
        function sync(open) {
          group.hidden = !open;
          folder.setAttribute('aria-expanded', String(open));
          folder.firstElementChild.textContent = open ? '▾' : '▸';
          if (open) collapsedFolders.delete(entry.id);
          else collapsedFolders.add(entry.id);
          state.collapsedFolders = [...collapsedFolders];
          save();
        }
        const folder = button(row, '', () => sync(group.hidden), 'treeFolder');
        add(folder, 'span').setAttribute('aria-hidden', 'true');
        add(folder, 'span', entry.name);
        sync(!collapsedFolders.has(entry.id));
        treeDrop(row, entry.id, () => sync(true));
        treeMenu(row, entry);
        if (byParent.has(entry.id)) build(group, entry.id);
      } else {
        const label = add(row, 'div', '', 'treeSource');
        sourceRow(label, entry.id, entry.name, entry.ext.slice(1).toUpperCase() + ' · ' + entry.unit_count + ' фрагм.');
        const course = add(label, 'div', '', 'sourceBuild');
        course.id = 'build-' + entry.id;
        course.setAttribute('aria-live', 'polite');
        showCourseBuild(entry.id, course);
        const build = courseBuilds.get(entry.id);
        if (build && ['queued', 'running'].includes(build.state)) pollCourseBuild(entry.id, build.job);

        treeMenu(row, entry);
      }
    }
  }
  build(tree, null);
}

function initSourceTree() {
  $('addFolder').hidden = false;
  $('addFolder').onclick = () => addTreeFolder();
  $('addSource').onclick = () => chooseUpload();
  const retry = button($('sourceStatus').parentElement, 'Повторить загрузку', () => uploadTreeFiles(failedFiles, uploadFolder));
  retry.id = 'retrySource';
  retry.hidden = true;
  $('sourceStatus').after(retry);
  $('sourceFiles').onchange = event => {
    const files = Array.from(event.target.files);
    event.target.value = '';
    uploadTreeFiles(files, uploadFolder);
  };
  treeDrop($('sourcesPanel'), null);
  document.addEventListener('click', event => {
    for (const menu of document.querySelectorAll('.treeMenu[open]')) if (!menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || document.querySelector('dialog[open]')) return;
    for (const menu of document.querySelectorAll('.treeMenu[open]')) {
      menu.open = false;
      menu.firstElementChild.focus();
    }
  });
  window.addEventListener('pageshow', event => { if (event.persisted) refreshTree(); });
  refreshTree();
}
