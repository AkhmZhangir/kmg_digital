'use strict';

function readGeoTheme(fallback) {
  try {
    const stored = localStorage.getItem('geocourse.theme');
    if (stored !== null) return stored === 'dark';
  } catch {}
  return typeof fallback === 'boolean' ? fallback : matchMedia('(prefers-color-scheme: dark)').matches;
}

function writeGeoTheme(dark) {
  try { localStorage.setItem('geocourse.theme', dark ? 'dark' : 'light'); } catch {}
}

function spaceDialog(title, label, choices, field) {
  const dialog = document.createElement('dialog');
  dialog.className = 'spaceDialog';
  const form = document.createElement('form');
  form.method = 'dialog';
  dialog.append(form);
  const heading = document.createElement('h2');
  heading.id = 'spaceDialogTitle';
  heading.textContent = title;
  dialog.setAttribute('aria-labelledby', heading.id);
  form.append(heading);
  const message = document.createElement(field ? 'label' : 'p');
  message.textContent = label;
  if (field) message.append(field);
  form.append(message);
  const footer = document.createElement('div');
  footer.className = 'dialogActions';
  form.append(footer);
  for (const [value, caption] of [['cancel', 'Отмена'], ...choices]) {
    const control = document.createElement('button');
    control.value = value;
    control.textContent = caption;
    control.formNoValidate = value === 'cancel';
    if (value === 'save') control.className = 'primary';
    footer.append(control);
  }
  document.body.append(dialog);
  dialog.showModal();
  (field || footer.firstElementChild).focus();
  return new Promise(resolve => dialog.addEventListener('close', () => {
    const selected = dialog.returnValue;
    dialog.remove();
    resolve(selected && selected !== 'cancel' ? (field ? field.value : selected) : null);
  }, {once: true}));
}

function askName(title, value = '') {
  const field = document.createElement('input');
  field.required = true;
  field.maxLength = 150;
  field.value = value;
  return spaceDialog(title, 'Название', [['save', 'Сохранить']], field);
}

async function spaceRequest(path, data) {
  const options = data ? {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)} : {};
  const result = await fetch('/api/spaces' + path, {...options, cache: 'no-store'});
  const payload = await result.json();
  if (!result.ok) throw Error(payload.error?.message || 'Не удалось сохранить изменения.');
  return payload;
}

function uploadSpaceFile(space, file, parent, processing) {
  const query = new URLSearchParams({name: file.name});
  if (parent) query.set('parent', parent);
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open('POST', '/api/spaces/' + space + '/upload?' + query);
    request.setRequestHeader('Content-Type', 'application/octet-stream');
    request.responseType = 'json';
    request.upload.addEventListener('load', processing);
    request.addEventListener('load', () => {
      if (request.status === 201 && request.response) resolve(request.response);
      else reject(Error(request.response?.error?.message || 'Не удалось загрузить документ.'));
    });
    request.addEventListener('error', () => reject(Error('Соединение прервалось. Повторите загрузку.')));
    request.send(file);
  });
}

async function createLibrary() {
  const name = await askName('Новая библиотека');
  if (name === null) return;
  const library = await spaceRequest('', {name});
  location.assign('/spaces/' + library.id + '?panel=sources');
}
