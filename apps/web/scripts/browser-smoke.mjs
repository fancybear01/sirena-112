import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const scriptDirectory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(scriptDirectory, '..');
const screenshotDirectory = path.join(webRoot, 'docs', 'screenshots', 'issue-94');
const webPort = 4174;
const apiPort = 18080;
const debugPort = 19222;
const origin = `http://127.0.0.1:${webPort}`;
const apiOrigin = `http://127.0.0.1:${apiPort}`;

const users = {
  admin: { id: 'admin-1', username: 'admin', displayName: 'Администратор', role: 'ADMIN', groupId: null },
  teacher: { id: 'teacher-1', username: 'teacher', displayName: 'Преподаватель', role: 'TEACHER', groupId: 'group-1' },
  student: { id: 'student-1', username: 'student', displayName: 'Обучающийся', role: 'STUDENT', groupId: 'group-1' },
};

const approvedScenario = {
  id: '80c14c89-f2b7-527a-bd6f-268cdc3d4a11',
  version: 3,
  title: 'Задымление в мусоропроводе',
  category: 'FIRE',
  difficulty: 'BASIC',
  profile: 'Учебная карточка классификатора 1050602.',
  timeLimitSeconds: 30,
  groundTruth: {},
  rubric: { criteria: [] },
};

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      try { resolve(raw ? JSON.parse(raw) : {}); } catch (error) { reject(error); }
    });
    request.on('error', reject);
  });
}

function currentUser(request) {
  const match = /(?:^|;\s*)sirena_role=([^;]+)/.exec(request.headers.cookie ?? '');
  return match ? users[decodeURIComponent(match[1])] ?? null : null;
}

function createMockApi() {
  return createServer(async (request, response) => {
    const url = new URL(request.url ?? '/', apiOrigin);
    response.setHeader('Access-Control-Allow-Origin', origin);
    response.setHeader('Access-Control-Allow-Credentials', 'true');
    response.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-XSRF-TOKEN');
    response.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, PATCH, OPTIONS');

    if (request.method === 'OPTIONS') {
      response.writeHead(204).end();
      return;
    }

    const json = (status, body, headers = {}) => {
      response.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', ...headers });
      response.end(body === undefined ? undefined : JSON.stringify(body));
    };

    try {
      if (url.pathname === '/api/auth/csrf') {
        json(200, { token: 'browser-smoke-token', headerName: 'X-XSRF-TOKEN' });
        return;
      }
      if (url.pathname === '/api/auth/login' && request.method === 'POST') {
        const body = await readBody(request);
        const user = users[String(body.username ?? '').toLowerCase()];
        if (!user) {
          json(401, { message: 'Неверный логин или пароль.' });
          return;
        }
        json(200, user, { 'Set-Cookie': `sirena_role=${encodeURIComponent(user.username)}; Path=/; SameSite=Lax` });
        return;
      }
      if (url.pathname === '/api/auth/logout' && request.method === 'POST') {
        json(204, undefined, { 'Set-Cookie': 'sirena_role=; Path=/; Max-Age=0; SameSite=Lax' });
        return;
      }
      if (url.pathname === '/api/auth/me') {
        const user = currentUser(request);
        json(user ? 200 : 401, user ?? { message: 'Требуется вход.' });
        return;
      }

      const user = currentUser(request);
      if (!user) {
        json(401, { message: 'Требуется вход.' });
        return;
      }

      if (url.pathname === '/api/admin/groups' && request.method === 'GET') {
        json(200, [{ id: 'group-1', name: 'Учебная группа' }]);
      } else if (url.pathname === '/api/admin/users' && request.method === 'GET') {
        json(200, [users.admin, users.teacher, users.student].map((item) => ({ ...item, locked: false, enabled: true })));
      } else if (url.pathname === '/api/teacher/scenarios/workflow' && request.method === 'GET') {
        json(200, []);
      } else if (url.pathname === '/api/teacher/scenarios' && request.method === 'GET') {
        json(200, [approvedScenario]);
      } else if (url.pathname === '/api/teacher/students' && request.method === 'GET') {
        json(200, [users.student]);
      } else if (url.pathname === '/api/teacher/history' && request.method === 'GET') {
        json(200, { summary: { assigned: 1, completed: 1, averagePercent: 100 }, attempts: [] });
      } else if (url.pathname === '/api/student/history' && request.method === 'GET') {
        json(200, { summary: { assigned: 1, completed: 1, averagePercent: 100 }, attempts: [] });
      } else {
        json(404, { message: 'Маршрут browser smoke не настроен.' });
      }
    } catch (error) {
      json(500, { message: error instanceof Error ? error.message : String(error) });
    }
  });
}

class CdpClient {
  constructor(webSocketUrl) {
    this.webSocketUrl = webSocketUrl;
    this.sequence = 0;
    this.pending = new Map();
  }

  async connect() {
    this.socket = new WebSocket(this.webSocketUrl);
    this.socket.addEventListener('message', (event) => {
      const message = JSON.parse(String(event.data));
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    });
    await new Promise((resolve, reject) => {
      this.socket.addEventListener('open', resolve, { once: true });
      this.socket.addEventListener('error', reject, { once: true });
    });
  }

  send(method, params = {}) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (result.exceptionDetails) throw new Error(result.exceptionDetails.text ?? 'Ошибка JavaScript в браузере');
    return result.result.value;
  }

  async waitFor(expression, message, timeoutMs = 12_000) {
    const startedAt = Date.now();
    while (Date.now() - startedAt < timeoutMs) {
      if (await this.evaluate(`Boolean(${expression})`)) return;
      await delay(100);
    }
    throw new Error(`Тайм-аут: ${message}`);
  }

  async navigate(pathname) {
    await this.send('Page.navigate', { url: `${origin}${pathname}` });
    await this.waitFor("document.readyState === 'complete'", `страница ${pathname} не загрузилась`);
  }

  async setViewport(width, height) {
    await this.send('Emulation.setDeviceMetricsOverride', {
      width,
      height,
      screenWidth: width,
      screenHeight: height,
      deviceScaleFactor: 1,
      mobile: width <= 600,
    });
  }

  async screenshot(name) {
    const result = await this.send('Page.captureScreenshot', {
      format: 'png',
      fromSurface: true,
      captureBeyondViewport: false,
    });
    await writeFile(path.join(screenshotDirectory, name), Buffer.from(result.data, 'base64'));
  }

  async resetScroll() {
    await this.evaluate(`new Promise((resolve) => {
      scrollTo(0, 0);
      requestAnimationFrame(() => requestAnimationFrame(resolve));
    })`);
    await this.waitFor('scrollY === 0', 'страница не вернулась к началу');
  }

  async close() {
    this.socket?.close();
  }
}

async function waitForHttp(url, label, timeoutMs = 15_000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The process is still starting.
    }
    await delay(150);
  }
  throw new Error(`${label} не запустился за ${timeoutMs} мс`);
}

async function waitForChrome() {
  const startedAt = Date.now();
  while (Date.now() - startedAt < 15_000) {
    try {
      const targets = await fetch(`http://127.0.0.1:${debugPort}/json/list`).then((response) => response.json());
      const page = targets.find((target) => target.type === 'page');
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {
      // Chrome is still starting.
    }
    await delay(150);
  }
  throw new Error('Chrome DevTools не стал доступен');
}

async function login(client, username, expectedPath, expectedHeading) {
  await client.navigate('/login');
  await client.waitFor("document.body.innerText.includes('Вход в систему')", 'форма входа не появилась');
  await client.evaluate(`(() => {
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    const username = document.querySelector('input[autocomplete="username"]');
    const password = document.querySelector('input[autocomplete="current-password"]');
    setValue.call(username, ${JSON.stringify(username)});
    username.dispatchEvent(new Event('input', { bubbles: true }));
    setValue.call(password, 'browser-smoke-password');
    password.dispatchEvent(new Event('input', { bubbles: true }));
    document.querySelector('form').requestSubmit();
  })()`);
  await client.waitFor(`location.pathname === ${JSON.stringify(expectedPath)} && document.body.innerText.includes(${JSON.stringify(expectedHeading)})`, `${username} не вошёл в ${expectedPath}`);
}

async function assertLayout(client, label) {
  const result = await client.evaluate(`(() => {
    const viewportWidth = document.documentElement.clientWidth;
    const overflow = document.documentElement.scrollWidth - viewportWidth;
    const interactive = [...document.querySelectorAll('button, input, textarea, [role="button"]')]
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      });
    const outside = interactive.filter((element) => {
      const rect = element.getBoundingClientRect();
      return rect.left < -1 || rect.right > viewportWidth + 1;
    }).map((element) => element.getAttribute('aria-label') || element.textContent.trim() || element.tagName);
    return { overflow, outside };
  })()`);
  if (result.overflow > 1 || result.outside.length) {
    throw new Error(`${label}: горизонтальное переполнение ${result.overflow}px; вне viewport: ${result.outside.join(', ')}`);
  }
}

async function assertSubmitAvailable(client) {
  const result = await client.evaluate(`(() => {
    const button = [...document.querySelectorAll('button')].find((item) => item.textContent.includes('Отправить на оценку'));
    if (!button) return { found: false };
    const rect = button.getBoundingClientRect();
    const top = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
    return {
      found: true,
      visible: rect.top >= 0 && rect.bottom <= innerHeight && rect.left >= 0 && rect.right <= innerWidth,
      reachable: top === button || button.contains(top),
    };
  })()`);
  if (!result.found || !result.visible || !result.reachable) {
    throw new Error(`Мобильная отправка карточки недоступна: ${JSON.stringify(result)}`);
  }
}

function completedStudentState() {
  const sessionId = 'a13e08ea-220f-458a-95f6-95b7c3a3f14c';
  const scenarioId = approvedScenario.id;
  const endedAt = new Date().toISOString();
  const startedAt = new Date(Date.now() - 24_000).toISOString();
  const services = [
    { id: 'MCHS', displayName: 'Служба 101 (МЧС)', reasons: [{ ruleId: '1050602', message: 'Маршрутизация по классификатору.', matchedInputIds: [] }] },
    { id: 'GKH', displayName: 'Городское хозяйство', reasons: [{ ruleId: '1050602', message: 'Маршрутизация по классификатору.', matchedInputIds: [] }] },
  ];
  const input = {
    caller: { fullName: 'Учебный заявитель', phoneNumbers: [{ value: '+7 900 000-00-00', type: 'MOBILE' }], callerType: 'RESIDENT' },
    incident: {
      selectedSignIds: ['sign.68eaae1dc9472ce9', 'sign.8795ab4a7bb0d66a', 'sign.8b0cf230ebb8ba99'],
      answers: [
        'routing.culture-listed-facility', 'routing.evacuation', 'routing.medical-help', 'routing.no-access',
        'routing.offence', 'routing.threat-to-people', 'routing.traffic-blocked',
      ].map((questionId) => ({ questionId, optionIds: ['NO'] })).concat([
        { questionId: 'routing.victims-status', optionIds: ['NONE'] },
      ]),
    },
    address: { displayAddress: 'Учебная улица, дом 1' },
    description: 'Учебный пример: задымление в мусоропроводе.',
    victims: { present: false, count: null, threatToPeople: false },
    facts: {},
  };
  const calculation = {
    status: 'RESOLVED', classifierVersion: '046-2024-11-15', classifierCode: '1050602',
    incidentType: 'задымление: мусоропровод', ekp35IncidentType: 'пожар: мусоропровод',
    responseScenarioCode: '1_9', responseScenarioStatus: 'CODE', mainServices: services.slice(0, 1),
    services, missingInputIds: [], explanations: ['Карточка рассчитана Core по классификатору.'],
  };
  const report = {
    sessionId, score: 100, maxScore: 100, passed: true,
    criteria: [
      { code: 'SIGNS', passed: true, points: 25, maxPoints: 25, message: 'Признаки соответствуют эталону.' },
      { code: 'ANSWERS', passed: true, points: 25, maxPoints: 25, message: 'Ответы соответствуют сценарию.' },
      { code: 'SERVICES', passed: true, points: 25, maxPoints: 25, message: 'Службы рассчитаны Core.' },
      { code: 'ADDRESS', passed: true, points: 25, maxPoints: 25, message: 'Адрес зафиксирован.' },
    ],
    errors: [],
    recommendations: ['Сохраняйте порядок: признаки, вопросы, адрес и сведения о пострадавших.'],
  };
  return { sessionId, scenarioId, startedAt, endedAt, timeLimitSeconds: 30, cardRevision: 3, card: { input, calculation }, report };
}

async function main() {
  await mkdir(screenshotDirectory, { recursive: true });
  const chromeCandidates = [
    process.env.SIRENA_CHROME_PATH,
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    '/usr/bin/google-chrome',
    '/usr/bin/chromium',
  ].filter(Boolean);
  const chromePath = chromeCandidates.find((candidate) => existsSync(candidate));
  if (!chromePath) throw new Error('Google Chrome не найден. Укажите SIRENA_CHROME_PATH.');

  const apiServer = createMockApi();
  await new Promise((resolve, reject) => {
    apiServer.once('error', reject);
    apiServer.listen(apiPort, '127.0.0.1', resolve);
  });

  const vite = spawn(process.execPath, [path.join(webRoot, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1', '--port', String(webPort), '--strictPort'], {
    cwd: webRoot,
    env: { ...process.env, VITE_API_MODE: 'mock', VITE_API_BASE_URL: apiOrigin },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  let viteLog = '';
  vite.stdout.on('data', (chunk) => { viteLog = `${viteLog}${chunk}`.slice(-4000); });
  vite.stderr.on('data', (chunk) => { viteLog = `${viteLog}${chunk}`.slice(-4000); });

  const chromeProfile = await mkdtemp(path.join(tmpdir(), 'sirena-browser-smoke-'));
  const chrome = spawn(chromePath, [
    '--headless=new',
    '--disable-gpu',
    '--disable-extensions',
    '--disable-background-networking',
    '--disable-component-update',
    '--no-first-run',
    '--no-default-browser-check',
    `--user-data-dir=${chromeProfile}`,
    `--remote-debugging-port=${debugPort}`,
    '--window-size=1920,1080',
    'about:blank',
  ], { stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true });
  let chromeLog = '';
  chrome.stderr.on('data', (chunk) => { chromeLog = `${chromeLog}${chunk}`.slice(-4000); });

  let client;
  try {
    await waitForHttp(origin, 'Vite');
    client = new CdpClient(await waitForChrome());
    await client.connect();
    await Promise.all([
      client.send('Page.enable'),
      client.send('Runtime.enable'),
      client.send('Network.enable'),
      client.send('Network.setCacheDisabled', { cacheDisabled: true }),
    ]);

    const version = await client.send('Browser.getVersion');
    await client.setViewport(390, 844);
    await client.send('Network.clearBrowserCookies');
    await client.navigate('/admin');
    await client.waitFor("location.pathname === '/login' && document.body.innerText.includes('Вход в систему')", 'защищённый direct URL не вернул на вход');
    await assertLayout(client, 'Вход 390×844');
    await client.screenshot('login-390x844.png');

    await client.evaluate("document.querySelector('input[autocomplete=\"username\"]').focus()");
    await client.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    await client.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9 });
    const focusedAutocomplete = await client.evaluate('document.activeElement?.getAttribute(\'autocomplete\')');
    if (focusedAutocomplete !== 'current-password') throw new Error('Клавиша Tab не переводит фокус с логина на пароль.');

    await login(client, 'admin', '/admin', 'Пользователи и группы');
    await assertLayout(client, 'Администратор 390×844');
    await client.screenshot('admin-390x844.png');
    await client.send('Page.reload', { ignoreCache: true });
    await client.waitFor("location.pathname === '/admin' && document.body.innerText.includes('Пользователи и группы')", 'страница администратора не восстановилась после reload');
    await client.navigate('/student');
    await client.waitFor("location.pathname === '/admin'", 'ADMIN получил чужой маршрут STUDENT');

    await client.send('Network.clearBrowserCookies');
    await client.setViewport(1366, 768);
    await login(client, 'teacher', '/teacher', 'Сценарии');
    await client.waitFor("!document.body.innerText.includes('Загружаем версии сценариев')", 'панель сценариев преподавателя не загрузилась');
    await assertLayout(client, 'Преподаватель 1366×768');
    await client.screenshot('teacher-1366x768.png');
    await client.send('Page.reload', { ignoreCache: true });
    await client.waitFor("location.pathname === '/teacher' && document.body.innerText.includes('Сценарии')", 'страница преподавателя не восстановилась после reload');
    await client.navigate('/admin');
    await client.waitFor("location.pathname === '/teacher'", 'TEACHER получил чужой маршрут ADMIN');
    await client.setViewport(390, 844);
    await client.resetScroll();
    await assertLayout(client, 'Преподаватель 390×844');
    await client.screenshot('teacher-390x844.png');

    await client.send('Network.clearBrowserCookies');
    await client.setViewport(1920, 1080);
    await login(client, 'student', '/student', 'Моё задание');
    await assertLayout(client, 'Обучающийся 1920×1080');
    await client.screenshot('student-1920x1080.png');
    await client.send('Page.reload', { ignoreCache: true });
    await client.waitFor("location.pathname === '/student' && document.body.innerText.includes('Моё задание')", 'страница обучающегося не восстановилась после reload');
    await client.navigate('/teacher');
    await client.waitFor("location.pathname === '/student' && document.body.innerText.includes('Моё задание')", 'STUDENT получил чужой маршрут TEACHER');
    await client.setViewport(390, 844);
    await client.resetScroll();
    await assertLayout(client, 'Обучающийся 390×844');
    await assertSubmitAvailable(client);
    await client.screenshot('student-390x844.png');

    await client.evaluate(`localStorage.setItem('sirena-112:student-assignment', ${JSON.stringify(JSON.stringify(completedStudentState()))})`);
    await client.send('Page.reload', { ignoreCache: true });
    await client.waitFor("location.pathname === '/student' && document.body.innerText.includes('Результат задания')", 'мобильный отчёт не загрузился');
    await client.evaluate("document.querySelector('.student-report')?.scrollIntoView()");
    await assertLayout(client, 'Отчёт 390×844');
    await client.screenshot('student-report-390x844.png');

    console.log(`PASS: ${version.product} на ${version.userAgent}`);
    console.log('PASS: роли ADMIN/TEACHER/STUDENT, direct URL, reload, клавиатурный фокус и мобильная отправка');
    console.log(`PASS: скриншоты сохранены в ${screenshotDirectory}`);
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.message : String(error)}\nVite:\n${viteLog}\nChrome:\n${chromeLog}`);
  } finally {
    await client?.close();
    chrome.kill();
    vite.kill();
    await new Promise((resolve) => apiServer.close(resolve));
    await delay(300);
    await rm(chromeProfile, { recursive: true, force: true, maxRetries: 3, retryDelay: 200 }).catch(() => undefined);
  }
}

await main();
