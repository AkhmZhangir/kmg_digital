'use strict';

let sourceEntries = [];
let collapsedFolders = new Set(state.collapsedFolders || []);
let uploadFolder = null;
let failedUpload;
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
    if (action === 'delete' || values.destination) refreshLibraries();
    if (values.destination && $('sourcePreview').previewEntry === values.id) {
      previewRequest++;
      $('sourcePreview').hidden = true;
    }
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

async function uploadTreeFiles(files, parent, destination = spaceId) {
  if (uploading || !files.length) return;
  uploading = true;
  $('addSource').disabled = true;
  $('retrySource').hidden = true;
  const failed = [];
  const errors = [];
  let count = 0;
  for (const file of files) {
    $('sourceStatus').textContent = 'Загрузка: ' + file.name;
    try {
      treeRefresh++;
      const snapshot = await uploadSpaceFile(destination, file, parent, () => {
        $('sourceStatus').textContent = 'Извлекаем текст: ' + file.name;
      });
      if (destination === spaceId) {
        if (parent) collapsedFolders.delete(parent);
        showTree(snapshot);
      }
      count++;
    } catch (error) {
      failed.push(file);
      errors.push(file.name + ' · ' + error.message);
    }
  }
  failedUpload = {files: failed, parent, destination};
  $('sourceStatus').textContent = [count ? 'Добавлено: ' + count + '.' : '', ...errors].filter(Boolean).join(' ');
  $('retrySource').hidden = !failed.length;
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
  if (entry.kind === 'source' && libraryTargets.some(target => target.id !== spaceId)) {
    const libraries = add(destinations, 'optgroup');
    libraries.label = 'Другие библиотеки';
    for (const target of libraryTargets.filter(target => target.id !== spaceId)) {
      add(libraries, 'option', target.name).value = 'space/' + target.id;
    }
  }
  destinations.value = entry.parent || '';
  spaceDialog('Переместить «' + entry.name + '»', 'Куда переместить', [['save', 'Переместить']], destinations)
    .then(target => {
      if (target === null) return;
      if (target.startsWith('space/')) {
        const library = libraryTargets.find(library => library.id === target.slice(6));
        if (library) moveToLibrary(entry, library);
      } else editTree('move', {id: entry.id, parent: target || null}, 'Расположение сохранено.');
    });
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
  preview.previewEntry = entry.id;
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
  action(entry.kind === 'source' ? 'Переместить…' : 'Переместить в папку', () => moveTreeEntry(entry));
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

function moveToLibrary(entry, library) {
  const build = knownCourseBuild(entry.id);
  if (build?.job) rememberCourseBuild(entry.id, build);
  return editTree('move', {id: entry.id, destination: library.id},
    'Документ перемещён: ' + library.name + '.');
}

function libraryDrop(link, target) {
  link.ondragover = event => {
    const files = event.dataTransfer.types.includes('Files');
    if (!files && !draggedEntry) return;
    event.preventDefault();
    event.stopPropagation();
    const allowed = files ? !uploading : draggedEntry.kind === 'source';
    link.dataset.drop = allowed ? 'allowed' : 'invalid';
    event.dataTransfer.dropEffect = allowed ? (files ? 'copy' : 'move') : 'none';
  };
  link.ondragleave = event => {
    if (!link.contains(event.relatedTarget)) delete link.dataset.drop;
  };
  link.ondrop = event => {
    const files = Array.from(event.dataTransfer.files);
    if (!files.length && !draggedEntry) return;
    event.preventDefault();
    event.stopPropagation();
    delete link.dataset.drop;
    if (files.length) uploadTreeFiles(files, null, target.id);
    else if (draggedEntry.kind === 'source') moveToLibrary(draggedEntry, target);
  };
}

const courseBuilds = new Map(Object.entries(state.courseBuilds || {}));
const pollingBuilds = new Set();

function knownCourseBuild(entryId) {
  const current = courseBuilds.get(entryId);
  if (current?.state === 'starting') return current;
  try {
    return JSON.parse(localStorage.getItem('geocourse.build.' + entryId)) || current;
  } catch {
    return current;
  }
}

function rememberCourseBuild(entryId, build) {
  courseBuilds.set(entryId, build);
  try {
    const {job, state, stage, progress, course, error, pages, needs_review} = build;
    localStorage.setItem('geocourse.build.' + entryId, JSON.stringify({job, state, stage, progress, course, error, pages, needs_review}));
  } catch {}
}

function chooseCourseRange(entry) {
  const dialog = $('buildDialog');
  const from = $('buildFrom');
  const to = $('buildTo');
  const confirm = $('buildConfirm');
  const preview = $('buildPreview');
  const pdf = $('buildPdf');
  const status = $('buildRangeStatus');
  const filePath = '/' + spaceId + '/files/' + entry.id;
  let request = 0;
  let delay;
  let closed = false;

  $('buildFile').textContent = entry.name;
  $('buildLimits').textContent = '';
  status.textContent = 'Загружаем список страниц…';
  from.value = to.value = '';
  from.disabled = to.disabled = confirm.disabled = preview.hidden = pdf.hidden = true;
  dialog.returnValue = 'cancel';
  $('buildCancel').onclick = () => dialog.close('cancel');
  dialog.showModal();

  async function showPreview() {
    const current = ++request;
    const first = from.valueAsNumber, last = to.valueAsNumber;
    if (!from.validity.valid || !to.validity.valid || first > last) {
      status.textContent = 'Проверь начальную и конечную страницу.';
      return;
    }
    status.textContent = 'Готовим предпросмотр…';
    try {
      const query = new URLSearchParams({page_from: first, page_to: last});
      const result = await spaceRequest(filePath + '/build-preview?' + query);
      if (closed || current !== request) return;
      status.textContent = 'Страниц с текстом: ' + result.pages + ' · начало выбранного фрагмента';
      preview.textContent = result.text;
      preview.hidden = false;
      if (entry.ext === '.pdf') {
        pdf.href = '/api/spaces' + filePath + '#page=' + first;
        pdf.hidden = false;
      }
      confirm.disabled = false;
    } catch (error) {
      if (!closed && current === request) status.textContent = error.message;
    }
  }

  from.oninput = to.oninput = () => {
    request++;
    preview.hidden = pdf.hidden = confirm.disabled = true;
    status.textContent = '';
    clearTimeout(delay);
    delay = setTimeout(showPreview, 250);
  };

  spaceRequest(filePath + '/build-preview').then(bounds => {
    if (closed || !dialog.open) return;
    from.min = to.min = bounds.first;
    from.max = to.max = bounds.last;
    from.value = bounds.first;
    to.value = bounds.end;
    from.disabled = to.disabled = false;
    $('buildLimits').textContent = 'Доступно стр. ' + bounds.first + '–' + bounds.last + ' · до ' + bounds.limit + ' страниц с текстом';
    from.focus();
    showPreview();
  }).catch(error => { if (!closed) status.textContent = error.message; });

  return new Promise(resolve => dialog.addEventListener('close', () => {
    closed = true;
    clearTimeout(delay);
    resolve(dialog.returnValue === 'build' && !confirm.disabled
      ? {page_from: from.valueAsNumber, page_to: to.valueAsNumber} : null);
  }, {once: true}));
}

function showCourseBuild(entryId, panel, build = knownCourseBuild(entryId)) {
  if (!panel) return;
  panel.replaceChildren();
  const ready = build?.state === 'ready' && /^up_[a-f0-9]+(?:_p\d+-\d+)?\/index\.html$/.test(build.course);
  if (ready) {
    add(panel, 'a', 'Открыть курс').href = '/' + build.course;
    if (build.needs_review) add(panel, 'small', 'Требует проверки', 'qualityBadge');
  }
  if (build?.pages?.length) add(panel, 'small', 'Стр. ' + build.pages.join('–'), 'muted');
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
  button(panel, ready ? 'Собрать ещё главу' : build?.error ? 'Повторить сборку' : 'Собрать курс', async () => {
    const entry = sourceEntries.find(source => source.id === entryId);
    if (!entry) return;
    const range = await chooseCourseRange(entry);
    if (!range || ['starting', 'queued', 'running'].includes(knownCourseBuild(entryId)?.state)) return;
    courseBuilds.set(entryId, {state: 'starting', stage: 'Отправляем запрос'});
    showCourseBuild(entryId, $('build-' + entryId));
    try {
      const result = await spaceRequest('/' + spaceId + '/build', {entry: entryId, ...range});
      updateCourseBuild(entryId, result);
      pollCourseBuild(entryId, result.job);
    } catch (error) {
      updateCourseBuild(entryId, {state: 'error', error: error.message});
      $('build-' + entryId)?.querySelector('button')?.focus();
    }
  });
}

function updateCourseBuild(entryId, build) {
  rememberCourseBuild(entryId, build);
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
      const build = knownCourseBuild(entryId);
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
  if (!sourceEntries.length) add(tree, 'p', 'Перетащи сюда файлы или добавь папку.', 'muted');
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
        for (const drop of $('sourcesPanel').querySelectorAll('[data-drop]')) delete drop.dataset.drop;
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
        const build = knownCourseBuild(entry.id);
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
  const retry = button($('sourceStatus').parentElement, 'Повторить загрузку', () => {
    if (failedUpload) uploadTreeFiles(failedUpload.files, failedUpload.parent, failedUpload.destination);
  });
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
