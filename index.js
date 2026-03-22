import require$$0$4, { app, session, ipcMain, BrowserWindow, shell, nativeImage, nativeTheme, Tray, Menu, dialog } from "electron";
import path, { join, basename } from "path";
import require$$0, { spawn, execSync } from "child_process";
import os from "os";
import fs, { readFileSync, existsSync, mkdirSync, createWriteStream } from "fs";
import require$$0$1 from "util";
import require$$0$2, { EventEmitter } from "events";
import require$$0$3 from "http";
import require$$1 from "https";
import pkg from "node-machine-id";
import { randomBytes } from "crypto";
import net from "net";
import JSON5 from "json5";
import fs$1 from "fs/promises";
import { readFileSync as readFileSync$1 } from "node:fs";
import { join as join$1 } from "node:path";
import { InstallReporter } from "@guanjia-openclaw/report/server";
const is = {
  dev: !app.isPackaged
};
const platform = {
  isWindows: process.platform === "win32",
  isMacOS: process.platform === "darwin",
  isLinux: process.platform === "linux"
};
const electronApp = {
  setAppUserModelId(id) {
    if (platform.isWindows)
      app.setAppUserModelId(is.dev ? process.execPath : id);
  },
  setAutoLaunch(auto) {
    if (platform.isLinux)
      return false;
    const isOpenAtLogin = () => {
      return app.getLoginItemSettings().openAtLogin;
    };
    if (isOpenAtLogin() !== auto) {
      app.setLoginItemSettings({
        openAtLogin: auto,
        path: process.execPath
      });
      return isOpenAtLogin() === auto;
    } else {
      return true;
    }
  },
  skipProxy() {
    return session.defaultSession.setProxy({ mode: "direct" });
  }
};
const optimizer = {
  watchWindowShortcuts(window2, shortcutOptions) {
    if (!window2)
      return;
    const { webContents } = window2;
    const { escToCloseWindow = false, zoom = false } = shortcutOptions || {};
    webContents.on("before-input-event", (event, input) => {
      if (input.type === "keyDown") {
        if (!is.dev) {
          if (input.code === "KeyR" && (input.control || input.meta))
            event.preventDefault();
        } else {
          if (input.code === "F12") {
            if (webContents.isDevToolsOpened()) {
              webContents.closeDevTools();
            } else {
              webContents.openDevTools({ mode: "undocked" });
              console.log("Open dev tool...");
            }
          }
        }
        if (escToCloseWindow) {
          if (input.code === "Escape" && input.key !== "Process") {
            window2.close();
            event.preventDefault();
          }
        }
        if (!zoom) {
          if (input.code === "Minus" && (input.control || input.meta))
            event.preventDefault();
          if (input.code === "Equal" && input.shift && (input.control || input.meta))
            event.preventDefault();
        }
      }
    });
  },
  registerFramelessWindowIpc() {
    ipcMain.on("win:invoke", (event, action) => {
      const win = BrowserWindow.fromWebContents(event.sender);
      if (win) {
        if (action === "show") {
          win.show();
        } else if (action === "showInactive") {
          win.showInactive();
        } else if (action === "min") {
          win.minimize();
        } else if (action === "max") {
          const isMaximized = win.isMaximized();
          if (isMaximized) {
            win.unmaximize();
          } else {
            win.maximize();
          }
        } else if (action === "close") {
          win.close();
        }
      }
    });
  }
};
function getDefaultExportFromCjs(x) {
  return x && x.__esModule && Object.prototype.hasOwnProperty.call(x, "default") ? x["default"] : x;
}
var packageJson;
var hasRequiredPackageJson;
function requirePackageJson() {
  if (hasRequiredPackageJson) return packageJson;
  hasRequiredPackageJson = 1;
  const fs$12 = fs;
  const path$1 = path;
  packageJson = {
    findAndReadPackageJson,
    tryReadJsonAt
  };
  function findAndReadPackageJson() {
    return tryReadJsonAt(getMainModulePath()) || tryReadJsonAt(extractPathFromArgs()) || tryReadJsonAt(process.resourcesPath, "app.asar") || tryReadJsonAt(process.resourcesPath, "app") || tryReadJsonAt(process.cwd()) || { name: void 0, version: void 0 };
  }
  function tryReadJsonAt(...searchPaths) {
    if (!searchPaths[0]) {
      return void 0;
    }
    try {
      const searchPath = path$1.join(...searchPaths);
      const fileName = findUp("package.json", searchPath);
      if (!fileName) {
        return void 0;
      }
      const json = JSON.parse(fs$12.readFileSync(fileName, "utf8"));
      const name = json?.productName || json?.name;
      if (!name || name.toLowerCase() === "electron") {
        return void 0;
      }
      if (name) {
        return { name, version: json?.version };
      }
      return void 0;
    } catch (e) {
      return void 0;
    }
  }
  function findUp(fileName, cwd) {
    let currentPath = cwd;
    while (true) {
      const parsedPath = path$1.parse(currentPath);
      const root = parsedPath.root;
      const dir = parsedPath.dir;
      if (fs$12.existsSync(path$1.join(currentPath, fileName))) {
        return path$1.resolve(path$1.join(currentPath, fileName));
      }
      if (currentPath === root) {
        return null;
      }
      currentPath = dir;
    }
  }
  function extractPathFromArgs() {
    const matchedArgs = process.argv.filter((arg) => {
      return arg.indexOf("--user-data-dir=") === 0;
    });
    if (matchedArgs.length === 0 || typeof matchedArgs[0] !== "string") {
      return null;
    }
    const userDataDir = matchedArgs[0];
    return userDataDir.replace("--user-data-dir=", "");
  }
  function getMainModulePath() {
    try {
      return require2.main?.filename;
    } catch {
      return void 0;
    }
  }
  return packageJson;
}
var NodeExternalApi_1;
var hasRequiredNodeExternalApi;
function requireNodeExternalApi() {
  if (hasRequiredNodeExternalApi) return NodeExternalApi_1;
  hasRequiredNodeExternalApi = 1;
  const childProcess = require$$0;
  const os$1 = os;
  const path$1 = path;
  const packageJson2 = requirePackageJson();
  class NodeExternalApi {
    appName = void 0;
    appPackageJson = void 0;
    platform = process.platform;
    getAppLogPath(appName = this.getAppName()) {
      if (this.platform === "darwin") {
        return path$1.join(this.getSystemPathHome(), "Library/Logs", appName);
      }
      return path$1.join(this.getAppUserDataPath(appName), "logs");
    }
    getAppName() {
      const appName = this.appName || this.getAppPackageJson()?.name;
      if (!appName) {
        throw new Error(
          "electron-log can't determine the app name. It tried these methods:\n1. Use `electron.app.name`\n2. Use productName or name from the nearest package.json`\nYou can also set it through log.transports.file.setAppName()"
        );
      }
      return appName;
    }
    /**
     * @private
     * @returns {undefined}
     */
    getAppPackageJson() {
      if (typeof this.appPackageJson !== "object") {
        this.appPackageJson = packageJson2.findAndReadPackageJson();
      }
      return this.appPackageJson;
    }
    getAppUserDataPath(appName = this.getAppName()) {
      return appName ? path$1.join(this.getSystemPathAppData(), appName) : void 0;
    }
    getAppVersion() {
      return this.getAppPackageJson()?.version;
    }
    getElectronLogPath() {
      return this.getAppLogPath();
    }
    getMacOsVersion() {
      const release = Number(os$1.release().split(".")[0]);
      if (release <= 19) {
        return `10.${release - 4}`;
      }
      return release - 9;
    }
    /**
     * @protected
     * @returns {string}
     */
    getOsVersion() {
      let osName = os$1.type().replace("_", " ");
      let osVersion = os$1.release();
      if (osName === "Darwin") {
        osName = "macOS";
        osVersion = this.getMacOsVersion();
      }
      return `${osName} ${osVersion}`;
    }
    /**
     * @return {PathVariables}
     */
    getPathVariables() {
      const appName = this.getAppName();
      const appVersion = this.getAppVersion();
      const self = this;
      return {
        appData: this.getSystemPathAppData(),
        appName,
        appVersion,
        get electronDefaultDir() {
          return self.getElectronLogPath();
        },
        home: this.getSystemPathHome(),
        libraryDefaultDir: this.getAppLogPath(appName),
        libraryTemplate: this.getAppLogPath("{appName}"),
        temp: this.getSystemPathTemp(),
        userData: this.getAppUserDataPath(appName)
      };
    }
    getSystemPathAppData() {
      const home = this.getSystemPathHome();
      switch (this.platform) {
        case "darwin": {
          return path$1.join(home, "Library/Application Support");
        }
        case "win32": {
          return process.env.APPDATA || path$1.join(home, "AppData/Roaming");
        }
        default: {
          return process.env.XDG_CONFIG_HOME || path$1.join(home, ".config");
        }
      }
    }
    getSystemPathHome() {
      return os$1.homedir?.() || process.env.HOME;
    }
    getSystemPathTemp() {
      return os$1.tmpdir();
    }
    getVersions() {
      return {
        app: `${this.getAppName()} ${this.getAppVersion()}`,
        electron: void 0,
        os: this.getOsVersion()
      };
    }
    isDev() {
      return process.env.NODE_ENV === "development" || process.env.ELECTRON_IS_DEV === "1";
    }
    isElectron() {
      return Boolean(process.versions.electron);
    }
    onAppEvent(_eventName, _handler) {
    }
    onAppReady(handler) {
      handler();
    }
    onEveryWebContentsEvent(eventName, handler) {
    }
    /**
     * Listen to async messages sent from opposite process
     * @param {string} channel
     * @param {function} listener
     */
    onIpc(channel, listener) {
    }
    onIpcInvoke(channel, listener) {
    }
    /**
     * @param {string} url
     * @param {Function} [logFunction]
     */
    openUrl(url, logFunction = console.error) {
      const startMap = { darwin: "open", win32: "start", linux: "xdg-open" };
      const start = startMap[process.platform] || "xdg-open";
      childProcess.exec(`${start} ${url}`, {}, (err) => {
        if (err) {
          logFunction(err);
        }
      });
    }
    setAppName(appName) {
      this.appName = appName;
    }
    setPlatform(platform2) {
      this.platform = platform2;
    }
    setPreloadFileForSessions({
      filePath,
      // eslint-disable-line no-unused-vars
      includeFutureSession = true,
      // eslint-disable-line no-unused-vars
      getSessions = () => []
      // eslint-disable-line no-unused-vars
    }) {
    }
    /**
     * Sent a message to opposite process
     * @param {string} channel
     * @param {any} message
     */
    sendIpc(channel, message) {
    }
    showErrorBox(title, message) {
    }
  }
  NodeExternalApi_1 = NodeExternalApi;
  return NodeExternalApi_1;
}
var ElectronExternalApi_1;
var hasRequiredElectronExternalApi;
function requireElectronExternalApi() {
  if (hasRequiredElectronExternalApi) return ElectronExternalApi_1;
  hasRequiredElectronExternalApi = 1;
  const path$1 = path;
  const NodeExternalApi = requireNodeExternalApi();
  class ElectronExternalApi extends NodeExternalApi {
    /**
     * @type {typeof Electron}
     */
    electron = void 0;
    /**
     * @param {object} options
     * @param {typeof Electron} [options.electron]
     */
    constructor({ electron } = {}) {
      super();
      this.electron = electron;
    }
    getAppName() {
      let appName;
      try {
        appName = this.appName || this.electron.app?.name || this.electron.app?.getName();
      } catch {
      }
      return appName || super.getAppName();
    }
    getAppUserDataPath(appName) {
      return this.getPath("userData") || super.getAppUserDataPath(appName);
    }
    getAppVersion() {
      let appVersion;
      try {
        appVersion = this.electron.app?.getVersion();
      } catch {
      }
      return appVersion || super.getAppVersion();
    }
    getElectronLogPath() {
      return this.getPath("logs") || super.getElectronLogPath();
    }
    /**
     * @private
     * @param {any} name
     * @returns {string|undefined}
     */
    getPath(name) {
      try {
        return this.electron.app?.getPath(name);
      } catch {
        return void 0;
      }
    }
    getVersions() {
      return {
        app: `${this.getAppName()} ${this.getAppVersion()}`,
        electron: `Electron ${process.versions.electron}`,
        os: this.getOsVersion()
      };
    }
    getSystemPathAppData() {
      return this.getPath("appData") || super.getSystemPathAppData();
    }
    isDev() {
      if (this.electron.app?.isPackaged !== void 0) {
        return !this.electron.app.isPackaged;
      }
      if (typeof process.execPath === "string") {
        const execFileName = path$1.basename(process.execPath).toLowerCase();
        return execFileName.startsWith("electron");
      }
      return super.isDev();
    }
    onAppEvent(eventName, handler) {
      this.electron.app?.on(eventName, handler);
      return () => {
        this.electron.app?.off(eventName, handler);
      };
    }
    onAppReady(handler) {
      if (this.electron.app?.isReady()) {
        handler();
      } else if (this.electron.app?.once) {
        this.electron.app?.once("ready", handler);
      } else {
        handler();
      }
    }
    onEveryWebContentsEvent(eventName, handler) {
      this.electron.webContents?.getAllWebContents()?.forEach((webContents) => {
        webContents.on(eventName, handler);
      });
      this.electron.app?.on("web-contents-created", onWebContentsCreated);
      return () => {
        this.electron.webContents?.getAllWebContents().forEach((webContents) => {
          webContents.off(eventName, handler);
        });
        this.electron.app?.off("web-contents-created", onWebContentsCreated);
      };
      function onWebContentsCreated(_, webContents) {
        webContents.on(eventName, handler);
      }
    }
    /**
     * Listen to async messages sent from opposite process
     * @param {string} channel
     * @param {function} listener
     */
    onIpc(channel, listener) {
      this.electron.ipcMain?.on(channel, listener);
    }
    onIpcInvoke(channel, listener) {
      this.electron.ipcMain?.handle?.(channel, listener);
    }
    /**
     * @param {string} url
     * @param {Function} [logFunction]
     */
    openUrl(url, logFunction = console.error) {
      this.electron.shell?.openExternal(url).catch(logFunction);
    }
    setPreloadFileForSessions({
      filePath,
      includeFutureSession = true,
      getSessions = () => [this.electron.session?.defaultSession]
    }) {
      for (const session2 of getSessions().filter(Boolean)) {
        setPreload(session2);
      }
      if (includeFutureSession) {
        this.onAppEvent("session-created", (session2) => {
          setPreload(session2);
        });
      }
      function setPreload(session2) {
        if (typeof session2.registerPreloadScript === "function") {
          session2.registerPreloadScript({
            filePath,
            id: "electron-log-preload",
            type: "frame"
          });
        } else {
          session2.setPreloads([...session2.getPreloads(), filePath]);
        }
      }
    }
    /**
     * Sent a message to opposite process
     * @param {string} channel
     * @param {any} message
     */
    sendIpc(channel, message) {
      this.electron.BrowserWindow?.getAllWindows()?.forEach((wnd) => {
        if (wnd.webContents?.isDestroyed() === false && wnd.webContents?.isCrashed() === false) {
          wnd.webContents.send(channel, message);
        }
      });
    }
    showErrorBox(title, message) {
      this.electron.dialog?.showErrorBox(title, message);
    }
  }
  ElectronExternalApi_1 = ElectronExternalApi;
  return ElectronExternalApi_1;
}
var electronLogPreload = { exports: {} };
var hasRequiredElectronLogPreload;
function requireElectronLogPreload() {
  if (hasRequiredElectronLogPreload) return electronLogPreload.exports;
  hasRequiredElectronLogPreload = 1;
  (function(module) {
    let electron = {};
    try {
      electron = require2("electron");
    } catch (e) {
    }
    if (electron.ipcRenderer) {
      initialize2(electron);
    }
    {
      module.exports = initialize2;
    }
    function initialize2({ contextBridge, ipcRenderer }) {
      if (!ipcRenderer) {
        return;
      }
      ipcRenderer.on("__ELECTRON_LOG_IPC__", (_, message) => {
        window.postMessage({ cmd: "message", ...message });
      });
      ipcRenderer.invoke("__ELECTRON_LOG__", { cmd: "getOptions" }).catch((e) => console.error(new Error(
        `electron-log isn't initialized in the main process. Please call log.initialize() before. ${e.message}`
      )));
      const electronLog = {
        sendToMain(message) {
          try {
            ipcRenderer.send("__ELECTRON_LOG__", message);
          } catch (e) {
            console.error("electronLog.sendToMain ", e, "data:", message);
            ipcRenderer.send("__ELECTRON_LOG__", {
              cmd: "errorHandler",
              error: { message: e?.message, stack: e?.stack },
              errorName: "sendToMain"
            });
          }
        },
        log(...data) {
          electronLog.sendToMain({ data, level: "info" });
        }
      };
      for (const level of ["error", "warn", "info", "verbose", "debug", "silly"]) {
        electronLog[level] = (...data) => electronLog.sendToMain({
          data,
          level
        });
      }
      if (contextBridge && process.contextIsolated) {
        try {
          contextBridge.exposeInMainWorld("__electronLog", electronLog);
        } catch {
        }
      }
      if (typeof window === "object") {
        window.__electronLog = electronLog;
      } else {
        __electronLog = electronLog;
      }
    }
  })(electronLogPreload);
  return electronLogPreload.exports;
}
var initialize;
var hasRequiredInitialize;
function requireInitialize() {
  if (hasRequiredInitialize) return initialize;
  hasRequiredInitialize = 1;
  const fs$12 = fs;
  const os$1 = os;
  const path$1 = path;
  const preloadInitializeFn = requireElectronLogPreload();
  let preloadInitialized = false;
  let spyConsoleInitialized = false;
  initialize = {
    initialize({
      externalApi,
      getSessions,
      includeFutureSession,
      logger,
      preload = true,
      spyRendererConsole = false
    }) {
      externalApi.onAppReady(() => {
        try {
          if (preload) {
            initializePreload({
              externalApi,
              getSessions,
              includeFutureSession,
              logger,
              preloadOption: preload
            });
          }
          if (spyRendererConsole) {
            initializeSpyRendererConsole({ externalApi, logger });
          }
        } catch (err) {
          logger.warn(err);
        }
      });
    }
  };
  function initializePreload({
    externalApi,
    getSessions,
    includeFutureSession,
    logger,
    preloadOption
  }) {
    let preloadPath = typeof preloadOption === "string" ? preloadOption : void 0;
    if (preloadInitialized) {
      logger.warn(new Error("log.initialize({ preload }) already called").stack);
      return;
    }
    preloadInitialized = true;
    try {
      preloadPath = path$1.resolve(
        __dirname,
        "../renderer/electron-log-preload.js"
      );
    } catch {
    }
    if (!preloadPath || !fs$12.existsSync(preloadPath)) {
      preloadPath = path$1.join(
        externalApi.getAppUserDataPath() || os$1.tmpdir(),
        "electron-log-preload.js"
      );
      const preloadCode = `
      try {
        (${preloadInitializeFn.toString()})(require('electron'));
      } catch(e) {
        console.error(e);
      }
    `;
      fs$12.writeFileSync(preloadPath, preloadCode, "utf8");
    }
    externalApi.setPreloadFileForSessions({
      filePath: preloadPath,
      includeFutureSession,
      getSessions
    });
  }
  function initializeSpyRendererConsole({ externalApi, logger }) {
    if (spyConsoleInitialized) {
      logger.warn(
        new Error("log.initialize({ spyRendererConsole }) already called").stack
      );
      return;
    }
    spyConsoleInitialized = true;
    const levels = ["debug", "info", "warn", "error"];
    externalApi.onEveryWebContentsEvent(
      "console-message",
      (event, level, message) => {
        logger.processMessage({
          data: [message],
          level: levels[level],
          variables: { processType: "renderer" }
        });
      }
    );
  }
  return initialize;
}
var scope;
var hasRequiredScope;
function requireScope() {
  if (hasRequiredScope) return scope;
  hasRequiredScope = 1;
  scope = scopeFactory;
  function scopeFactory(logger) {
    return Object.defineProperties(scope2, {
      defaultLabel: { value: "", writable: true },
      labelPadding: { value: true, writable: true },
      maxLabelLength: { value: 0, writable: true },
      labelLength: {
        get() {
          switch (typeof scope2.labelPadding) {
            case "boolean":
              return scope2.labelPadding ? scope2.maxLabelLength : 0;
            case "number":
              return scope2.labelPadding;
            default:
              return 0;
          }
        }
      }
    });
    function scope2(label) {
      scope2.maxLabelLength = Math.max(scope2.maxLabelLength, label.length);
      const newScope = {};
      for (const level of logger.levels) {
        newScope[level] = (...d) => logger.logData(d, { level, scope: label });
      }
      newScope.log = newScope.info;
      return newScope;
    }
  }
  return scope;
}
var Buffering_1;
var hasRequiredBuffering;
function requireBuffering() {
  if (hasRequiredBuffering) return Buffering_1;
  hasRequiredBuffering = 1;
  class Buffering {
    constructor({ processMessage }) {
      this.processMessage = processMessage;
      this.buffer = [];
      this.enabled = false;
      this.begin = this.begin.bind(this);
      this.commit = this.commit.bind(this);
      this.reject = this.reject.bind(this);
    }
    addMessage(message) {
      this.buffer.push(message);
    }
    begin() {
      this.enabled = [];
    }
    commit() {
      this.enabled = false;
      this.buffer.forEach((item) => this.processMessage(item));
      this.buffer = [];
    }
    reject() {
      this.enabled = false;
      this.buffer = [];
    }
  }
  Buffering_1 = Buffering;
  return Buffering_1;
}
var Logger_1;
var hasRequiredLogger;
function requireLogger() {
  if (hasRequiredLogger) return Logger_1;
  hasRequiredLogger = 1;
  const scopeFactory = requireScope();
  const Buffering = requireBuffering();
  class Logger {
    static instances = {};
    dependencies = {};
    errorHandler = null;
    eventLogger = null;
    functions = {};
    hooks = [];
    isDev = false;
    levels = null;
    logId = null;
    scope = null;
    transports = {};
    variables = {};
    constructor({
      allowUnknownLevel = false,
      dependencies = {},
      errorHandler,
      eventLogger,
      initializeFn,
      isDev: isDev2 = false,
      levels = ["error", "warn", "info", "verbose", "debug", "silly"],
      logId,
      transportFactories = {},
      variables
    } = {}) {
      this.addLevel = this.addLevel.bind(this);
      this.create = this.create.bind(this);
      this.initialize = this.initialize.bind(this);
      this.logData = this.logData.bind(this);
      this.processMessage = this.processMessage.bind(this);
      this.allowUnknownLevel = allowUnknownLevel;
      this.buffering = new Buffering(this);
      this.dependencies = dependencies;
      this.initializeFn = initializeFn;
      this.isDev = isDev2;
      this.levels = levels;
      this.logId = logId;
      this.scope = scopeFactory(this);
      this.transportFactories = transportFactories;
      this.variables = variables || {};
      for (const name of this.levels) {
        this.addLevel(name, false);
      }
      this.log = this.info;
      this.functions.log = this.log;
      this.errorHandler = errorHandler;
      errorHandler?.setOptions({ ...dependencies, logFn: this.error });
      this.eventLogger = eventLogger;
      eventLogger?.setOptions({ ...dependencies, logger: this });
      for (const [name, factory] of Object.entries(transportFactories)) {
        this.transports[name] = factory(this, dependencies);
      }
      Logger.instances[logId] = this;
    }
    static getInstance({ logId }) {
      return this.instances[logId] || this.instances.default;
    }
    addLevel(level, index = this.levels.length) {
      if (index !== false) {
        this.levels.splice(index, 0, level);
      }
      this[level] = (...args) => this.logData(args, { level });
      this.functions[level] = this[level];
    }
    catchErrors(options) {
      this.processMessage(
        {
          data: ["log.catchErrors is deprecated. Use log.errorHandler instead"],
          level: "warn"
        },
        { transports: ["console"] }
      );
      return this.errorHandler.startCatching(options);
    }
    create(options) {
      if (typeof options === "string") {
        options = { logId: options };
      }
      return new Logger({
        dependencies: this.dependencies,
        errorHandler: this.errorHandler,
        initializeFn: this.initializeFn,
        isDev: this.isDev,
        transportFactories: this.transportFactories,
        variables: { ...this.variables },
        ...options
      });
    }
    compareLevels(passLevel, checkLevel, levels = this.levels) {
      const pass = levels.indexOf(passLevel);
      const check = levels.indexOf(checkLevel);
      if (check === -1 || pass === -1) {
        return true;
      }
      return check <= pass;
    }
    initialize(options = {}) {
      this.initializeFn({ logger: this, ...this.dependencies, ...options });
    }
    logData(data, options = {}) {
      if (this.buffering.enabled) {
        this.buffering.addMessage({ data, date: /* @__PURE__ */ new Date(), ...options });
      } else {
        this.processMessage({ data, ...options });
      }
    }
    processMessage(message, { transports = this.transports } = {}) {
      if (message.cmd === "errorHandler") {
        this.errorHandler.handle(message.error, {
          errorName: message.errorName,
          processType: "renderer",
          showDialog: Boolean(message.showDialog)
        });
        return;
      }
      let level = message.level;
      if (!this.allowUnknownLevel) {
        level = this.levels.includes(message.level) ? message.level : "info";
      }
      const normalizedMessage = {
        date: /* @__PURE__ */ new Date(),
        logId: this.logId,
        ...message,
        level,
        variables: {
          ...this.variables,
          ...message.variables
        }
      };
      for (const [transName, transFn] of this.transportEntries(transports)) {
        if (typeof transFn !== "function" || transFn.level === false) {
          continue;
        }
        if (!this.compareLevels(transFn.level, message.level)) {
          continue;
        }
        try {
          const transformedMsg = this.hooks.reduce((msg, hook) => {
            return msg ? hook(msg, transFn, transName) : msg;
          }, normalizedMessage);
          if (transformedMsg) {
            transFn({ ...transformedMsg, data: [...transformedMsg.data] });
          }
        } catch (e) {
          this.processInternalErrorFn(e);
        }
      }
    }
    processInternalErrorFn(_e) {
    }
    transportEntries(transports = this.transports) {
      const transportArray = Array.isArray(transports) ? transports : Object.entries(transports);
      return transportArray.map((item) => {
        switch (typeof item) {
          case "string":
            return this.transports[item] ? [item, this.transports[item]] : null;
          case "function":
            return [item.name, item];
          default:
            return Array.isArray(item) ? item : null;
        }
      }).filter(Boolean);
    }
  }
  Logger_1 = Logger;
  return Logger_1;
}
var ErrorHandler_1;
var hasRequiredErrorHandler;
function requireErrorHandler() {
  if (hasRequiredErrorHandler) return ErrorHandler_1;
  hasRequiredErrorHandler = 1;
  class ErrorHandler {
    externalApi = void 0;
    isActive = false;
    logFn = void 0;
    onError = void 0;
    showDialog = true;
    constructor({
      externalApi,
      logFn = void 0,
      onError = void 0,
      showDialog = void 0
    } = {}) {
      this.createIssue = this.createIssue.bind(this);
      this.handleError = this.handleError.bind(this);
      this.handleRejection = this.handleRejection.bind(this);
      this.setOptions({ externalApi, logFn, onError, showDialog });
      this.startCatching = this.startCatching.bind(this);
      this.stopCatching = this.stopCatching.bind(this);
    }
    handle(error, {
      logFn = this.logFn,
      onError = this.onError,
      processType = "browser",
      showDialog = this.showDialog,
      errorName = ""
    } = {}) {
      error = normalizeError(error);
      try {
        if (typeof onError === "function") {
          const versions = this.externalApi?.getVersions() || {};
          const createIssue = this.createIssue;
          const result = onError({
            createIssue,
            error,
            errorName,
            processType,
            versions
          });
          if (result === false) {
            return;
          }
        }
        errorName ? logFn(errorName, error) : logFn(error);
        if (showDialog && !errorName.includes("rejection") && this.externalApi) {
          this.externalApi.showErrorBox(
            `A JavaScript error occurred in the ${processType} process`,
            error.stack
          );
        }
      } catch {
        console.error(error);
      }
    }
    setOptions({ externalApi, logFn, onError, showDialog }) {
      if (typeof externalApi === "object") {
        this.externalApi = externalApi;
      }
      if (typeof logFn === "function") {
        this.logFn = logFn;
      }
      if (typeof onError === "function") {
        this.onError = onError;
      }
      if (typeof showDialog === "boolean") {
        this.showDialog = showDialog;
      }
    }
    startCatching({ onError, showDialog } = {}) {
      if (this.isActive) {
        return;
      }
      this.isActive = true;
      this.setOptions({ onError, showDialog });
      process.on("uncaughtException", this.handleError);
      process.on("unhandledRejection", this.handleRejection);
    }
    stopCatching() {
      this.isActive = false;
      process.removeListener("uncaughtException", this.handleError);
      process.removeListener("unhandledRejection", this.handleRejection);
    }
    createIssue(pageUrl, queryParams) {
      this.externalApi?.openUrl(
        `${pageUrl}?${new URLSearchParams(queryParams).toString()}`
      );
    }
    handleError(error) {
      this.handle(error, { errorName: "Unhandled" });
    }
    handleRejection(reason) {
      const error = reason instanceof Error ? reason : new Error(JSON.stringify(reason));
      this.handle(error, { errorName: "Unhandled rejection" });
    }
  }
  function normalizeError(e) {
    if (e instanceof Error) {
      return e;
    }
    if (e && typeof e === "object") {
      if (e.message) {
        return Object.assign(new Error(e.message), e);
      }
      try {
        return new Error(JSON.stringify(e));
      } catch (serErr) {
        return new Error(`Couldn't normalize error ${String(e)}: ${serErr}`);
      }
    }
    return new Error(`Can't normalize error ${String(e)}`);
  }
  ErrorHandler_1 = ErrorHandler;
  return ErrorHandler_1;
}
var EventLogger_1;
var hasRequiredEventLogger;
function requireEventLogger() {
  if (hasRequiredEventLogger) return EventLogger_1;
  hasRequiredEventLogger = 1;
  class EventLogger {
    disposers = [];
    format = "{eventSource}#{eventName}:";
    formatters = {
      app: {
        "certificate-error": ({ args }) => {
          return this.arrayToObject(args.slice(1, 4), [
            "url",
            "error",
            "certificate"
          ]);
        },
        "child-process-gone": ({ args }) => {
          return args.length === 1 ? args[0] : args;
        },
        "render-process-gone": ({ args: [webContents, details] }) => {
          return details && typeof details === "object" ? { ...details, ...this.getWebContentsDetails(webContents) } : [];
        }
      },
      webContents: {
        "console-message": ({ args: [level, message, line, sourceId] }) => {
          if (level < 3) {
            return void 0;
          }
          return { message, source: `${sourceId}:${line}` };
        },
        "did-fail-load": ({ args }) => {
          return this.arrayToObject(args, [
            "errorCode",
            "errorDescription",
            "validatedURL",
            "isMainFrame",
            "frameProcessId",
            "frameRoutingId"
          ]);
        },
        "did-fail-provisional-load": ({ args }) => {
          return this.arrayToObject(args, [
            "errorCode",
            "errorDescription",
            "validatedURL",
            "isMainFrame",
            "frameProcessId",
            "frameRoutingId"
          ]);
        },
        "plugin-crashed": ({ args }) => {
          return this.arrayToObject(args, ["name", "version"]);
        },
        "preload-error": ({ args }) => {
          return this.arrayToObject(args, ["preloadPath", "error"]);
        }
      }
    };
    events = {
      app: {
        "certificate-error": true,
        "child-process-gone": true,
        "render-process-gone": true
      },
      webContents: {
        // 'console-message': true,
        "did-fail-load": true,
        "did-fail-provisional-load": true,
        "plugin-crashed": true,
        "preload-error": true,
        "unresponsive": true
      }
    };
    externalApi = void 0;
    level = "error";
    scope = "";
    constructor(options = {}) {
      this.setOptions(options);
    }
    setOptions({
      events,
      externalApi,
      level,
      logger,
      format: format2,
      formatters,
      scope: scope2
    }) {
      if (typeof events === "object") {
        this.events = events;
      }
      if (typeof externalApi === "object") {
        this.externalApi = externalApi;
      }
      if (typeof level === "string") {
        this.level = level;
      }
      if (typeof logger === "object") {
        this.logger = logger;
      }
      if (typeof format2 === "string" || typeof format2 === "function") {
        this.format = format2;
      }
      if (typeof formatters === "object") {
        this.formatters = formatters;
      }
      if (typeof scope2 === "string") {
        this.scope = scope2;
      }
    }
    startLogging(options = {}) {
      this.setOptions(options);
      this.disposeListeners();
      for (const eventName of this.getEventNames(this.events.app)) {
        this.disposers.push(
          this.externalApi.onAppEvent(eventName, (...handlerArgs) => {
            this.handleEvent({ eventSource: "app", eventName, handlerArgs });
          })
        );
      }
      for (const eventName of this.getEventNames(this.events.webContents)) {
        this.disposers.push(
          this.externalApi.onEveryWebContentsEvent(
            eventName,
            (...handlerArgs) => {
              this.handleEvent(
                { eventSource: "webContents", eventName, handlerArgs }
              );
            }
          )
        );
      }
    }
    stopLogging() {
      this.disposeListeners();
    }
    arrayToObject(array2, fieldNames) {
      const obj = {};
      fieldNames.forEach((fieldName, index) => {
        obj[fieldName] = array2[index];
      });
      if (array2.length > fieldNames.length) {
        obj.unknownArgs = array2.slice(fieldNames.length);
      }
      return obj;
    }
    disposeListeners() {
      this.disposers.forEach((disposer) => disposer());
      this.disposers = [];
    }
    formatEventLog({ eventName, eventSource, handlerArgs }) {
      const [event, ...args] = handlerArgs;
      if (typeof this.format === "function") {
        return this.format({ args, event, eventName, eventSource });
      }
      const formatter = this.formatters[eventSource]?.[eventName];
      let formattedArgs = args;
      if (typeof formatter === "function") {
        formattedArgs = formatter({ args, event, eventName, eventSource });
      }
      if (!formattedArgs) {
        return void 0;
      }
      const eventData = {};
      if (Array.isArray(formattedArgs)) {
        eventData.args = formattedArgs;
      } else if (typeof formattedArgs === "object") {
        Object.assign(eventData, formattedArgs);
      }
      if (eventSource === "webContents") {
        Object.assign(eventData, this.getWebContentsDetails(event?.sender));
      }
      const title = this.format.replace("{eventSource}", eventSource === "app" ? "App" : "WebContents").replace("{eventName}", eventName);
      return [title, eventData];
    }
    getEventNames(eventMap) {
      if (!eventMap || typeof eventMap !== "object") {
        return [];
      }
      return Object.entries(eventMap).filter(([_, listen]) => listen).map(([eventName]) => eventName);
    }
    getWebContentsDetails(webContents) {
      if (!webContents?.loadURL) {
        return {};
      }
      try {
        return {
          webContents: {
            id: webContents.id,
            url: webContents.getURL()
          }
        };
      } catch {
        return {};
      }
    }
    handleEvent({ eventName, eventSource, handlerArgs }) {
      const log = this.formatEventLog({ eventName, eventSource, handlerArgs });
      if (log) {
        const logFns = this.scope ? this.logger.scope(this.scope) : this.logger;
        logFns?.[this.level]?.(...log);
      }
    }
  }
  EventLogger_1 = EventLogger;
  return EventLogger_1;
}
var transform_1;
var hasRequiredTransform;
function requireTransform() {
  if (hasRequiredTransform) return transform_1;
  hasRequiredTransform = 1;
  transform_1 = { transform: transform2 };
  function transform2({
    logger,
    message,
    transport,
    initialData = message?.data || [],
    transforms = transport?.transforms
  }) {
    return transforms.reduce((data, trans) => {
      if (typeof trans === "function") {
        return trans({ data, logger, message, transport });
      }
      return data;
    }, initialData);
  }
  return transform_1;
}
var format;
var hasRequiredFormat;
function requireFormat() {
  if (hasRequiredFormat) return format;
  hasRequiredFormat = 1;
  const { transform: transform2 } = requireTransform();
  format = {
    concatFirstStringElements,
    formatScope,
    formatText,
    formatVariables,
    timeZoneFromOffset,
    format({ message, logger, transport, data = message?.data }) {
      switch (typeof transport.format) {
        case "string": {
          return transform2({
            message,
            logger,
            transforms: [formatVariables, formatScope, formatText],
            transport,
            initialData: [transport.format, ...data]
          });
        }
        case "function": {
          return transport.format({
            data,
            level: message?.level || "info",
            logger,
            message,
            transport
          });
        }
        default: {
          return data;
        }
      }
    }
  };
  function concatFirstStringElements({ data }) {
    if (typeof data[0] !== "string" || typeof data[1] !== "string") {
      return data;
    }
    if (data[0].match(/%[1cdfiOos]/)) {
      return data;
    }
    return [`${data[0]} ${data[1]}`, ...data.slice(2)];
  }
  function timeZoneFromOffset(minutesOffset) {
    const minutesPositive = Math.abs(minutesOffset);
    const sign = minutesOffset > 0 ? "-" : "+";
    const hours = Math.floor(minutesPositive / 60).toString().padStart(2, "0");
    const minutes = (minutesPositive % 60).toString().padStart(2, "0");
    return `${sign}${hours}:${minutes}`;
  }
  function formatScope({ data, logger, message }) {
    const { defaultLabel, labelLength } = logger?.scope || {};
    const template = data[0];
    let label = message.scope;
    if (!label) {
      label = defaultLabel;
    }
    let scopeText;
    if (label === "") {
      scopeText = labelLength > 0 ? "".padEnd(labelLength + 3) : "";
    } else if (typeof label === "string") {
      scopeText = ` (${label})`.padEnd(labelLength + 3);
    } else {
      scopeText = "";
    }
    data[0] = template.replace("{scope}", scopeText);
    return data;
  }
  function formatVariables({ data, message }) {
    let template = data[0];
    if (typeof template !== "string") {
      return data;
    }
    template = template.replace("{level}]", `${message.level}]`.padEnd(6, " "));
    const date2 = message.date || /* @__PURE__ */ new Date();
    data[0] = template.replace(/\{(\w+)}/g, (substring, name) => {
      switch (name) {
        case "level":
          return message.level || "info";
        case "logId":
          return message.logId;
        case "y":
          return date2.getFullYear().toString(10);
        case "m":
          return (date2.getMonth() + 1).toString(10).padStart(2, "0");
        case "d":
          return date2.getDate().toString(10).padStart(2, "0");
        case "h":
          return date2.getHours().toString(10).padStart(2, "0");
        case "i":
          return date2.getMinutes().toString(10).padStart(2, "0");
        case "s":
          return date2.getSeconds().toString(10).padStart(2, "0");
        case "ms":
          return date2.getMilliseconds().toString(10).padStart(3, "0");
        case "z":
          return timeZoneFromOffset(date2.getTimezoneOffset());
        case "iso":
          return date2.toISOString();
        default: {
          return message.variables?.[name] || substring;
        }
      }
    }).trim();
    return data;
  }
  function formatText({ data }) {
    const template = data[0];
    if (typeof template !== "string") {
      return data;
    }
    const textTplPosition = template.lastIndexOf("{text}");
    if (textTplPosition === template.length - 6) {
      data[0] = template.replace(/\s?{text}/, "");
      if (data[0] === "") {
        data.shift();
      }
      return data;
    }
    const templatePieces = template.split("{text}");
    let result = [];
    if (templatePieces[0] !== "") {
      result.push(templatePieces[0]);
    }
    result = result.concat(data.slice(1));
    if (templatePieces[1] !== "") {
      result.push(templatePieces[1]);
    }
    return result;
  }
  return format;
}
var object$1 = { exports: {} };
var hasRequiredObject;
function requireObject() {
  if (hasRequiredObject) return object$1.exports;
  hasRequiredObject = 1;
  (function(module) {
    const util = require$$0$1;
    module.exports = {
      serialize,
      maxDepth({ data, transport, depth = transport?.depth ?? 6 }) {
        if (!data) {
          return data;
        }
        if (depth < 1) {
          if (Array.isArray(data)) return "[array]";
          if (typeof data === "object" && data) return "[object]";
          return data;
        }
        if (Array.isArray(data)) {
          return data.map((child) => module.exports.maxDepth({
            data: child,
            depth: depth - 1
          }));
        }
        if (typeof data !== "object") {
          return data;
        }
        if (data && typeof data.toISOString === "function") {
          return data;
        }
        if (data === null) {
          return null;
        }
        if (data instanceof Error) {
          return data;
        }
        const newJson = {};
        for (const i in data) {
          if (!Object.prototype.hasOwnProperty.call(data, i)) continue;
          newJson[i] = module.exports.maxDepth({
            data: data[i],
            depth: depth - 1
          });
        }
        return newJson;
      },
      toJSON({ data }) {
        return JSON.parse(JSON.stringify(data, createSerializer()));
      },
      toString({ data, transport }) {
        const inspectOptions = transport?.inspectOptions || {};
        const simplifiedData = data.map((item) => {
          if (item === void 0) {
            return void 0;
          }
          try {
            const str = JSON.stringify(item, createSerializer(), "  ");
            return str === void 0 ? void 0 : JSON.parse(str);
          } catch (e) {
            return item;
          }
        });
        return util.formatWithOptions(inspectOptions, ...simplifiedData);
      }
    };
    function createSerializer(options = {}) {
      const seen = /* @__PURE__ */ new WeakSet();
      return function(key, value) {
        if (typeof value === "object" && value !== null) {
          if (seen.has(value)) {
            return void 0;
          }
          seen.add(value);
        }
        return serialize(key, value, options);
      };
    }
    function serialize(key, value, options = {}) {
      const serializeMapAndSet = options?.serializeMapAndSet !== false;
      if (value instanceof Error) {
        return value.stack;
      }
      if (!value) {
        return value;
      }
      if (typeof value === "function") {
        return `[function] ${value.toString()}`;
      }
      if (value instanceof Date) {
        return value.toISOString();
      }
      if (serializeMapAndSet && value instanceof Map && Object.fromEntries) {
        return Object.fromEntries(value);
      }
      if (serializeMapAndSet && value instanceof Set && Array.from) {
        return Array.from(value);
      }
      return value;
    }
  })(object$1);
  return object$1.exports;
}
var style;
var hasRequiredStyle;
function requireStyle() {
  if (hasRequiredStyle) return style;
  hasRequiredStyle = 1;
  style = {
    transformStyles,
    applyAnsiStyles({ data }) {
      return transformStyles(data, styleToAnsi, resetAnsiStyle);
    },
    removeStyles({ data }) {
      return transformStyles(data, () => "");
    }
  };
  const ANSI_COLORS = {
    unset: "\x1B[0m",
    black: "\x1B[30m",
    red: "\x1B[31m",
    green: "\x1B[32m",
    yellow: "\x1B[33m",
    blue: "\x1B[34m",
    magenta: "\x1B[35m",
    cyan: "\x1B[36m",
    white: "\x1B[37m",
    gray: "\x1B[90m"
  };
  function styleToAnsi(style2) {
    const color = style2.replace(/color:\s*(\w+).*/, "$1").toLowerCase();
    return ANSI_COLORS[color] || "";
  }
  function resetAnsiStyle(string2) {
    return string2 + ANSI_COLORS.unset;
  }
  function transformStyles(data, onStyleFound, onStyleApplied) {
    const foundStyles = {};
    return data.reduce((result, item, index, array2) => {
      if (foundStyles[index]) {
        return result;
      }
      if (typeof item === "string") {
        let valueIndex = index;
        let styleApplied = false;
        item = item.replace(/%[1cdfiOos]/g, (match) => {
          valueIndex += 1;
          if (match !== "%c") {
            return match;
          }
          const style2 = array2[valueIndex];
          if (typeof style2 === "string") {
            foundStyles[valueIndex] = true;
            styleApplied = true;
            return onStyleFound(style2, item);
          }
          return match;
        });
        if (styleApplied && onStyleApplied) {
          item = onStyleApplied(item);
        }
      }
      result.push(item);
      return result;
    }, []);
  }
  return style;
}
var console_1;
var hasRequiredConsole;
function requireConsole() {
  if (hasRequiredConsole) return console_1;
  hasRequiredConsole = 1;
  const {
    concatFirstStringElements,
    format: format2
  } = requireFormat();
  const { maxDepth, toJSON } = requireObject();
  const {
    applyAnsiStyles,
    removeStyles
  } = requireStyle();
  const { transform: transform2 } = requireTransform();
  const consoleMethods = {
    error: console.error,
    warn: console.warn,
    info: console.info,
    verbose: console.info,
    debug: console.debug,
    silly: console.debug,
    log: console.log
  };
  console_1 = consoleTransportFactory;
  const separator = process.platform === "win32" ? ">" : "›";
  const DEFAULT_FORMAT = `%c{h}:{i}:{s}.{ms}{scope}%c ${separator} {text}`;
  Object.assign(consoleTransportFactory, {
    DEFAULT_FORMAT
  });
  function consoleTransportFactory(logger) {
    return Object.assign(transport, {
      colorMap: {
        error: "red",
        warn: "yellow",
        info: "cyan",
        verbose: "unset",
        debug: "gray",
        silly: "gray",
        default: "unset"
      },
      format: DEFAULT_FORMAT,
      level: "silly",
      transforms: [
        addTemplateColors,
        format2,
        formatStyles,
        concatFirstStringElements,
        maxDepth,
        toJSON
      ],
      useStyles: process.env.FORCE_STYLES,
      writeFn({ message }) {
        const consoleLogFn = consoleMethods[message.level] || consoleMethods.info;
        consoleLogFn(...message.data);
      }
    });
    function transport(message) {
      const data = transform2({ logger, message, transport });
      transport.writeFn({
        message: { ...message, data }
      });
    }
  }
  function addTemplateColors({ data, message, transport }) {
    if (typeof transport.format !== "string" || !transport.format.includes("%c")) {
      return data;
    }
    return [
      `color:${levelToStyle(message.level, transport)}`,
      "color:unset",
      ...data
    ];
  }
  function canUseStyles(useStyleValue, level) {
    if (typeof useStyleValue === "boolean") {
      return useStyleValue;
    }
    const useStderr = level === "error" || level === "warn";
    const stream = useStderr ? process.stderr : process.stdout;
    return stream && stream.isTTY;
  }
  function formatStyles(args) {
    const { message, transport } = args;
    const useStyles = canUseStyles(transport.useStyles, message.level);
    const nextTransform = useStyles ? applyAnsiStyles : removeStyles;
    return nextTransform(args);
  }
  function levelToStyle(level, transport) {
    return transport.colorMap[level] || transport.colorMap.default;
  }
  return console_1;
}
var File_1;
var hasRequiredFile$1;
function requireFile$1() {
  if (hasRequiredFile$1) return File_1;
  hasRequiredFile$1 = 1;
  const EventEmitter2 = require$$0$2;
  const fs$12 = fs;
  const os$1 = os;
  class File extends EventEmitter2 {
    asyncWriteQueue = [];
    bytesWritten = 0;
    hasActiveAsyncWriting = false;
    path = null;
    initialSize = void 0;
    writeOptions = null;
    writeAsync = false;
    constructor({
      path: path2,
      writeOptions = { encoding: "utf8", flag: "a", mode: 438 },
      writeAsync = false
    }) {
      super();
      this.path = path2;
      this.writeOptions = writeOptions;
      this.writeAsync = writeAsync;
    }
    get size() {
      return this.getSize();
    }
    clear() {
      try {
        fs$12.writeFileSync(this.path, "", {
          mode: this.writeOptions.mode,
          flag: "w"
        });
        this.reset();
        return true;
      } catch (e) {
        if (e.code === "ENOENT") {
          return true;
        }
        this.emit("error", e, this);
        return false;
      }
    }
    crop(bytesAfter) {
      try {
        const content = readFileSyncFromEnd(this.path, bytesAfter || 4096);
        this.clear();
        this.writeLine(`[log cropped]${os$1.EOL}${content}`);
      } catch (e) {
        this.emit(
          "error",
          new Error(`Couldn't crop file ${this.path}. ${e.message}`),
          this
        );
      }
    }
    getSize() {
      if (this.initialSize === void 0) {
        try {
          const stats = fs$12.statSync(this.path);
          this.initialSize = stats.size;
        } catch (e) {
          this.initialSize = 0;
        }
      }
      return this.initialSize + this.bytesWritten;
    }
    increaseBytesWrittenCounter(text) {
      this.bytesWritten += Buffer.byteLength(text, this.writeOptions.encoding);
    }
    isNull() {
      return false;
    }
    nextAsyncWrite() {
      const file2 = this;
      if (this.hasActiveAsyncWriting || this.asyncWriteQueue.length === 0) {
        return;
      }
      const text = this.asyncWriteQueue.join("");
      this.asyncWriteQueue = [];
      this.hasActiveAsyncWriting = true;
      fs$12.writeFile(this.path, text, this.writeOptions, (e) => {
        file2.hasActiveAsyncWriting = false;
        if (e) {
          file2.emit(
            "error",
            new Error(`Couldn't write to ${file2.path}. ${e.message}`),
            this
          );
        } else {
          file2.increaseBytesWrittenCounter(text);
        }
        file2.nextAsyncWrite();
      });
    }
    reset() {
      this.initialSize = void 0;
      this.bytesWritten = 0;
    }
    toString() {
      return this.path;
    }
    writeLine(text) {
      text += os$1.EOL;
      if (this.writeAsync) {
        this.asyncWriteQueue.push(text);
        this.nextAsyncWrite();
        return;
      }
      try {
        fs$12.writeFileSync(this.path, text, this.writeOptions);
        this.increaseBytesWrittenCounter(text);
      } catch (e) {
        this.emit(
          "error",
          new Error(`Couldn't write to ${this.path}. ${e.message}`),
          this
        );
      }
    }
  }
  File_1 = File;
  function readFileSyncFromEnd(filePath, bytesCount) {
    const buffer = Buffer.alloc(bytesCount);
    const stats = fs$12.statSync(filePath);
    const readLength = Math.min(stats.size, bytesCount);
    const offset = Math.max(0, stats.size - bytesCount);
    const fd = fs$12.openSync(filePath, "r");
    const totalBytes = fs$12.readSync(fd, buffer, 0, readLength, offset);
    fs$12.closeSync(fd);
    return buffer.toString("utf8", 0, totalBytes);
  }
  return File_1;
}
var NullFile_1;
var hasRequiredNullFile;
function requireNullFile() {
  if (hasRequiredNullFile) return NullFile_1;
  hasRequiredNullFile = 1;
  const File = requireFile$1();
  class NullFile extends File {
    clear() {
    }
    crop() {
    }
    getSize() {
      return 0;
    }
    isNull() {
      return true;
    }
    writeLine() {
    }
  }
  NullFile_1 = NullFile;
  return NullFile_1;
}
var FileRegistry_1;
var hasRequiredFileRegistry;
function requireFileRegistry() {
  if (hasRequiredFileRegistry) return FileRegistry_1;
  hasRequiredFileRegistry = 1;
  const EventEmitter2 = require$$0$2;
  const fs$12 = fs;
  const path$1 = path;
  const File = requireFile$1();
  const NullFile = requireNullFile();
  class FileRegistry extends EventEmitter2 {
    store = {};
    constructor() {
      super();
      this.emitError = this.emitError.bind(this);
    }
    /**
     * Provide a File object corresponding to the filePath
     * @param {string} filePath
     * @param {WriteOptions} [writeOptions]
     * @param {boolean} [writeAsync]
     * @return {File}
     */
    provide({ filePath, writeOptions = {}, writeAsync = false }) {
      let file2;
      try {
        filePath = path$1.resolve(filePath);
        if (this.store[filePath]) {
          return this.store[filePath];
        }
        file2 = this.createFile({ filePath, writeOptions, writeAsync });
      } catch (e) {
        file2 = new NullFile({ path: filePath });
        this.emitError(e, file2);
      }
      file2.on("error", this.emitError);
      this.store[filePath] = file2;
      return file2;
    }
    /**
     * @param {string} filePath
     * @param {WriteOptions} writeOptions
     * @param {boolean} async
     * @return {File}
     * @private
     */
    createFile({ filePath, writeOptions, writeAsync }) {
      this.testFileWriting({ filePath, writeOptions });
      return new File({ path: filePath, writeOptions, writeAsync });
    }
    /**
     * @param {Error} error
     * @param {File} file
     * @private
     */
    emitError(error, file2) {
      this.emit("error", error, file2);
    }
    /**
     * @param {string} filePath
     * @param {WriteOptions} writeOptions
     * @private
     */
    testFileWriting({ filePath, writeOptions }) {
      fs$12.mkdirSync(path$1.dirname(filePath), { recursive: true });
      fs$12.writeFileSync(filePath, "", { flag: "a", mode: writeOptions.mode });
    }
  }
  FileRegistry_1 = FileRegistry;
  return FileRegistry_1;
}
var file;
var hasRequiredFile;
function requireFile() {
  if (hasRequiredFile) return file;
  hasRequiredFile = 1;
  const fs$12 = fs;
  const os$1 = os;
  const path$1 = path;
  const FileRegistry = requireFileRegistry();
  const { transform: transform2 } = requireTransform();
  const { removeStyles } = requireStyle();
  const {
    format: format2,
    concatFirstStringElements
  } = requireFormat();
  const { toString } = requireObject();
  file = fileTransportFactory;
  const globalRegistry2 = new FileRegistry();
  function fileTransportFactory(logger, { registry: registry2 = globalRegistry2, externalApi } = {}) {
    let pathVariables;
    if (registry2.listenerCount("error") < 1) {
      registry2.on("error", (e, file2) => {
        logConsole(`Can't write to ${file2}`, e);
      });
    }
    return Object.assign(transport, {
      fileName: getDefaultFileName(logger.variables.processType),
      format: "[{y}-{m}-{d} {h}:{i}:{s}.{ms}] [{level}]{scope} {text}",
      getFile,
      inspectOptions: { depth: 5 },
      level: "silly",
      maxSize: 1024 ** 2,
      readAllLogs,
      sync: true,
      transforms: [removeStyles, format2, concatFirstStringElements, toString],
      writeOptions: { flag: "a", mode: 438, encoding: "utf8" },
      archiveLogFn(file2) {
        const oldPath = file2.toString();
        const inf = path$1.parse(oldPath);
        try {
          fs$12.renameSync(oldPath, path$1.join(inf.dir, `${inf.name}.old${inf.ext}`));
        } catch (e) {
          logConsole("Could not rotate log", e);
          const quarterOfMaxSize = Math.round(transport.maxSize / 4);
          file2.crop(Math.min(quarterOfMaxSize, 256 * 1024));
        }
      },
      resolvePathFn(vars) {
        return path$1.join(vars.libraryDefaultDir, vars.fileName);
      },
      setAppName(name) {
        logger.dependencies.externalApi.setAppName(name);
      }
    });
    function transport(message) {
      const file2 = getFile(message);
      const needLogRotation = transport.maxSize > 0 && file2.size > transport.maxSize;
      if (needLogRotation) {
        transport.archiveLogFn(file2);
        file2.reset();
      }
      const content = transform2({ logger, message, transport });
      file2.writeLine(content);
    }
    function initializeOnFirstAccess() {
      if (pathVariables) {
        return;
      }
      pathVariables = Object.create(
        Object.prototype,
        {
          ...Object.getOwnPropertyDescriptors(
            externalApi.getPathVariables()
          ),
          fileName: {
            get() {
              return transport.fileName;
            },
            enumerable: true
          }
        }
      );
      if (typeof transport.archiveLog === "function") {
        transport.archiveLogFn = transport.archiveLog;
        logConsole("archiveLog is deprecated. Use archiveLogFn instead");
      }
      if (typeof transport.resolvePath === "function") {
        transport.resolvePathFn = transport.resolvePath;
        logConsole("resolvePath is deprecated. Use resolvePathFn instead");
      }
    }
    function logConsole(message, error = null, level = "error") {
      const data = [`electron-log.transports.file: ${message}`];
      if (error) {
        data.push(error);
      }
      logger.transports.console({ data, date: /* @__PURE__ */ new Date(), level });
    }
    function getFile(msg) {
      initializeOnFirstAccess();
      const filePath = transport.resolvePathFn(pathVariables, msg);
      return registry2.provide({
        filePath,
        writeAsync: !transport.sync,
        writeOptions: transport.writeOptions
      });
    }
    function readAllLogs({ fileFilter = (f) => f.endsWith(".log") } = {}) {
      initializeOnFirstAccess();
      const logsPath = path$1.dirname(transport.resolvePathFn(pathVariables));
      if (!fs$12.existsSync(logsPath)) {
        return [];
      }
      return fs$12.readdirSync(logsPath).map((fileName) => path$1.join(logsPath, fileName)).filter(fileFilter).map((logPath) => {
        try {
          return {
            path: logPath,
            lines: fs$12.readFileSync(logPath, "utf8").split(os$1.EOL)
          };
        } catch {
          return null;
        }
      }).filter(Boolean);
    }
  }
  function getDefaultFileName(processType = process.type) {
    switch (processType) {
      case "renderer":
        return "renderer.log";
      case "worker":
        return "worker.log";
      default:
        return "main.log";
    }
  }
  return file;
}
var ipc;
var hasRequiredIpc;
function requireIpc() {
  if (hasRequiredIpc) return ipc;
  hasRequiredIpc = 1;
  const { maxDepth, toJSON } = requireObject();
  const { transform: transform2 } = requireTransform();
  ipc = ipcTransportFactory;
  function ipcTransportFactory(logger, { externalApi }) {
    Object.assign(transport, {
      depth: 3,
      eventId: "__ELECTRON_LOG_IPC__",
      level: logger.isDev ? "silly" : false,
      transforms: [toJSON, maxDepth]
    });
    return externalApi?.isElectron() ? transport : void 0;
    function transport(message) {
      if (message?.variables?.processType === "renderer") {
        return;
      }
      externalApi?.sendIpc(transport.eventId, {
        ...message,
        data: transform2({ logger, message, transport })
      });
    }
  }
  return ipc;
}
var remote;
var hasRequiredRemote;
function requireRemote() {
  if (hasRequiredRemote) return remote;
  hasRequiredRemote = 1;
  const http = require$$0$3;
  const https = require$$1;
  const { transform: transform2 } = requireTransform();
  const { removeStyles } = requireStyle();
  const { toJSON, maxDepth } = requireObject();
  remote = remoteTransportFactory;
  function remoteTransportFactory(logger) {
    return Object.assign(transport, {
      client: { name: "electron-application" },
      depth: 6,
      level: false,
      requestOptions: {},
      transforms: [removeStyles, toJSON, maxDepth],
      makeBodyFn({ message }) {
        return JSON.stringify({
          client: transport.client,
          data: message.data,
          date: message.date.getTime(),
          level: message.level,
          scope: message.scope,
          variables: message.variables
        });
      },
      processErrorFn({ error }) {
        logger.processMessage(
          {
            data: [`electron-log: can't POST ${transport.url}`, error],
            level: "warn"
          },
          { transports: ["console", "file"] }
        );
      },
      sendRequestFn({ serverUrl, requestOptions, body }) {
        const httpTransport = serverUrl.startsWith("https:") ? https : http;
        const request = httpTransport.request(serverUrl, {
          method: "POST",
          ...requestOptions,
          headers: {
            "Content-Type": "application/json",
            "Content-Length": body.length,
            ...requestOptions.headers
          }
        });
        request.write(body);
        request.end();
        return request;
      }
    });
    function transport(message) {
      if (!transport.url) {
        return;
      }
      const body = transport.makeBodyFn({
        logger,
        message: { ...message, data: transform2({ logger, message, transport }) },
        transport
      });
      const request = transport.sendRequestFn({
        serverUrl: transport.url,
        requestOptions: transport.requestOptions,
        body: Buffer.from(body, "utf8")
      });
      request.on("error", (error) => transport.processErrorFn({
        error,
        logger,
        message,
        request,
        transport
      }));
    }
  }
  return remote;
}
var createDefaultLogger_1;
var hasRequiredCreateDefaultLogger;
function requireCreateDefaultLogger() {
  if (hasRequiredCreateDefaultLogger) return createDefaultLogger_1;
  hasRequiredCreateDefaultLogger = 1;
  const Logger = requireLogger();
  const ErrorHandler = requireErrorHandler();
  const EventLogger = requireEventLogger();
  const transportConsole = requireConsole();
  const transportFile = requireFile();
  const transportIpc = requireIpc();
  const transportRemote = requireRemote();
  createDefaultLogger_1 = createDefaultLogger;
  function createDefaultLogger({ dependencies, initializeFn }) {
    const defaultLogger = new Logger({
      dependencies,
      errorHandler: new ErrorHandler(),
      eventLogger: new EventLogger(),
      initializeFn,
      isDev: dependencies.externalApi?.isDev(),
      logId: "default",
      transportFactories: {
        console: transportConsole,
        file: transportFile,
        ipc: transportIpc,
        remote: transportRemote
      },
      variables: {
        processType: "main"
      }
    });
    defaultLogger.default = defaultLogger;
    defaultLogger.Logger = Logger;
    defaultLogger.processInternalErrorFn = (e) => {
      defaultLogger.transports.console.writeFn({
        message: {
          data: ["Unhandled electron-log error", e],
          level: "error"
        }
      });
    };
    return defaultLogger;
  }
  return createDefaultLogger_1;
}
var main;
var hasRequiredMain$1;
function requireMain$1() {
  if (hasRequiredMain$1) return main;
  hasRequiredMain$1 = 1;
  const electron = require$$0$4;
  const ElectronExternalApi = requireElectronExternalApi();
  const { initialize: initialize2 } = requireInitialize();
  const createDefaultLogger = requireCreateDefaultLogger();
  const externalApi = new ElectronExternalApi({ electron });
  const defaultLogger = createDefaultLogger({
    dependencies: { externalApi },
    initializeFn: initialize2
  });
  main = defaultLogger;
  externalApi.onIpc("__ELECTRON_LOG__", (_, message) => {
    if (message.scope) {
      defaultLogger.Logger.getInstance(message).scope(message.scope);
    }
    const date2 = new Date(message.date);
    processMessage({
      ...message,
      date: date2.getTime() ? date2 : /* @__PURE__ */ new Date()
    });
  });
  externalApi.onIpcInvoke("__ELECTRON_LOG__", (_, { cmd = "", logId }) => {
    switch (cmd) {
      case "getOptions": {
        const logger = defaultLogger.Logger.getInstance({ logId });
        return {
          levels: logger.levels,
          logId
        };
      }
      default: {
        processMessage({ data: [`Unknown cmd '${cmd}'`], level: "error" });
        return {};
      }
    }
  });
  function processMessage(message) {
    defaultLogger.Logger.getInstance(message)?.processMessage(message);
  }
  return main;
}
var main_1;
var hasRequiredMain;
function requireMain() {
  if (hasRequiredMain) return main_1;
  hasRequiredMain = 1;
  const main2 = requireMain$1();
  main_1 = main2;
  return main_1;
}
var mainExports = requireMain();
const mainLogger = /* @__PURE__ */ getDefaultExportFromCjs(mainExports);
const UI_DEV_SERVER_URL = "http://localhost:5175";
const MAIN_WINDOW_DEFAULT_WIDTH = 1200;
const MAIN_WINDOW_DEFAULT_HEIGHT = 800;
const MAIN_WINDOW_MIN_WIDTH = 800;
const MAIN_WINDOW_MIN_HEIGHT = 600;
const APP_USER_MODEL_ID = "com.tencent.qclaw";
const LOG_RETENTION_DAYS = 30;
const LOG_SUBDIRS = ["main", "renderer", "openclaw", "crash"];
const LOG_BUFFER_CAPACITY = 500;
const TRAY_TOOLTIP = "QClaw";
const CRASH_REPORT_DIR_NAME = "crash";
const CRASH_REPORT_MAX_COUNT = 50;
const GPU_DEGRADATION_FLAG_FILE = "gpu-degradation.flag.json";
const BOOT_IN_PROGRESS_FLAG_FILE = "boot-in-progress.flag";
const RENDERER_RELOAD_MAX_RETRIES = 3;
const RENDERER_RELOAD_WINDOW_MS = 6e4;
const RENDERER_RELOAD_DELAY_MS = 500;
mainLogger.initialize();
const isDev = !app.isPackaged;
const rendererLogger = mainLogger.create({ logId: "renderer" });
const openclawLogger = mainLogger.create({ logId: "openclaw" });
if (isDev) {
  mainLogger.transports.file.level = false;
  rendererLogger.transports.file.level = false;
  openclawLogger.transports.file.level = false;
} else {
  let getTodayDate = function() {
    return (/* @__PURE__ */ new Date()).toISOString().slice(0, 10);
  }, dailyLogPath = function(subdir) {
    return path.join(logsDir, subdir, `${getTodayDate()}.log`);
  }, cleanExpiredLogs = function() {
    const cutoff = Date.now() - LOG_RETENTION_DAYS * 24 * 60 * 60 * 1e3;
    for (const subdir of LOG_SUBDIRS) {
      const dir = path.join(logsDir, subdir);
      if (!fs.existsSync(dir)) continue;
      try {
        const files = fs.readdirSync(dir);
        for (const file2 of files) {
          const match = file2.match(/^(\d{4}-\d{2}-\d{2})\.log$/);
          if (!match) continue;
          const fileDate = new Date(match[1]).getTime();
          if (fileDate < cutoff) {
            fs.unlinkSync(path.join(dir, file2));
          }
        }
      } catch {
      }
    }
  };
  const logsDir = app.getPath("logs");
  mainLogger.transports.file.resolvePathFn = () => dailyLogPath("main");
  rendererLogger.transports.file.resolvePathFn = () => dailyLogPath("renderer");
  openclawLogger.transports.file.resolvePathFn = () => dailyLogPath("openclaw");
  cleanExpiredLogs();
}
const LOCALHOST_ADDRESS = "127.0.0.1";
const APP_STORE_FILE_NAME = "app-store.json";
const OPENCLAW_STATE_DIR_NAME = ".qclaw";
const OPENCLAW_EXTERNAL_STATE_DIR_NAME = ".openclaw";
const OPENCLAW_CONFIG_FILE_NAME = "openclaw.json";
const OPENCLAW_GATEWAY_PORT_DEFAULT = 28789;
const OPENCLAW_EXTERNAL_GATEWAY_PORT_DEFAULT = 18789;
function resolveStateDir() {
  if (process.env.OPENCLAW_STATE_DIR) {
    return process.env.OPENCLAW_STATE_DIR;
  }
  return path.join(os.homedir(), OPENCLAW_STATE_DIR_NAME);
}
const OPENCLAW_STATE_DIR = resolveStateDir();
const OPENCLAW_CONFIG_PATH = process.env.OPENCLAW_CONFIG_PATH ?? path.join(OPENCLAW_STATE_DIR, OPENCLAW_CONFIG_FILE_NAME);
const OPENCLAW_BACKUP_DIR = path.join(path.dirname(OPENCLAW_CONFIG_PATH), "backups");
const OPENCLAW_DEFAULT_GATEWAY_PORT = process.env.OPENCLAW_GATEWAY_PORT ? Number(process.env.OPENCLAW_GATEWAY_PORT) : OPENCLAW_GATEWAY_PORT_DEFAULT;
const OPENCLAW_HEALTH_WAIT_RETRIES = 300;
const OPENCLAW_HEALTH_WAIT_INTERVAL = 2e3;
const OPENCLAW_STARTUP_TIMEOUT = 3e4;
const OPENCLAW_SHUTDOWN_TIMEOUT = 5e3;
const RESTART_DELAY_MS = 100;
const NODE_OPTIONS_VALUE = "--no-warnings";
const ENV_VALUE_ENABLED = "1";
const OPENCLAW_CLAWHUB_SKILLS_EXTRA_DIRS = [
  "~/.openclaw/skills",
  "~/.openclaw/workspace/skills",
  "~/.agents/skills"
];
const OPENCLAW_EXTERNAL_PLUGIN_EXTRA_DIRS = [
  "~/.openclaw/extensions"
];
const FORCED_CLEANUP_EXTENSIONS = [
  "tencent-access"
];
const BUNDLED_PATH_SUFFIXES = [
  path.join("openclaw", "config", "extensions"),
  path.join("openclaw", "config", "skills")
];
const OPENCLAW_ENTRY_FILE = "openclaw.mjs";
const QCLAW_META_FILE_NAME = "qclaw.json";
const OPENCLAW_COMMAND_GATEWAY = "gateway";
const WORKSPACE_DIR_NAME = "workspace";
const AUTH_TOKEN_BYTES = 24;
const INSTANCE_DETECTION_TIMEOUT_MS = 3e3;
const INSTANCE_RETRY_DETECTION_MAX_ATTEMPTS = 10;
const INSTANCE_RETRY_DETECTION_INTERVAL_MS = 3e3;
const EXTERNAL_MONITOR_POLL_INTERVAL_MS = 3e4;
const ELECTRON_REQUIRED_ORIGINS = ["file://", "null"];
const STORE_KEY_INSTANCE_MODE = "instanceMode";
const PROTECTED_CONFIG_PATHS = [
  "gateway",
  // 网关配置整体（端口、认证、绑定、tailscale 等）
  "models.providers.qclaw.apiKey",
  // 用户认证凭证
  "channels.wechat-access.token",
  // 微信登录 token
  "agents.defaults.workspace",
  // 用户工作空间路径
  "agents.defaults.model.primary",
  // 用户可能自定义模型
  "skills.load.extraDirs",
  // 由 ensureExternalExtraDirs / ensureBundledPaths 独立管理
  "plugins.load.paths"
  // 同上，避免模板空数组覆盖用户自行添加的路径
];
function getOpenClawPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "openclaw", "node_modules", "openclaw");
  }
  const appPath = app.getAppPath();
  return path.join(appPath, "resources", "openclaw", "node_modules", "openclaw");
}
function getExecNodePath() {
  if (process.platform === "darwin") {
    const helperPath = getMacHelperPath();
    if (helperPath && fs.existsSync(helperPath)) {
      return helperPath;
    }
  }
  return process.execPath;
}
function getMacHelperPath() {
  const execPath = process.execPath;
  const appName = path.basename(execPath);
  const macOSDir = path.dirname(execPath);
  const contentsDir = path.dirname(macOSDir);
  const helperAppName = `${appName} Helper`;
  return path.join(
    contentsDir,
    "Frameworks",
    `${helperAppName}.app`,
    "Contents",
    "MacOS",
    helperAppName
  );
}
function getConfigPath() {
  return OPENCLAW_CONFIG_PATH;
}
function getDefaultConfigSourcePath() {
  return path.join(getBundledConfigDir(), OPENCLAW_CONFIG_FILE_NAME);
}
function getBundledConfigDir() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "openclaw", "config");
  }
  const appPath = app.getAppPath();
  return path.join(appPath, "resources", "openclaw", "config");
}
function getBundledExtensionsDir() {
  return path.join(getBundledConfigDir(), "extensions");
}
function getBundledSkillsDir() {
  return path.join(getBundledConfigDir(), "skills");
}
function getOpenClawEntryPath() {
  return path.join(getOpenClawPath(), OPENCLAW_ENTRY_FILE);
}
function $constructor(name, initializer2, params) {
  function init(inst, def) {
    if (!inst._zod) {
      Object.defineProperty(inst, "_zod", {
        value: {
          def,
          constr: _,
          traits: /* @__PURE__ */ new Set()
        },
        enumerable: false
      });
    }
    if (inst._zod.traits.has(name)) {
      return;
    }
    inst._zod.traits.add(name);
    initializer2(inst, def);
    const proto = _.prototype;
    const keys = Object.keys(proto);
    for (let i = 0; i < keys.length; i++) {
      const k = keys[i];
      if (!(k in inst)) {
        inst[k] = proto[k].bind(inst);
      }
    }
  }
  const Parent = params?.Parent ?? Object;
  class Definition extends Parent {
  }
  Object.defineProperty(Definition, "name", { value: name });
  function _(def) {
    var _a2;
    const inst = params?.Parent ? new Definition() : this;
    init(inst, def);
    (_a2 = inst._zod).deferred ?? (_a2.deferred = []);
    for (const fn of inst._zod.deferred) {
      fn();
    }
    return inst;
  }
  Object.defineProperty(_, "init", { value: init });
  Object.defineProperty(_, Symbol.hasInstance, {
    value: (inst) => {
      if (params?.Parent && inst instanceof params.Parent)
        return true;
      return inst?._zod?.traits?.has(name);
    }
  });
  Object.defineProperty(_, "name", { value: name });
  return _;
}
class $ZodAsyncError extends Error {
  constructor() {
    super(`Encountered Promise during synchronous parse. Use .parseAsync() instead.`);
  }
}
class $ZodEncodeError extends Error {
  constructor(name) {
    super(`Encountered unidirectional transform during encode: ${name}`);
    this.name = "ZodEncodeError";
  }
}
const globalConfig = {};
function config(newConfig) {
  return globalConfig;
}
function getEnumValues(entries) {
  const numericValues = Object.values(entries).filter((v) => typeof v === "number");
  const values = Object.entries(entries).filter(([k, _]) => numericValues.indexOf(+k) === -1).map(([_, v]) => v);
  return values;
}
function jsonStringifyReplacer(_, value) {
  if (typeof value === "bigint")
    return value.toString();
  return value;
}
function cached(getter) {
  return {
    get value() {
      {
        const value = getter();
        Object.defineProperty(this, "value", { value });
        return value;
      }
    }
  };
}
function nullish(input) {
  return input === null || input === void 0;
}
function cleanRegex(source) {
  const start = source.startsWith("^") ? 1 : 0;
  const end = source.endsWith("$") ? source.length - 1 : source.length;
  return source.slice(start, end);
}
function floatSafeRemainder(val, step) {
  const valDecCount = (val.toString().split(".")[1] || "").length;
  const stepString = step.toString();
  let stepDecCount = (stepString.split(".")[1] || "").length;
  if (stepDecCount === 0 && /\d?e-\d?/.test(stepString)) {
    const match = stepString.match(/\d?e-(\d?)/);
    if (match?.[1]) {
      stepDecCount = Number.parseInt(match[1]);
    }
  }
  const decCount = valDecCount > stepDecCount ? valDecCount : stepDecCount;
  const valInt = Number.parseInt(val.toFixed(decCount).replace(".", ""));
  const stepInt = Number.parseInt(step.toFixed(decCount).replace(".", ""));
  return valInt % stepInt / 10 ** decCount;
}
const EVALUATING = Symbol("evaluating");
function defineLazy(object2, key, getter) {
  let value = void 0;
  Object.defineProperty(object2, key, {
    get() {
      if (value === EVALUATING) {
        return void 0;
      }
      if (value === void 0) {
        value = EVALUATING;
        value = getter();
      }
      return value;
    },
    set(v) {
      Object.defineProperty(object2, key, {
        value: v
        // configurable: true,
      });
    },
    configurable: true
  });
}
function assignProp(target, prop, value) {
  Object.defineProperty(target, prop, {
    value,
    writable: true,
    enumerable: true,
    configurable: true
  });
}
function mergeDefs(...defs) {
  const mergedDescriptors = {};
  for (const def of defs) {
    const descriptors = Object.getOwnPropertyDescriptors(def);
    Object.assign(mergedDescriptors, descriptors);
  }
  return Object.defineProperties({}, mergedDescriptors);
}
function esc(str) {
  return JSON.stringify(str);
}
function slugify(input) {
  return input.toLowerCase().trim().replace(/[^\w\s-]/g, "").replace(/[\s_-]+/g, "-").replace(/^-+|-+$/g, "");
}
const captureStackTrace = "captureStackTrace" in Error ? Error.captureStackTrace : (..._args) => {
};
function isObject(data) {
  return typeof data === "object" && data !== null && !Array.isArray(data);
}
const allowsEval = cached(() => {
  if (typeof navigator !== "undefined" && navigator?.userAgent?.includes("Cloudflare")) {
    return false;
  }
  try {
    const F = Function;
    new F("");
    return true;
  } catch (_) {
    return false;
  }
});
function isPlainObject$1(o) {
  if (isObject(o) === false)
    return false;
  const ctor = o.constructor;
  if (ctor === void 0)
    return true;
  if (typeof ctor !== "function")
    return true;
  const prot = ctor.prototype;
  if (isObject(prot) === false)
    return false;
  if (Object.prototype.hasOwnProperty.call(prot, "isPrototypeOf") === false) {
    return false;
  }
  return true;
}
function shallowClone(o) {
  if (isPlainObject$1(o))
    return { ...o };
  if (Array.isArray(o))
    return [...o];
  return o;
}
const propertyKeyTypes = /* @__PURE__ */ new Set(["string", "number", "symbol"]);
function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function clone(inst, def, params) {
  const cl = new inst._zod.constr(def ?? inst._zod.def);
  if (!def || params?.parent)
    cl._zod.parent = inst;
  return cl;
}
function normalizeParams(_params) {
  const params = _params;
  if (!params)
    return {};
  if (typeof params === "string")
    return { error: () => params };
  if (params?.message !== void 0) {
    if (params?.error !== void 0)
      throw new Error("Cannot specify both `message` and `error` params");
    params.error = params.message;
  }
  delete params.message;
  if (typeof params.error === "string")
    return { ...params, error: () => params.error };
  return params;
}
function optionalKeys(shape) {
  return Object.keys(shape).filter((k) => {
    return shape[k]._zod.optin === "optional" && shape[k]._zod.optout === "optional";
  });
}
const NUMBER_FORMAT_RANGES = {
  safeint: [Number.MIN_SAFE_INTEGER, Number.MAX_SAFE_INTEGER],
  int32: [-2147483648, 2147483647],
  uint32: [0, 4294967295],
  float32: [-34028234663852886e22, 34028234663852886e22],
  float64: [-Number.MAX_VALUE, Number.MAX_VALUE]
};
function pick(schema, mask) {
  const currDef = schema._zod.def;
  const checks = currDef.checks;
  const hasChecks = checks && checks.length > 0;
  if (hasChecks) {
    throw new Error(".pick() cannot be used on object schemas containing refinements");
  }
  const def = mergeDefs(schema._zod.def, {
    get shape() {
      const newShape = {};
      for (const key in mask) {
        if (!(key in currDef.shape)) {
          throw new Error(`Unrecognized key: "${key}"`);
        }
        if (!mask[key])
          continue;
        newShape[key] = currDef.shape[key];
      }
      assignProp(this, "shape", newShape);
      return newShape;
    },
    checks: []
  });
  return clone(schema, def);
}
function omit(schema, mask) {
  const currDef = schema._zod.def;
  const checks = currDef.checks;
  const hasChecks = checks && checks.length > 0;
  if (hasChecks) {
    throw new Error(".omit() cannot be used on object schemas containing refinements");
  }
  const def = mergeDefs(schema._zod.def, {
    get shape() {
      const newShape = { ...schema._zod.def.shape };
      for (const key in mask) {
        if (!(key in currDef.shape)) {
          throw new Error(`Unrecognized key: "${key}"`);
        }
        if (!mask[key])
          continue;
        delete newShape[key];
      }
      assignProp(this, "shape", newShape);
      return newShape;
    },
    checks: []
  });
  return clone(schema, def);
}
function extend(schema, shape) {
  if (!isPlainObject$1(shape)) {
    throw new Error("Invalid input to extend: expected a plain object");
  }
  const checks = schema._zod.def.checks;
  const hasChecks = checks && checks.length > 0;
  if (hasChecks) {
    const existingShape = schema._zod.def.shape;
    for (const key in shape) {
      if (Object.getOwnPropertyDescriptor(existingShape, key) !== void 0) {
        throw new Error("Cannot overwrite keys on object schemas containing refinements. Use `.safeExtend()` instead.");
      }
    }
  }
  const def = mergeDefs(schema._zod.def, {
    get shape() {
      const _shape = { ...schema._zod.def.shape, ...shape };
      assignProp(this, "shape", _shape);
      return _shape;
    }
  });
  return clone(schema, def);
}
function safeExtend(schema, shape) {
  if (!isPlainObject$1(shape)) {
    throw new Error("Invalid input to safeExtend: expected a plain object");
  }
  const def = mergeDefs(schema._zod.def, {
    get shape() {
      const _shape = { ...schema._zod.def.shape, ...shape };
      assignProp(this, "shape", _shape);
      return _shape;
    }
  });
  return clone(schema, def);
}
function merge(a, b) {
  const def = mergeDefs(a._zod.def, {
    get shape() {
      const _shape = { ...a._zod.def.shape, ...b._zod.def.shape };
      assignProp(this, "shape", _shape);
      return _shape;
    },
    get catchall() {
      return b._zod.def.catchall;
    },
    checks: []
    // delete existing checks
  });
  return clone(a, def);
}
function partial(Class, schema, mask) {
  const currDef = schema._zod.def;
  const checks = currDef.checks;
  const hasChecks = checks && checks.length > 0;
  if (hasChecks) {
    throw new Error(".partial() cannot be used on object schemas containing refinements");
  }
  const def = mergeDefs(schema._zod.def, {
    get shape() {
      const oldShape = schema._zod.def.shape;
      const shape = { ...oldShape };
      if (mask) {
        for (const key in mask) {
          if (!(key in oldShape)) {
            throw new Error(`Unrecognized key: "${key}"`);
          }
          if (!mask[key])
            continue;
          shape[key] = Class ? new Class({
            type: "optional",
            innerType: oldShape[key]
          }) : oldShape[key];
        }
      } else {
        for (const key in oldShape) {
          shape[key] = Class ? new Class({
            type: "optional",
            innerType: oldShape[key]
          }) : oldShape[key];
        }
      }
      assignProp(this, "shape", shape);
      return shape;
    },
    checks: []
  });
  return clone(schema, def);
}
function required(Class, schema, mask) {
  const def = mergeDefs(schema._zod.def, {
    get shape() {
      const oldShape = schema._zod.def.shape;
      const shape = { ...oldShape };
      if (mask) {
        for (const key in mask) {
          if (!(key in shape)) {
            throw new Error(`Unrecognized key: "${key}"`);
          }
          if (!mask[key])
            continue;
          shape[key] = new Class({
            type: "nonoptional",
            innerType: oldShape[key]
          });
        }
      } else {
        for (const key in oldShape) {
          shape[key] = new Class({
            type: "nonoptional",
            innerType: oldShape[key]
          });
        }
      }
      assignProp(this, "shape", shape);
      return shape;
    }
  });
  return clone(schema, def);
}
function aborted(x, startIndex = 0) {
  if (x.aborted === true)
    return true;
  for (let i = startIndex; i < x.issues.length; i++) {
    if (x.issues[i]?.continue !== true) {
      return true;
    }
  }
  return false;
}
function prefixIssues(path2, issues) {
  return issues.map((iss) => {
    var _a2;
    (_a2 = iss).path ?? (_a2.path = []);
    iss.path.unshift(path2);
    return iss;
  });
}
function unwrapMessage(message) {
  return typeof message === "string" ? message : message?.message;
}
function finalizeIssue(iss, ctx, config2) {
  const full = { ...iss, path: iss.path ?? [] };
  if (!iss.message) {
    const message = unwrapMessage(iss.inst?._zod.def?.error?.(iss)) ?? unwrapMessage(ctx?.error?.(iss)) ?? unwrapMessage(config2.customError?.(iss)) ?? unwrapMessage(config2.localeError?.(iss)) ?? "Invalid input";
    full.message = message;
  }
  delete full.inst;
  delete full.continue;
  if (!ctx?.reportInput) {
    delete full.input;
  }
  return full;
}
function getLengthableOrigin(input) {
  if (Array.isArray(input))
    return "array";
  if (typeof input === "string")
    return "string";
  return "unknown";
}
function issue(...args) {
  const [iss, input, inst] = args;
  if (typeof iss === "string") {
    return {
      message: iss,
      code: "custom",
      input,
      inst
    };
  }
  return { ...iss };
}
const initializer$1 = (inst, def) => {
  inst.name = "$ZodError";
  Object.defineProperty(inst, "_zod", {
    value: inst._zod,
    enumerable: false
  });
  Object.defineProperty(inst, "issues", {
    value: def,
    enumerable: false
  });
  inst.message = JSON.stringify(def, jsonStringifyReplacer, 2);
  Object.defineProperty(inst, "toString", {
    value: () => inst.message,
    enumerable: false
  });
};
const $ZodError = $constructor("$ZodError", initializer$1);
const $ZodRealError = $constructor("$ZodError", initializer$1, { Parent: Error });
function flattenError(error, mapper = (issue2) => issue2.message) {
  const fieldErrors = {};
  const formErrors = [];
  for (const sub of error.issues) {
    if (sub.path.length > 0) {
      fieldErrors[sub.path[0]] = fieldErrors[sub.path[0]] || [];
      fieldErrors[sub.path[0]].push(mapper(sub));
    } else {
      formErrors.push(mapper(sub));
    }
  }
  return { formErrors, fieldErrors };
}
function formatError(error, mapper = (issue2) => issue2.message) {
  const fieldErrors = { _errors: [] };
  const processError = (error2) => {
    for (const issue2 of error2.issues) {
      if (issue2.code === "invalid_union" && issue2.errors.length) {
        issue2.errors.map((issues) => processError({ issues }));
      } else if (issue2.code === "invalid_key") {
        processError({ issues: issue2.issues });
      } else if (issue2.code === "invalid_element") {
        processError({ issues: issue2.issues });
      } else if (issue2.path.length === 0) {
        fieldErrors._errors.push(mapper(issue2));
      } else {
        let curr = fieldErrors;
        let i = 0;
        while (i < issue2.path.length) {
          const el = issue2.path[i];
          const terminal = i === issue2.path.length - 1;
          if (!terminal) {
            curr[el] = curr[el] || { _errors: [] };
          } else {
            curr[el] = curr[el] || { _errors: [] };
            curr[el]._errors.push(mapper(issue2));
          }
          curr = curr[el];
          i++;
        }
      }
    }
  };
  processError(error);
  return fieldErrors;
}
const _parse = (_Err) => (schema, value, _ctx, _params) => {
  const ctx = _ctx ? Object.assign(_ctx, { async: false }) : { async: false };
  const result = schema._zod.run({ value, issues: [] }, ctx);
  if (result instanceof Promise) {
    throw new $ZodAsyncError();
  }
  if (result.issues.length) {
    const e = new (_params?.Err ?? _Err)(result.issues.map((iss) => finalizeIssue(iss, ctx, config())));
    captureStackTrace(e, _params?.callee);
    throw e;
  }
  return result.value;
};
const _parseAsync = (_Err) => async (schema, value, _ctx, params) => {
  const ctx = _ctx ? Object.assign(_ctx, { async: true }) : { async: true };
  let result = schema._zod.run({ value, issues: [] }, ctx);
  if (result instanceof Promise)
    result = await result;
  if (result.issues.length) {
    const e = new (params?.Err ?? _Err)(result.issues.map((iss) => finalizeIssue(iss, ctx, config())));
    captureStackTrace(e, params?.callee);
    throw e;
  }
  return result.value;
};
const _safeParse = (_Err) => (schema, value, _ctx) => {
  const ctx = _ctx ? { ..._ctx, async: false } : { async: false };
  const result = schema._zod.run({ value, issues: [] }, ctx);
  if (result instanceof Promise) {
    throw new $ZodAsyncError();
  }
  return result.issues.length ? {
    success: false,
    error: new (_Err ?? $ZodError)(result.issues.map((iss) => finalizeIssue(iss, ctx, config())))
  } : { success: true, data: result.value };
};
const safeParse$1 = /* @__PURE__ */ _safeParse($ZodRealError);
const _safeParseAsync = (_Err) => async (schema, value, _ctx) => {
  const ctx = _ctx ? Object.assign(_ctx, { async: true }) : { async: true };
  let result = schema._zod.run({ value, issues: [] }, ctx);
  if (result instanceof Promise)
    result = await result;
  return result.issues.length ? {
    success: false,
    error: new _Err(result.issues.map((iss) => finalizeIssue(iss, ctx, config())))
  } : { success: true, data: result.value };
};
const safeParseAsync$1 = /* @__PURE__ */ _safeParseAsync($ZodRealError);
const _encode = (_Err) => (schema, value, _ctx) => {
  const ctx = _ctx ? Object.assign(_ctx, { direction: "backward" }) : { direction: "backward" };
  return _parse(_Err)(schema, value, ctx);
};
const _decode = (_Err) => (schema, value, _ctx) => {
  return _parse(_Err)(schema, value, _ctx);
};
const _encodeAsync = (_Err) => async (schema, value, _ctx) => {
  const ctx = _ctx ? Object.assign(_ctx, { direction: "backward" }) : { direction: "backward" };
  return _parseAsync(_Err)(schema, value, ctx);
};
const _decodeAsync = (_Err) => async (schema, value, _ctx) => {
  return _parseAsync(_Err)(schema, value, _ctx);
};
const _safeEncode = (_Err) => (schema, value, _ctx) => {
  const ctx = _ctx ? Object.assign(_ctx, { direction: "backward" }) : { direction: "backward" };
  return _safeParse(_Err)(schema, value, ctx);
};
const _safeDecode = (_Err) => (schema, value, _ctx) => {
  return _safeParse(_Err)(schema, value, _ctx);
};
const _safeEncodeAsync = (_Err) => async (schema, value, _ctx) => {
  const ctx = _ctx ? Object.assign(_ctx, { direction: "backward" }) : { direction: "backward" };
  return _safeParseAsync(_Err)(schema, value, ctx);
};
const _safeDecodeAsync = (_Err) => async (schema, value, _ctx) => {
  return _safeParseAsync(_Err)(schema, value, _ctx);
};
const cuid = /^[cC][^\s-]{8,}$/;
const cuid2 = /^[0-9a-z]+$/;
const ulid = /^[0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{26}$/;
const xid = /^[0-9a-vA-V]{20}$/;
const ksuid = /^[A-Za-z0-9]{27}$/;
const nanoid = /^[a-zA-Z0-9_-]{21}$/;
const duration$1 = /^P(?:(\d+W)|(?!.*W)(?=\d|T\d)(\d+Y)?(\d+M)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+([.,]\d+)?S)?)?)$/;
const guid = /^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$/;
const uuid = (version2) => {
  if (!version2)
    return /^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|00000000-0000-0000-0000-000000000000|ffffffff-ffff-ffff-ffff-ffffffffffff)$/;
  return new RegExp(`^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-${version2}[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12})$`);
};
const email = /^(?!\.)(?!.*\.\.)([A-Za-z0-9_'+\-\.]*)[A-Za-z0-9_+-]@([A-Za-z0-9][A-Za-z0-9\-]*\.)+[A-Za-z]{2,}$/;
const _emoji$1 = `^(\\p{Extended_Pictographic}|\\p{Emoji_Component})+$`;
function emoji() {
  return new RegExp(_emoji$1, "u");
}
const ipv4 = /^(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])$/;
const ipv6 = /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})|:((:[0-9a-fA-F]{1,4}){1,7}|:))$/;
const cidrv4 = /^((25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])\/([0-9]|[1-2][0-9]|3[0-2])$/;
const cidrv6 = /^(([0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}|::|([0-9a-fA-F]{1,4})?::([0-9a-fA-F]{1,4}:?){0,6})\/(12[0-8]|1[01][0-9]|[1-9]?[0-9])$/;
const base64 = /^$|^(?:[0-9a-zA-Z+/]{4})*(?:(?:[0-9a-zA-Z+/]{2}==)|(?:[0-9a-zA-Z+/]{3}=))?$/;
const base64url = /^[A-Za-z0-9_-]*$/;
const e164 = /^\+[1-9]\d{6,14}$/;
const dateSource = `(?:(?:\\d\\d[2468][048]|\\d\\d[13579][26]|\\d\\d0[48]|[02468][048]00|[13579][26]00)-02-29|\\d{4}-(?:(?:0[13578]|1[02])-(?:0[1-9]|[12]\\d|3[01])|(?:0[469]|11)-(?:0[1-9]|[12]\\d|30)|(?:02)-(?:0[1-9]|1\\d|2[0-8])))`;
const date$1 = /* @__PURE__ */ new RegExp(`^${dateSource}$`);
function timeSource(args) {
  const hhmm = `(?:[01]\\d|2[0-3]):[0-5]\\d`;
  const regex = typeof args.precision === "number" ? args.precision === -1 ? `${hhmm}` : args.precision === 0 ? `${hhmm}:[0-5]\\d` : `${hhmm}:[0-5]\\d\\.\\d{${args.precision}}` : `${hhmm}(?::[0-5]\\d(?:\\.\\d+)?)?`;
  return regex;
}
function time$1(args) {
  return new RegExp(`^${timeSource(args)}$`);
}
function datetime$1(args) {
  const time2 = timeSource({ precision: args.precision });
  const opts = ["Z"];
  if (args.local)
    opts.push("");
  if (args.offset)
    opts.push(`([+-](?:[01]\\d|2[0-3]):[0-5]\\d)`);
  const timeRegex = `${time2}(?:${opts.join("|")})`;
  return new RegExp(`^${dateSource}T(?:${timeRegex})$`);
}
const string$1 = (params) => {
  const regex = params ? `[\\s\\S]{${params?.minimum ?? 0},${params?.maximum ?? ""}}` : `[\\s\\S]*`;
  return new RegExp(`^${regex}$`);
};
const integer = /^-?\d+$/;
const number$1 = /^-?\d+(?:\.\d+)?$/;
const boolean$1 = /^(?:true|false)$/i;
const lowercase = /^[^A-Z]*$/;
const uppercase = /^[^a-z]*$/;
import __cjs_mod__ from "node:module";
const __filename = import.meta.filename;
const __dirname = import.meta.dirname;
const require2 = __cjs_mod__.createRequire(import.meta.url);
const $ZodCheck = /* @__PURE__ */ $constructor("$ZodCheck", (inst, def) => {
  var _a2;
  inst._zod ?? (inst._zod = {});
  inst._zod.def = def;
  (_a2 = inst._zod).onattach ?? (_a2.onattach = []);
});
const numericOriginMap = {
  number: "number",
  bigint: "bigint",
  object: "date"
};
const $ZodCheckLessThan = /* @__PURE__ */ $constructor("$ZodCheckLessThan", (inst, def) => {
  $ZodCheck.init(inst, def);
  const origin = numericOriginMap[typeof def.value];
  inst._zod.onattach.push((inst2) => {
    const bag = inst2._zod.bag;
    const curr = (def.inclusive ? bag.maximum : bag.exclusiveMaximum) ?? Number.POSITIVE_INFINITY;
    if (def.value < curr) {
      if (def.inclusive)
        bag.maximum = def.value;
      else
        bag.exclusiveMaximum = def.value;
    }
  });
  inst._zod.check = (payload) => {
    if (def.inclusive ? payload.value <= def.value : payload.value < def.value) {
      return;
    }
    payload.issues.push({
      origin,
      code: "too_big",
      maximum: typeof def.value === "object" ? def.value.getTime() : def.value,
      input: payload.value,
      inclusive: def.inclusive,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckGreaterThan = /* @__PURE__ */ $constructor("$ZodCheckGreaterThan", (inst, def) => {
  $ZodCheck.init(inst, def);
  const origin = numericOriginMap[typeof def.value];
  inst._zod.onattach.push((inst2) => {
    const bag = inst2._zod.bag;
    const curr = (def.inclusive ? bag.minimum : bag.exclusiveMinimum) ?? Number.NEGATIVE_INFINITY;
    if (def.value > curr) {
      if (def.inclusive)
        bag.minimum = def.value;
      else
        bag.exclusiveMinimum = def.value;
    }
  });
  inst._zod.check = (payload) => {
    if (def.inclusive ? payload.value >= def.value : payload.value > def.value) {
      return;
    }
    payload.issues.push({
      origin,
      code: "too_small",
      minimum: typeof def.value === "object" ? def.value.getTime() : def.value,
      input: payload.value,
      inclusive: def.inclusive,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckMultipleOf = /* @__PURE__ */ $constructor("$ZodCheckMultipleOf", (inst, def) => {
  $ZodCheck.init(inst, def);
  inst._zod.onattach.push((inst2) => {
    var _a2;
    (_a2 = inst2._zod.bag).multipleOf ?? (_a2.multipleOf = def.value);
  });
  inst._zod.check = (payload) => {
    if (typeof payload.value !== typeof def.value)
      throw new Error("Cannot mix number and bigint in multiple_of check.");
    const isMultiple = typeof payload.value === "bigint" ? payload.value % def.value === BigInt(0) : floatSafeRemainder(payload.value, def.value) === 0;
    if (isMultiple)
      return;
    payload.issues.push({
      origin: typeof payload.value,
      code: "not_multiple_of",
      divisor: def.value,
      input: payload.value,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckNumberFormat = /* @__PURE__ */ $constructor("$ZodCheckNumberFormat", (inst, def) => {
  $ZodCheck.init(inst, def);
  def.format = def.format || "float64";
  const isInt = def.format?.includes("int");
  const origin = isInt ? "int" : "number";
  const [minimum, maximum] = NUMBER_FORMAT_RANGES[def.format];
  inst._zod.onattach.push((inst2) => {
    const bag = inst2._zod.bag;
    bag.format = def.format;
    bag.minimum = minimum;
    bag.maximum = maximum;
    if (isInt)
      bag.pattern = integer;
  });
  inst._zod.check = (payload) => {
    const input = payload.value;
    if (isInt) {
      if (!Number.isInteger(input)) {
        payload.issues.push({
          expected: origin,
          format: def.format,
          code: "invalid_type",
          continue: false,
          input,
          inst
        });
        return;
      }
      if (!Number.isSafeInteger(input)) {
        if (input > 0) {
          payload.issues.push({
            input,
            code: "too_big",
            maximum: Number.MAX_SAFE_INTEGER,
            note: "Integers must be within the safe integer range.",
            inst,
            origin,
            inclusive: true,
            continue: !def.abort
          });
        } else {
          payload.issues.push({
            input,
            code: "too_small",
            minimum: Number.MIN_SAFE_INTEGER,
            note: "Integers must be within the safe integer range.",
            inst,
            origin,
            inclusive: true,
            continue: !def.abort
          });
        }
        return;
      }
    }
    if (input < minimum) {
      payload.issues.push({
        origin: "number",
        input,
        code: "too_small",
        minimum,
        inclusive: true,
        inst,
        continue: !def.abort
      });
    }
    if (input > maximum) {
      payload.issues.push({
        origin: "number",
        input,
        code: "too_big",
        maximum,
        inclusive: true,
        inst,
        continue: !def.abort
      });
    }
  };
});
const $ZodCheckMaxLength = /* @__PURE__ */ $constructor("$ZodCheckMaxLength", (inst, def) => {
  var _a2;
  $ZodCheck.init(inst, def);
  (_a2 = inst._zod.def).when ?? (_a2.when = (payload) => {
    const val = payload.value;
    return !nullish(val) && val.length !== void 0;
  });
  inst._zod.onattach.push((inst2) => {
    const curr = inst2._zod.bag.maximum ?? Number.POSITIVE_INFINITY;
    if (def.maximum < curr)
      inst2._zod.bag.maximum = def.maximum;
  });
  inst._zod.check = (payload) => {
    const input = payload.value;
    const length = input.length;
    if (length <= def.maximum)
      return;
    const origin = getLengthableOrigin(input);
    payload.issues.push({
      origin,
      code: "too_big",
      maximum: def.maximum,
      inclusive: true,
      input,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckMinLength = /* @__PURE__ */ $constructor("$ZodCheckMinLength", (inst, def) => {
  var _a2;
  $ZodCheck.init(inst, def);
  (_a2 = inst._zod.def).when ?? (_a2.when = (payload) => {
    const val = payload.value;
    return !nullish(val) && val.length !== void 0;
  });
  inst._zod.onattach.push((inst2) => {
    const curr = inst2._zod.bag.minimum ?? Number.NEGATIVE_INFINITY;
    if (def.minimum > curr)
      inst2._zod.bag.minimum = def.minimum;
  });
  inst._zod.check = (payload) => {
    const input = payload.value;
    const length = input.length;
    if (length >= def.minimum)
      return;
    const origin = getLengthableOrigin(input);
    payload.issues.push({
      origin,
      code: "too_small",
      minimum: def.minimum,
      inclusive: true,
      input,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckLengthEquals = /* @__PURE__ */ $constructor("$ZodCheckLengthEquals", (inst, def) => {
  var _a2;
  $ZodCheck.init(inst, def);
  (_a2 = inst._zod.def).when ?? (_a2.when = (payload) => {
    const val = payload.value;
    return !nullish(val) && val.length !== void 0;
  });
  inst._zod.onattach.push((inst2) => {
    const bag = inst2._zod.bag;
    bag.minimum = def.length;
    bag.maximum = def.length;
    bag.length = def.length;
  });
  inst._zod.check = (payload) => {
    const input = payload.value;
    const length = input.length;
    if (length === def.length)
      return;
    const origin = getLengthableOrigin(input);
    const tooBig = length > def.length;
    payload.issues.push({
      origin,
      ...tooBig ? { code: "too_big", maximum: def.length } : { code: "too_small", minimum: def.length },
      inclusive: true,
      exact: true,
      input: payload.value,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckStringFormat = /* @__PURE__ */ $constructor("$ZodCheckStringFormat", (inst, def) => {
  var _a2, _b;
  $ZodCheck.init(inst, def);
  inst._zod.onattach.push((inst2) => {
    const bag = inst2._zod.bag;
    bag.format = def.format;
    if (def.pattern) {
      bag.patterns ?? (bag.patterns = /* @__PURE__ */ new Set());
      bag.patterns.add(def.pattern);
    }
  });
  if (def.pattern)
    (_a2 = inst._zod).check ?? (_a2.check = (payload) => {
      def.pattern.lastIndex = 0;
      if (def.pattern.test(payload.value))
        return;
      payload.issues.push({
        origin: "string",
        code: "invalid_format",
        format: def.format,
        input: payload.value,
        ...def.pattern ? { pattern: def.pattern.toString() } : {},
        inst,
        continue: !def.abort
      });
    });
  else
    (_b = inst._zod).check ?? (_b.check = () => {
    });
});
const $ZodCheckRegex = /* @__PURE__ */ $constructor("$ZodCheckRegex", (inst, def) => {
  $ZodCheckStringFormat.init(inst, def);
  inst._zod.check = (payload) => {
    def.pattern.lastIndex = 0;
    if (def.pattern.test(payload.value))
      return;
    payload.issues.push({
      origin: "string",
      code: "invalid_format",
      format: "regex",
      input: payload.value,
      pattern: def.pattern.toString(),
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckLowerCase = /* @__PURE__ */ $constructor("$ZodCheckLowerCase", (inst, def) => {
  def.pattern ?? (def.pattern = lowercase);
  $ZodCheckStringFormat.init(inst, def);
});
const $ZodCheckUpperCase = /* @__PURE__ */ $constructor("$ZodCheckUpperCase", (inst, def) => {
  def.pattern ?? (def.pattern = uppercase);
  $ZodCheckStringFormat.init(inst, def);
});
const $ZodCheckIncludes = /* @__PURE__ */ $constructor("$ZodCheckIncludes", (inst, def) => {
  $ZodCheck.init(inst, def);
  const escapedRegex = escapeRegex(def.includes);
  const pattern = new RegExp(typeof def.position === "number" ? `^.{${def.position}}${escapedRegex}` : escapedRegex);
  def.pattern = pattern;
  inst._zod.onattach.push((inst2) => {
    const bag = inst2._zod.bag;
    bag.patterns ?? (bag.patterns = /* @__PURE__ */ new Set());
    bag.patterns.add(pattern);
  });
  inst._zod.check = (payload) => {
    if (payload.value.includes(def.includes, def.position))
      return;
    payload.issues.push({
      origin: "string",
      code: "invalid_format",
      format: "includes",
      includes: def.includes,
      input: payload.value,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckStartsWith = /* @__PURE__ */ $constructor("$ZodCheckStartsWith", (inst, def) => {
  $ZodCheck.init(inst, def);
  const pattern = new RegExp(`^${escapeRegex(def.prefix)}.*`);
  def.pattern ?? (def.pattern = pattern);
  inst._zod.onattach.push((inst2) => {
    const bag = inst2._zod.bag;
    bag.patterns ?? (bag.patterns = /* @__PURE__ */ new Set());
    bag.patterns.add(pattern);
  });
  inst._zod.check = (payload) => {
    if (payload.value.startsWith(def.prefix))
      return;
    payload.issues.push({
      origin: "string",
      code: "invalid_format",
      format: "starts_with",
      prefix: def.prefix,
      input: payload.value,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckEndsWith = /* @__PURE__ */ $constructor("$ZodCheckEndsWith", (inst, def) => {
  $ZodCheck.init(inst, def);
  const pattern = new RegExp(`.*${escapeRegex(def.suffix)}$`);
  def.pattern ?? (def.pattern = pattern);
  inst._zod.onattach.push((inst2) => {
    const bag = inst2._zod.bag;
    bag.patterns ?? (bag.patterns = /* @__PURE__ */ new Set());
    bag.patterns.add(pattern);
  });
  inst._zod.check = (payload) => {
    if (payload.value.endsWith(def.suffix))
      return;
    payload.issues.push({
      origin: "string",
      code: "invalid_format",
      format: "ends_with",
      suffix: def.suffix,
      input: payload.value,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodCheckOverwrite = /* @__PURE__ */ $constructor("$ZodCheckOverwrite", (inst, def) => {
  $ZodCheck.init(inst, def);
  inst._zod.check = (payload) => {
    payload.value = def.tx(payload.value);
  };
});
class Doc {
  constructor(args = []) {
    this.content = [];
    this.indent = 0;
    if (this)
      this.args = args;
  }
  indented(fn) {
    this.indent += 1;
    fn(this);
    this.indent -= 1;
  }
  write(arg) {
    if (typeof arg === "function") {
      arg(this, { execution: "sync" });
      arg(this, { execution: "async" });
      return;
    }
    const content = arg;
    const lines = content.split("\n").filter((x) => x);
    const minIndent = Math.min(...lines.map((x) => x.length - x.trimStart().length));
    const dedented = lines.map((x) => x.slice(minIndent)).map((x) => " ".repeat(this.indent * 2) + x);
    for (const line of dedented) {
      this.content.push(line);
    }
  }
  compile() {
    const F = Function;
    const args = this?.args;
    const content = this?.content ?? [``];
    const lines = [...content.map((x) => `  ${x}`)];
    return new F(...args, lines.join("\n"));
  }
}
const version = {
  major: 4,
  minor: 3,
  patch: 6
};
const $ZodType = /* @__PURE__ */ $constructor("$ZodType", (inst, def) => {
  var _a2;
  inst ?? (inst = {});
  inst._zod.def = def;
  inst._zod.bag = inst._zod.bag || {};
  inst._zod.version = version;
  const checks = [...inst._zod.def.checks ?? []];
  if (inst._zod.traits.has("$ZodCheck")) {
    checks.unshift(inst);
  }
  for (const ch of checks) {
    for (const fn of ch._zod.onattach) {
      fn(inst);
    }
  }
  if (checks.length === 0) {
    (_a2 = inst._zod).deferred ?? (_a2.deferred = []);
    inst._zod.deferred?.push(() => {
      inst._zod.run = inst._zod.parse;
    });
  } else {
    const runChecks = (payload, checks2, ctx) => {
      let isAborted = aborted(payload);
      let asyncResult;
      for (const ch of checks2) {
        if (ch._zod.def.when) {
          const shouldRun = ch._zod.def.when(payload);
          if (!shouldRun)
            continue;
        } else if (isAborted) {
          continue;
        }
        const currLen = payload.issues.length;
        const _ = ch._zod.check(payload);
        if (_ instanceof Promise && ctx?.async === false) {
          throw new $ZodAsyncError();
        }
        if (asyncResult || _ instanceof Promise) {
          asyncResult = (asyncResult ?? Promise.resolve()).then(async () => {
            await _;
            const nextLen = payload.issues.length;
            if (nextLen === currLen)
              return;
            if (!isAborted)
              isAborted = aborted(payload, currLen);
          });
        } else {
          const nextLen = payload.issues.length;
          if (nextLen === currLen)
            continue;
          if (!isAborted)
            isAborted = aborted(payload, currLen);
        }
      }
      if (asyncResult) {
        return asyncResult.then(() => {
          return payload;
        });
      }
      return payload;
    };
    const handleCanaryResult = (canary, payload, ctx) => {
      if (aborted(canary)) {
        canary.aborted = true;
        return canary;
      }
      const checkResult = runChecks(payload, checks, ctx);
      if (checkResult instanceof Promise) {
        if (ctx.async === false)
          throw new $ZodAsyncError();
        return checkResult.then((checkResult2) => inst._zod.parse(checkResult2, ctx));
      }
      return inst._zod.parse(checkResult, ctx);
    };
    inst._zod.run = (payload, ctx) => {
      if (ctx.skipChecks) {
        return inst._zod.parse(payload, ctx);
      }
      if (ctx.direction === "backward") {
        const canary = inst._zod.parse({ value: payload.value, issues: [] }, { ...ctx, skipChecks: true });
        if (canary instanceof Promise) {
          return canary.then((canary2) => {
            return handleCanaryResult(canary2, payload, ctx);
          });
        }
        return handleCanaryResult(canary, payload, ctx);
      }
      const result = inst._zod.parse(payload, ctx);
      if (result instanceof Promise) {
        if (ctx.async === false)
          throw new $ZodAsyncError();
        return result.then((result2) => runChecks(result2, checks, ctx));
      }
      return runChecks(result, checks, ctx);
    };
  }
  defineLazy(inst, "~standard", () => ({
    validate: (value) => {
      try {
        const r = safeParse$1(inst, value);
        return r.success ? { value: r.data } : { issues: r.error?.issues };
      } catch (_) {
        return safeParseAsync$1(inst, value).then((r) => r.success ? { value: r.data } : { issues: r.error?.issues });
      }
    },
    vendor: "zod",
    version: 1
  }));
});
const $ZodString = /* @__PURE__ */ $constructor("$ZodString", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.pattern = [...inst?._zod.bag?.patterns ?? []].pop() ?? string$1(inst._zod.bag);
  inst._zod.parse = (payload, _) => {
    if (def.coerce)
      try {
        payload.value = String(payload.value);
      } catch (_2) {
      }
    if (typeof payload.value === "string")
      return payload;
    payload.issues.push({
      expected: "string",
      code: "invalid_type",
      input: payload.value,
      inst
    });
    return payload;
  };
});
const $ZodStringFormat = /* @__PURE__ */ $constructor("$ZodStringFormat", (inst, def) => {
  $ZodCheckStringFormat.init(inst, def);
  $ZodString.init(inst, def);
});
const $ZodGUID = /* @__PURE__ */ $constructor("$ZodGUID", (inst, def) => {
  def.pattern ?? (def.pattern = guid);
  $ZodStringFormat.init(inst, def);
});
const $ZodUUID = /* @__PURE__ */ $constructor("$ZodUUID", (inst, def) => {
  if (def.version) {
    const versionMap = {
      v1: 1,
      v2: 2,
      v3: 3,
      v4: 4,
      v5: 5,
      v6: 6,
      v7: 7,
      v8: 8
    };
    const v = versionMap[def.version];
    if (v === void 0)
      throw new Error(`Invalid UUID version: "${def.version}"`);
    def.pattern ?? (def.pattern = uuid(v));
  } else
    def.pattern ?? (def.pattern = uuid());
  $ZodStringFormat.init(inst, def);
});
const $ZodEmail = /* @__PURE__ */ $constructor("$ZodEmail", (inst, def) => {
  def.pattern ?? (def.pattern = email);
  $ZodStringFormat.init(inst, def);
});
const $ZodURL = /* @__PURE__ */ $constructor("$ZodURL", (inst, def) => {
  $ZodStringFormat.init(inst, def);
  inst._zod.check = (payload) => {
    try {
      const trimmed = payload.value.trim();
      const url = new URL(trimmed);
      if (def.hostname) {
        def.hostname.lastIndex = 0;
        if (!def.hostname.test(url.hostname)) {
          payload.issues.push({
            code: "invalid_format",
            format: "url",
            note: "Invalid hostname",
            pattern: def.hostname.source,
            input: payload.value,
            inst,
            continue: !def.abort
          });
        }
      }
      if (def.protocol) {
        def.protocol.lastIndex = 0;
        if (!def.protocol.test(url.protocol.endsWith(":") ? url.protocol.slice(0, -1) : url.protocol)) {
          payload.issues.push({
            code: "invalid_format",
            format: "url",
            note: "Invalid protocol",
            pattern: def.protocol.source,
            input: payload.value,
            inst,
            continue: !def.abort
          });
        }
      }
      if (def.normalize) {
        payload.value = url.href;
      } else {
        payload.value = trimmed;
      }
      return;
    } catch (_) {
      payload.issues.push({
        code: "invalid_format",
        format: "url",
        input: payload.value,
        inst,
        continue: !def.abort
      });
    }
  };
});
const $ZodEmoji = /* @__PURE__ */ $constructor("$ZodEmoji", (inst, def) => {
  def.pattern ?? (def.pattern = emoji());
  $ZodStringFormat.init(inst, def);
});
const $ZodNanoID = /* @__PURE__ */ $constructor("$ZodNanoID", (inst, def) => {
  def.pattern ?? (def.pattern = nanoid);
  $ZodStringFormat.init(inst, def);
});
const $ZodCUID = /* @__PURE__ */ $constructor("$ZodCUID", (inst, def) => {
  def.pattern ?? (def.pattern = cuid);
  $ZodStringFormat.init(inst, def);
});
const $ZodCUID2 = /* @__PURE__ */ $constructor("$ZodCUID2", (inst, def) => {
  def.pattern ?? (def.pattern = cuid2);
  $ZodStringFormat.init(inst, def);
});
const $ZodULID = /* @__PURE__ */ $constructor("$ZodULID", (inst, def) => {
  def.pattern ?? (def.pattern = ulid);
  $ZodStringFormat.init(inst, def);
});
const $ZodXID = /* @__PURE__ */ $constructor("$ZodXID", (inst, def) => {
  def.pattern ?? (def.pattern = xid);
  $ZodStringFormat.init(inst, def);
});
const $ZodKSUID = /* @__PURE__ */ $constructor("$ZodKSUID", (inst, def) => {
  def.pattern ?? (def.pattern = ksuid);
  $ZodStringFormat.init(inst, def);
});
const $ZodISODateTime = /* @__PURE__ */ $constructor("$ZodISODateTime", (inst, def) => {
  def.pattern ?? (def.pattern = datetime$1(def));
  $ZodStringFormat.init(inst, def);
});
const $ZodISODate = /* @__PURE__ */ $constructor("$ZodISODate", (inst, def) => {
  def.pattern ?? (def.pattern = date$1);
  $ZodStringFormat.init(inst, def);
});
const $ZodISOTime = /* @__PURE__ */ $constructor("$ZodISOTime", (inst, def) => {
  def.pattern ?? (def.pattern = time$1(def));
  $ZodStringFormat.init(inst, def);
});
const $ZodISODuration = /* @__PURE__ */ $constructor("$ZodISODuration", (inst, def) => {
  def.pattern ?? (def.pattern = duration$1);
  $ZodStringFormat.init(inst, def);
});
const $ZodIPv4 = /* @__PURE__ */ $constructor("$ZodIPv4", (inst, def) => {
  def.pattern ?? (def.pattern = ipv4);
  $ZodStringFormat.init(inst, def);
  inst._zod.bag.format = `ipv4`;
});
const $ZodIPv6 = /* @__PURE__ */ $constructor("$ZodIPv6", (inst, def) => {
  def.pattern ?? (def.pattern = ipv6);
  $ZodStringFormat.init(inst, def);
  inst._zod.bag.format = `ipv6`;
  inst._zod.check = (payload) => {
    try {
      new URL(`http://[${payload.value}]`);
    } catch {
      payload.issues.push({
        code: "invalid_format",
        format: "ipv6",
        input: payload.value,
        inst,
        continue: !def.abort
      });
    }
  };
});
const $ZodCIDRv4 = /* @__PURE__ */ $constructor("$ZodCIDRv4", (inst, def) => {
  def.pattern ?? (def.pattern = cidrv4);
  $ZodStringFormat.init(inst, def);
});
const $ZodCIDRv6 = /* @__PURE__ */ $constructor("$ZodCIDRv6", (inst, def) => {
  def.pattern ?? (def.pattern = cidrv6);
  $ZodStringFormat.init(inst, def);
  inst._zod.check = (payload) => {
    const parts = payload.value.split("/");
    try {
      if (parts.length !== 2)
        throw new Error();
      const [address, prefix] = parts;
      if (!prefix)
        throw new Error();
      const prefixNum = Number(prefix);
      if (`${prefixNum}` !== prefix)
        throw new Error();
      if (prefixNum < 0 || prefixNum > 128)
        throw new Error();
      new URL(`http://[${address}]`);
    } catch {
      payload.issues.push({
        code: "invalid_format",
        format: "cidrv6",
        input: payload.value,
        inst,
        continue: !def.abort
      });
    }
  };
});
function isValidBase64(data) {
  if (data === "")
    return true;
  if (data.length % 4 !== 0)
    return false;
  try {
    atob(data);
    return true;
  } catch {
    return false;
  }
}
const $ZodBase64 = /* @__PURE__ */ $constructor("$ZodBase64", (inst, def) => {
  def.pattern ?? (def.pattern = base64);
  $ZodStringFormat.init(inst, def);
  inst._zod.bag.contentEncoding = "base64";
  inst._zod.check = (payload) => {
    if (isValidBase64(payload.value))
      return;
    payload.issues.push({
      code: "invalid_format",
      format: "base64",
      input: payload.value,
      inst,
      continue: !def.abort
    });
  };
});
function isValidBase64URL(data) {
  if (!base64url.test(data))
    return false;
  const base642 = data.replace(/[-_]/g, (c) => c === "-" ? "+" : "/");
  const padded = base642.padEnd(Math.ceil(base642.length / 4) * 4, "=");
  return isValidBase64(padded);
}
const $ZodBase64URL = /* @__PURE__ */ $constructor("$ZodBase64URL", (inst, def) => {
  def.pattern ?? (def.pattern = base64url);
  $ZodStringFormat.init(inst, def);
  inst._zod.bag.contentEncoding = "base64url";
  inst._zod.check = (payload) => {
    if (isValidBase64URL(payload.value))
      return;
    payload.issues.push({
      code: "invalid_format",
      format: "base64url",
      input: payload.value,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodE164 = /* @__PURE__ */ $constructor("$ZodE164", (inst, def) => {
  def.pattern ?? (def.pattern = e164);
  $ZodStringFormat.init(inst, def);
});
function isValidJWT(token, algorithm = null) {
  try {
    const tokensParts = token.split(".");
    if (tokensParts.length !== 3)
      return false;
    const [header] = tokensParts;
    if (!header)
      return false;
    const parsedHeader = JSON.parse(atob(header));
    if ("typ" in parsedHeader && parsedHeader?.typ !== "JWT")
      return false;
    if (!parsedHeader.alg)
      return false;
    if (algorithm && (!("alg" in parsedHeader) || parsedHeader.alg !== algorithm))
      return false;
    return true;
  } catch {
    return false;
  }
}
const $ZodJWT = /* @__PURE__ */ $constructor("$ZodJWT", (inst, def) => {
  $ZodStringFormat.init(inst, def);
  inst._zod.check = (payload) => {
    if (isValidJWT(payload.value, def.alg))
      return;
    payload.issues.push({
      code: "invalid_format",
      format: "jwt",
      input: payload.value,
      inst,
      continue: !def.abort
    });
  };
});
const $ZodNumber = /* @__PURE__ */ $constructor("$ZodNumber", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.pattern = inst._zod.bag.pattern ?? number$1;
  inst._zod.parse = (payload, _ctx) => {
    if (def.coerce)
      try {
        payload.value = Number(payload.value);
      } catch (_) {
      }
    const input = payload.value;
    if (typeof input === "number" && !Number.isNaN(input) && Number.isFinite(input)) {
      return payload;
    }
    const received = typeof input === "number" ? Number.isNaN(input) ? "NaN" : !Number.isFinite(input) ? "Infinity" : void 0 : void 0;
    payload.issues.push({
      expected: "number",
      code: "invalid_type",
      input,
      inst,
      ...received ? { received } : {}
    });
    return payload;
  };
});
const $ZodNumberFormat = /* @__PURE__ */ $constructor("$ZodNumberFormat", (inst, def) => {
  $ZodCheckNumberFormat.init(inst, def);
  $ZodNumber.init(inst, def);
});
const $ZodBoolean = /* @__PURE__ */ $constructor("$ZodBoolean", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.pattern = boolean$1;
  inst._zod.parse = (payload, _ctx) => {
    if (def.coerce)
      try {
        payload.value = Boolean(payload.value);
      } catch (_) {
      }
    const input = payload.value;
    if (typeof input === "boolean")
      return payload;
    payload.issues.push({
      expected: "boolean",
      code: "invalid_type",
      input,
      inst
    });
    return payload;
  };
});
const $ZodUnknown = /* @__PURE__ */ $constructor("$ZodUnknown", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.parse = (payload) => payload;
});
const $ZodNever = /* @__PURE__ */ $constructor("$ZodNever", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.parse = (payload, _ctx) => {
    payload.issues.push({
      expected: "never",
      code: "invalid_type",
      input: payload.value,
      inst
    });
    return payload;
  };
});
function handleArrayResult(result, final, index) {
  if (result.issues.length) {
    final.issues.push(...prefixIssues(index, result.issues));
  }
  final.value[index] = result.value;
}
const $ZodArray = /* @__PURE__ */ $constructor("$ZodArray", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.parse = (payload, ctx) => {
    const input = payload.value;
    if (!Array.isArray(input)) {
      payload.issues.push({
        expected: "array",
        code: "invalid_type",
        input,
        inst
      });
      return payload;
    }
    payload.value = Array(input.length);
    const proms = [];
    for (let i = 0; i < input.length; i++) {
      const item = input[i];
      const result = def.element._zod.run({
        value: item,
        issues: []
      }, ctx);
      if (result instanceof Promise) {
        proms.push(result.then((result2) => handleArrayResult(result2, payload, i)));
      } else {
        handleArrayResult(result, payload, i);
      }
    }
    if (proms.length) {
      return Promise.all(proms).then(() => payload);
    }
    return payload;
  };
});
function handlePropertyResult(result, final, key, input, isOptionalOut) {
  if (result.issues.length) {
    if (isOptionalOut && !(key in input)) {
      return;
    }
    final.issues.push(...prefixIssues(key, result.issues));
  }
  if (result.value === void 0) {
    if (key in input) {
      final.value[key] = void 0;
    }
  } else {
    final.value[key] = result.value;
  }
}
function normalizeDef(def) {
  const keys = Object.keys(def.shape);
  for (const k of keys) {
    if (!def.shape?.[k]?._zod?.traits?.has("$ZodType")) {
      throw new Error(`Invalid element at key "${k}": expected a Zod schema`);
    }
  }
  const okeys = optionalKeys(def.shape);
  return {
    ...def,
    keys,
    keySet: new Set(keys),
    numKeys: keys.length,
    optionalKeys: new Set(okeys)
  };
}
function handleCatchall(proms, input, payload, ctx, def, inst) {
  const unrecognized = [];
  const keySet = def.keySet;
  const _catchall = def.catchall._zod;
  const t = _catchall.def.type;
  const isOptionalOut = _catchall.optout === "optional";
  for (const key in input) {
    if (keySet.has(key))
      continue;
    if (t === "never") {
      unrecognized.push(key);
      continue;
    }
    const r = _catchall.run({ value: input[key], issues: [] }, ctx);
    if (r instanceof Promise) {
      proms.push(r.then((r2) => handlePropertyResult(r2, payload, key, input, isOptionalOut)));
    } else {
      handlePropertyResult(r, payload, key, input, isOptionalOut);
    }
  }
  if (unrecognized.length) {
    payload.issues.push({
      code: "unrecognized_keys",
      keys: unrecognized,
      input,
      inst
    });
  }
  if (!proms.length)
    return payload;
  return Promise.all(proms).then(() => {
    return payload;
  });
}
const $ZodObject = /* @__PURE__ */ $constructor("$ZodObject", (inst, def) => {
  $ZodType.init(inst, def);
  const desc = Object.getOwnPropertyDescriptor(def, "shape");
  if (!desc?.get) {
    const sh = def.shape;
    Object.defineProperty(def, "shape", {
      get: () => {
        const newSh = { ...sh };
        Object.defineProperty(def, "shape", {
          value: newSh
        });
        return newSh;
      }
    });
  }
  const _normalized = cached(() => normalizeDef(def));
  defineLazy(inst._zod, "propValues", () => {
    const shape = def.shape;
    const propValues = {};
    for (const key in shape) {
      const field = shape[key]._zod;
      if (field.values) {
        propValues[key] ?? (propValues[key] = /* @__PURE__ */ new Set());
        for (const v of field.values)
          propValues[key].add(v);
      }
    }
    return propValues;
  });
  const isObject$1 = isObject;
  const catchall = def.catchall;
  let value;
  inst._zod.parse = (payload, ctx) => {
    value ?? (value = _normalized.value);
    const input = payload.value;
    if (!isObject$1(input)) {
      payload.issues.push({
        expected: "object",
        code: "invalid_type",
        input,
        inst
      });
      return payload;
    }
    payload.value = {};
    const proms = [];
    const shape = value.shape;
    for (const key of value.keys) {
      const el = shape[key];
      const isOptionalOut = el._zod.optout === "optional";
      const r = el._zod.run({ value: input[key], issues: [] }, ctx);
      if (r instanceof Promise) {
        proms.push(r.then((r2) => handlePropertyResult(r2, payload, key, input, isOptionalOut)));
      } else {
        handlePropertyResult(r, payload, key, input, isOptionalOut);
      }
    }
    if (!catchall) {
      return proms.length ? Promise.all(proms).then(() => payload) : payload;
    }
    return handleCatchall(proms, input, payload, ctx, _normalized.value, inst);
  };
});
const $ZodObjectJIT = /* @__PURE__ */ $constructor("$ZodObjectJIT", (inst, def) => {
  $ZodObject.init(inst, def);
  const superParse = inst._zod.parse;
  const _normalized = cached(() => normalizeDef(def));
  const generateFastpass = (shape) => {
    const doc = new Doc(["shape", "payload", "ctx"]);
    const normalized = _normalized.value;
    const parseStr = (key) => {
      const k = esc(key);
      return `shape[${k}]._zod.run({ value: input[${k}], issues: [] }, ctx)`;
    };
    doc.write(`const input = payload.value;`);
    const ids = /* @__PURE__ */ Object.create(null);
    let counter = 0;
    for (const key of normalized.keys) {
      ids[key] = `key_${counter++}`;
    }
    doc.write(`const newResult = {};`);
    for (const key of normalized.keys) {
      const id = ids[key];
      const k = esc(key);
      const schema = shape[key];
      const isOptionalOut = schema?._zod?.optout === "optional";
      doc.write(`const ${id} = ${parseStr(key)};`);
      if (isOptionalOut) {
        doc.write(`
        if (${id}.issues.length) {
          if (${k} in input) {
            payload.issues = payload.issues.concat(${id}.issues.map(iss => ({
              ...iss,
              path: iss.path ? [${k}, ...iss.path] : [${k}]
            })));
          }
        }
        
        if (${id}.value === undefined) {
          if (${k} in input) {
            newResult[${k}] = undefined;
          }
        } else {
          newResult[${k}] = ${id}.value;
        }
        
      `);
      } else {
        doc.write(`
        if (${id}.issues.length) {
          payload.issues = payload.issues.concat(${id}.issues.map(iss => ({
            ...iss,
            path: iss.path ? [${k}, ...iss.path] : [${k}]
          })));
        }
        
        if (${id}.value === undefined) {
          if (${k} in input) {
            newResult[${k}] = undefined;
          }
        } else {
          newResult[${k}] = ${id}.value;
        }
        
      `);
      }
    }
    doc.write(`payload.value = newResult;`);
    doc.write(`return payload;`);
    const fn = doc.compile();
    return (payload, ctx) => fn(shape, payload, ctx);
  };
  let fastpass;
  const isObject$1 = isObject;
  const jit = !globalConfig.jitless;
  const allowsEval$1 = allowsEval;
  const fastEnabled = jit && allowsEval$1.value;
  const catchall = def.catchall;
  let value;
  inst._zod.parse = (payload, ctx) => {
    value ?? (value = _normalized.value);
    const input = payload.value;
    if (!isObject$1(input)) {
      payload.issues.push({
        expected: "object",
        code: "invalid_type",
        input,
        inst
      });
      return payload;
    }
    if (jit && fastEnabled && ctx?.async === false && ctx.jitless !== true) {
      if (!fastpass)
        fastpass = generateFastpass(def.shape);
      payload = fastpass(payload, ctx);
      if (!catchall)
        return payload;
      return handleCatchall([], input, payload, ctx, value, inst);
    }
    return superParse(payload, ctx);
  };
});
function handleUnionResults(results, final, inst, ctx) {
  for (const result of results) {
    if (result.issues.length === 0) {
      final.value = result.value;
      return final;
    }
  }
  const nonaborted = results.filter((r) => !aborted(r));
  if (nonaborted.length === 1) {
    final.value = nonaborted[0].value;
    return nonaborted[0];
  }
  final.issues.push({
    code: "invalid_union",
    input: final.value,
    inst,
    errors: results.map((result) => result.issues.map((iss) => finalizeIssue(iss, ctx, config())))
  });
  return final;
}
const $ZodUnion = /* @__PURE__ */ $constructor("$ZodUnion", (inst, def) => {
  $ZodType.init(inst, def);
  defineLazy(inst._zod, "optin", () => def.options.some((o) => o._zod.optin === "optional") ? "optional" : void 0);
  defineLazy(inst._zod, "optout", () => def.options.some((o) => o._zod.optout === "optional") ? "optional" : void 0);
  defineLazy(inst._zod, "values", () => {
    if (def.options.every((o) => o._zod.values)) {
      return new Set(def.options.flatMap((option) => Array.from(option._zod.values)));
    }
    return void 0;
  });
  defineLazy(inst._zod, "pattern", () => {
    if (def.options.every((o) => o._zod.pattern)) {
      const patterns = def.options.map((o) => o._zod.pattern);
      return new RegExp(`^(${patterns.map((p) => cleanRegex(p.source)).join("|")})$`);
    }
    return void 0;
  });
  const single = def.options.length === 1;
  const first = def.options[0]._zod.run;
  inst._zod.parse = (payload, ctx) => {
    if (single) {
      return first(payload, ctx);
    }
    let async = false;
    const results = [];
    for (const option of def.options) {
      const result = option._zod.run({
        value: payload.value,
        issues: []
      }, ctx);
      if (result instanceof Promise) {
        results.push(result);
        async = true;
      } else {
        if (result.issues.length === 0)
          return result;
        results.push(result);
      }
    }
    if (!async)
      return handleUnionResults(results, payload, inst, ctx);
    return Promise.all(results).then((results2) => {
      return handleUnionResults(results2, payload, inst, ctx);
    });
  };
});
const $ZodIntersection = /* @__PURE__ */ $constructor("$ZodIntersection", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.parse = (payload, ctx) => {
    const input = payload.value;
    const left = def.left._zod.run({ value: input, issues: [] }, ctx);
    const right = def.right._zod.run({ value: input, issues: [] }, ctx);
    const async = left instanceof Promise || right instanceof Promise;
    if (async) {
      return Promise.all([left, right]).then(([left2, right2]) => {
        return handleIntersectionResults(payload, left2, right2);
      });
    }
    return handleIntersectionResults(payload, left, right);
  };
});
function mergeValues(a, b) {
  if (a === b) {
    return { valid: true, data: a };
  }
  if (a instanceof Date && b instanceof Date && +a === +b) {
    return { valid: true, data: a };
  }
  if (isPlainObject$1(a) && isPlainObject$1(b)) {
    const bKeys = Object.keys(b);
    const sharedKeys = Object.keys(a).filter((key) => bKeys.indexOf(key) !== -1);
    const newObj = { ...a, ...b };
    for (const key of sharedKeys) {
      const sharedValue = mergeValues(a[key], b[key]);
      if (!sharedValue.valid) {
        return {
          valid: false,
          mergeErrorPath: [key, ...sharedValue.mergeErrorPath]
        };
      }
      newObj[key] = sharedValue.data;
    }
    return { valid: true, data: newObj };
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) {
      return { valid: false, mergeErrorPath: [] };
    }
    const newArray = [];
    for (let index = 0; index < a.length; index++) {
      const itemA = a[index];
      const itemB = b[index];
      const sharedValue = mergeValues(itemA, itemB);
      if (!sharedValue.valid) {
        return {
          valid: false,
          mergeErrorPath: [index, ...sharedValue.mergeErrorPath]
        };
      }
      newArray.push(sharedValue.data);
    }
    return { valid: true, data: newArray };
  }
  return { valid: false, mergeErrorPath: [] };
}
function handleIntersectionResults(result, left, right) {
  const unrecKeys = /* @__PURE__ */ new Map();
  let unrecIssue;
  for (const iss of left.issues) {
    if (iss.code === "unrecognized_keys") {
      unrecIssue ?? (unrecIssue = iss);
      for (const k of iss.keys) {
        if (!unrecKeys.has(k))
          unrecKeys.set(k, {});
        unrecKeys.get(k).l = true;
      }
    } else {
      result.issues.push(iss);
    }
  }
  for (const iss of right.issues) {
    if (iss.code === "unrecognized_keys") {
      for (const k of iss.keys) {
        if (!unrecKeys.has(k))
          unrecKeys.set(k, {});
        unrecKeys.get(k).r = true;
      }
    } else {
      result.issues.push(iss);
    }
  }
  const bothKeys = [...unrecKeys].filter(([, f]) => f.l && f.r).map(([k]) => k);
  if (bothKeys.length && unrecIssue) {
    result.issues.push({ ...unrecIssue, keys: bothKeys });
  }
  if (aborted(result))
    return result;
  const merged = mergeValues(left.value, right.value);
  if (!merged.valid) {
    throw new Error(`Unmergable intersection. Error path: ${JSON.stringify(merged.mergeErrorPath)}`);
  }
  result.value = merged.data;
  return result;
}
const $ZodRecord = /* @__PURE__ */ $constructor("$ZodRecord", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.parse = (payload, ctx) => {
    const input = payload.value;
    if (!isPlainObject$1(input)) {
      payload.issues.push({
        expected: "record",
        code: "invalid_type",
        input,
        inst
      });
      return payload;
    }
    const proms = [];
    const values = def.keyType._zod.values;
    if (values) {
      payload.value = {};
      const recordKeys = /* @__PURE__ */ new Set();
      for (const key of values) {
        if (typeof key === "string" || typeof key === "number" || typeof key === "symbol") {
          recordKeys.add(typeof key === "number" ? key.toString() : key);
          const result = def.valueType._zod.run({ value: input[key], issues: [] }, ctx);
          if (result instanceof Promise) {
            proms.push(result.then((result2) => {
              if (result2.issues.length) {
                payload.issues.push(...prefixIssues(key, result2.issues));
              }
              payload.value[key] = result2.value;
            }));
          } else {
            if (result.issues.length) {
              payload.issues.push(...prefixIssues(key, result.issues));
            }
            payload.value[key] = result.value;
          }
        }
      }
      let unrecognized;
      for (const key in input) {
        if (!recordKeys.has(key)) {
          unrecognized = unrecognized ?? [];
          unrecognized.push(key);
        }
      }
      if (unrecognized && unrecognized.length > 0) {
        payload.issues.push({
          code: "unrecognized_keys",
          input,
          inst,
          keys: unrecognized
        });
      }
    } else {
      payload.value = {};
      for (const key of Reflect.ownKeys(input)) {
        if (key === "__proto__")
          continue;
        let keyResult = def.keyType._zod.run({ value: key, issues: [] }, ctx);
        if (keyResult instanceof Promise) {
          throw new Error("Async schemas not supported in object keys currently");
        }
        const checkNumericKey = typeof key === "string" && number$1.test(key) && keyResult.issues.length;
        if (checkNumericKey) {
          const retryResult = def.keyType._zod.run({ value: Number(key), issues: [] }, ctx);
          if (retryResult instanceof Promise) {
            throw new Error("Async schemas not supported in object keys currently");
          }
          if (retryResult.issues.length === 0) {
            keyResult = retryResult;
          }
        }
        if (keyResult.issues.length) {
          if (def.mode === "loose") {
            payload.value[key] = input[key];
          } else {
            payload.issues.push({
              code: "invalid_key",
              origin: "record",
              issues: keyResult.issues.map((iss) => finalizeIssue(iss, ctx, config())),
              input: key,
              path: [key],
              inst
            });
          }
          continue;
        }
        const result = def.valueType._zod.run({ value: input[key], issues: [] }, ctx);
        if (result instanceof Promise) {
          proms.push(result.then((result2) => {
            if (result2.issues.length) {
              payload.issues.push(...prefixIssues(key, result2.issues));
            }
            payload.value[keyResult.value] = result2.value;
          }));
        } else {
          if (result.issues.length) {
            payload.issues.push(...prefixIssues(key, result.issues));
          }
          payload.value[keyResult.value] = result.value;
        }
      }
    }
    if (proms.length) {
      return Promise.all(proms).then(() => payload);
    }
    return payload;
  };
});
const $ZodEnum = /* @__PURE__ */ $constructor("$ZodEnum", (inst, def) => {
  $ZodType.init(inst, def);
  const values = getEnumValues(def.entries);
  const valuesSet = new Set(values);
  inst._zod.values = valuesSet;
  inst._zod.pattern = new RegExp(`^(${values.filter((k) => propertyKeyTypes.has(typeof k)).map((o) => typeof o === "string" ? escapeRegex(o) : o.toString()).join("|")})$`);
  inst._zod.parse = (payload, _ctx) => {
    const input = payload.value;
    if (valuesSet.has(input)) {
      return payload;
    }
    payload.issues.push({
      code: "invalid_value",
      values,
      input,
      inst
    });
    return payload;
  };
});
const $ZodTransform = /* @__PURE__ */ $constructor("$ZodTransform", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.parse = (payload, ctx) => {
    if (ctx.direction === "backward") {
      throw new $ZodEncodeError(inst.constructor.name);
    }
    const _out = def.transform(payload.value, payload);
    if (ctx.async) {
      const output = _out instanceof Promise ? _out : Promise.resolve(_out);
      return output.then((output2) => {
        payload.value = output2;
        return payload;
      });
    }
    if (_out instanceof Promise) {
      throw new $ZodAsyncError();
    }
    payload.value = _out;
    return payload;
  };
});
function handleOptionalResult(result, input) {
  if (result.issues.length && input === void 0) {
    return { issues: [], value: void 0 };
  }
  return result;
}
const $ZodOptional = /* @__PURE__ */ $constructor("$ZodOptional", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.optin = "optional";
  inst._zod.optout = "optional";
  defineLazy(inst._zod, "values", () => {
    return def.innerType._zod.values ? /* @__PURE__ */ new Set([...def.innerType._zod.values, void 0]) : void 0;
  });
  defineLazy(inst._zod, "pattern", () => {
    const pattern = def.innerType._zod.pattern;
    return pattern ? new RegExp(`^(${cleanRegex(pattern.source)})?$`) : void 0;
  });
  inst._zod.parse = (payload, ctx) => {
    if (def.innerType._zod.optin === "optional") {
      const result = def.innerType._zod.run(payload, ctx);
      if (result instanceof Promise)
        return result.then((r) => handleOptionalResult(r, payload.value));
      return handleOptionalResult(result, payload.value);
    }
    if (payload.value === void 0) {
      return payload;
    }
    return def.innerType._zod.run(payload, ctx);
  };
});
const $ZodExactOptional = /* @__PURE__ */ $constructor("$ZodExactOptional", (inst, def) => {
  $ZodOptional.init(inst, def);
  defineLazy(inst._zod, "values", () => def.innerType._zod.values);
  defineLazy(inst._zod, "pattern", () => def.innerType._zod.pattern);
  inst._zod.parse = (payload, ctx) => {
    return def.innerType._zod.run(payload, ctx);
  };
});
const $ZodNullable = /* @__PURE__ */ $constructor("$ZodNullable", (inst, def) => {
  $ZodType.init(inst, def);
  defineLazy(inst._zod, "optin", () => def.innerType._zod.optin);
  defineLazy(inst._zod, "optout", () => def.innerType._zod.optout);
  defineLazy(inst._zod, "pattern", () => {
    const pattern = def.innerType._zod.pattern;
    return pattern ? new RegExp(`^(${cleanRegex(pattern.source)}|null)$`) : void 0;
  });
  defineLazy(inst._zod, "values", () => {
    return def.innerType._zod.values ? /* @__PURE__ */ new Set([...def.innerType._zod.values, null]) : void 0;
  });
  inst._zod.parse = (payload, ctx) => {
    if (payload.value === null)
      return payload;
    return def.innerType._zod.run(payload, ctx);
  };
});
const $ZodDefault = /* @__PURE__ */ $constructor("$ZodDefault", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.optin = "optional";
  defineLazy(inst._zod, "values", () => def.innerType._zod.values);
  inst._zod.parse = (payload, ctx) => {
    if (ctx.direction === "backward") {
      return def.innerType._zod.run(payload, ctx);
    }
    if (payload.value === void 0) {
      payload.value = def.defaultValue;
      return payload;
    }
    const result = def.innerType._zod.run(payload, ctx);
    if (result instanceof Promise) {
      return result.then((result2) => handleDefaultResult(result2, def));
    }
    return handleDefaultResult(result, def);
  };
});
function handleDefaultResult(payload, def) {
  if (payload.value === void 0) {
    payload.value = def.defaultValue;
  }
  return payload;
}
const $ZodPrefault = /* @__PURE__ */ $constructor("$ZodPrefault", (inst, def) => {
  $ZodType.init(inst, def);
  inst._zod.optin = "optional";
  defineLazy(inst._zod, "values", () => def.innerType._zod.values);
  inst._zod.parse = (payload, ctx) => {
    if (ctx.direction === "backward") {
      return def.innerType._zod.run(payload, ctx);
    }
    if (payload.value === void 0) {
      payload.value = def.defaultValue;
    }
    return def.innerType._zod.run(payload, ctx);
  };
});
const $ZodNonOptional = /* @__PURE__ */ $constructor("$ZodNonOptional", (inst, def) => {
  $ZodType.init(inst, def);
  defineLazy(inst._zod, "values", () => {
    const v = def.innerType._zod.values;
    return v ? new Set([...v].filter((x) => x !== void 0)) : void 0;
  });
  inst._zod.parse = (payload, ctx) => {
    const result = def.innerType._zod.run(payload, ctx);
    if (result instanceof Promise) {
      return result.then((result2) => handleNonOptionalResult(result2, inst));
    }
    return handleNonOptionalResult(result, inst);
  };
});
function handleNonOptionalResult(payload, inst) {
  if (!payload.issues.length && payload.value === void 0) {
    payload.issues.push({
      code: "invalid_type",
      expected: "nonoptional",
      input: payload.value,
      inst
    });
  }
  return payload;
}
const $ZodCatch = /* @__PURE__ */ $constructor("$ZodCatch", (inst, def) => {
  $ZodType.init(inst, def);
  defineLazy(inst._zod, "optin", () => def.innerType._zod.optin);
  defineLazy(inst._zod, "optout", () => def.innerType._zod.optout);
  defineLazy(inst._zod, "values", () => def.innerType._zod.values);
  inst._zod.parse = (payload, ctx) => {
    if (ctx.direction === "backward") {
      return def.innerType._zod.run(payload, ctx);
    }
    const result = def.innerType._zod.run(payload, ctx);
    if (result instanceof Promise) {
      return result.then((result2) => {
        payload.value = result2.value;
        if (result2.issues.length) {
          payload.value = def.catchValue({
            ...payload,
            error: {
              issues: result2.issues.map((iss) => finalizeIssue(iss, ctx, config()))
            },
            input: payload.value
          });
          payload.issues = [];
        }
        return payload;
      });
    }
    payload.value = result.value;
    if (result.issues.length) {
      payload.value = def.catchValue({
        ...payload,
        error: {
          issues: result.issues.map((iss) => finalizeIssue(iss, ctx, config()))
        },
        input: payload.value
      });
      payload.issues = [];
    }
    return payload;
  };
});
const $ZodPipe = /* @__PURE__ */ $constructor("$ZodPipe", (inst, def) => {
  $ZodType.init(inst, def);
  defineLazy(inst._zod, "values", () => def.in._zod.values);
  defineLazy(inst._zod, "optin", () => def.in._zod.optin);
  defineLazy(inst._zod, "optout", () => def.out._zod.optout);
  defineLazy(inst._zod, "propValues", () => def.in._zod.propValues);
  inst._zod.parse = (payload, ctx) => {
    if (ctx.direction === "backward") {
      const right = def.out._zod.run(payload, ctx);
      if (right instanceof Promise) {
        return right.then((right2) => handlePipeResult(right2, def.in, ctx));
      }
      return handlePipeResult(right, def.in, ctx);
    }
    const left = def.in._zod.run(payload, ctx);
    if (left instanceof Promise) {
      return left.then((left2) => handlePipeResult(left2, def.out, ctx));
    }
    return handlePipeResult(left, def.out, ctx);
  };
});
function handlePipeResult(left, next, ctx) {
  if (left.issues.length) {
    left.aborted = true;
    return left;
  }
  return next._zod.run({ value: left.value, issues: left.issues }, ctx);
}
const $ZodReadonly = /* @__PURE__ */ $constructor("$ZodReadonly", (inst, def) => {
  $ZodType.init(inst, def);
  defineLazy(inst._zod, "propValues", () => def.innerType._zod.propValues);
  defineLazy(inst._zod, "values", () => def.innerType._zod.values);
  defineLazy(inst._zod, "optin", () => def.innerType?._zod?.optin);
  defineLazy(inst._zod, "optout", () => def.innerType?._zod?.optout);
  inst._zod.parse = (payload, ctx) => {
    if (ctx.direction === "backward") {
      return def.innerType._zod.run(payload, ctx);
    }
    const result = def.innerType._zod.run(payload, ctx);
    if (result instanceof Promise) {
      return result.then(handleReadonlyResult);
    }
    return handleReadonlyResult(result);
  };
});
function handleReadonlyResult(payload) {
  payload.value = Object.freeze(payload.value);
  return payload;
}
const $ZodCustom = /* @__PURE__ */ $constructor("$ZodCustom", (inst, def) => {
  $ZodCheck.init(inst, def);
  $ZodType.init(inst, def);
  inst._zod.parse = (payload, _) => {
    return payload;
  };
  inst._zod.check = (payload) => {
    const input = payload.value;
    const r = def.fn(input);
    if (r instanceof Promise) {
      return r.then((r2) => handleRefineResult(r2, payload, input, inst));
    }
    handleRefineResult(r, payload, input, inst);
    return;
  };
});
function handleRefineResult(result, payload, input, inst) {
  if (!result) {
    const _iss = {
      code: "custom",
      input,
      inst,
      // incorporates params.error into issue reporting
      path: [...inst._zod.def.path ?? []],
      // incorporates params.error into issue reporting
      continue: !inst._zod.def.abort
      // params: inst._zod.def.params,
    };
    if (inst._zod.def.params)
      _iss.params = inst._zod.def.params;
    payload.issues.push(issue(_iss));
  }
}
var _a;
class $ZodRegistry {
  constructor() {
    this._map = /* @__PURE__ */ new WeakMap();
    this._idmap = /* @__PURE__ */ new Map();
  }
  add(schema, ..._meta) {
    const meta = _meta[0];
    this._map.set(schema, meta);
    if (meta && typeof meta === "object" && "id" in meta) {
      this._idmap.set(meta.id, schema);
    }
    return this;
  }
  clear() {
    this._map = /* @__PURE__ */ new WeakMap();
    this._idmap = /* @__PURE__ */ new Map();
    return this;
  }
  remove(schema) {
    const meta = this._map.get(schema);
    if (meta && typeof meta === "object" && "id" in meta) {
      this._idmap.delete(meta.id);
    }
    this._map.delete(schema);
    return this;
  }
  get(schema) {
    const p = schema._zod.parent;
    if (p) {
      const pm = { ...this.get(p) ?? {} };
      delete pm.id;
      const f = { ...pm, ...this._map.get(schema) };
      return Object.keys(f).length ? f : void 0;
    }
    return this._map.get(schema);
  }
  has(schema) {
    return this._map.has(schema);
  }
}
function registry() {
  return new $ZodRegistry();
}
(_a = globalThis).__zod_globalRegistry ?? (_a.__zod_globalRegistry = registry());
const globalRegistry = globalThis.__zod_globalRegistry;
// @__NO_SIDE_EFFECTS__
function _string(Class, params) {
  return new Class({
    type: "string",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _email(Class, params) {
  return new Class({
    type: "string",
    format: "email",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _guid(Class, params) {
  return new Class({
    type: "string",
    format: "guid",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _uuid(Class, params) {
  return new Class({
    type: "string",
    format: "uuid",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _uuidv4(Class, params) {
  return new Class({
    type: "string",
    format: "uuid",
    check: "string_format",
    abort: false,
    version: "v4",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _uuidv6(Class, params) {
  return new Class({
    type: "string",
    format: "uuid",
    check: "string_format",
    abort: false,
    version: "v6",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _uuidv7(Class, params) {
  return new Class({
    type: "string",
    format: "uuid",
    check: "string_format",
    abort: false,
    version: "v7",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _url(Class, params) {
  return new Class({
    type: "string",
    format: "url",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _emoji(Class, params) {
  return new Class({
    type: "string",
    format: "emoji",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _nanoid(Class, params) {
  return new Class({
    type: "string",
    format: "nanoid",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _cuid(Class, params) {
  return new Class({
    type: "string",
    format: "cuid",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _cuid2(Class, params) {
  return new Class({
    type: "string",
    format: "cuid2",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _ulid(Class, params) {
  return new Class({
    type: "string",
    format: "ulid",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _xid(Class, params) {
  return new Class({
    type: "string",
    format: "xid",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _ksuid(Class, params) {
  return new Class({
    type: "string",
    format: "ksuid",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _ipv4(Class, params) {
  return new Class({
    type: "string",
    format: "ipv4",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _ipv6(Class, params) {
  return new Class({
    type: "string",
    format: "ipv6",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _cidrv4(Class, params) {
  return new Class({
    type: "string",
    format: "cidrv4",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _cidrv6(Class, params) {
  return new Class({
    type: "string",
    format: "cidrv6",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _base64(Class, params) {
  return new Class({
    type: "string",
    format: "base64",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _base64url(Class, params) {
  return new Class({
    type: "string",
    format: "base64url",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _e164(Class, params) {
  return new Class({
    type: "string",
    format: "e164",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _jwt(Class, params) {
  return new Class({
    type: "string",
    format: "jwt",
    check: "string_format",
    abort: false,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _isoDateTime(Class, params) {
  return new Class({
    type: "string",
    format: "datetime",
    check: "string_format",
    offset: false,
    local: false,
    precision: null,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _isoDate(Class, params) {
  return new Class({
    type: "string",
    format: "date",
    check: "string_format",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _isoTime(Class, params) {
  return new Class({
    type: "string",
    format: "time",
    check: "string_format",
    precision: null,
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _isoDuration(Class, params) {
  return new Class({
    type: "string",
    format: "duration",
    check: "string_format",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _number(Class, params) {
  return new Class({
    type: "number",
    checks: [],
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _int(Class, params) {
  return new Class({
    type: "number",
    check: "number_format",
    abort: false,
    format: "safeint",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _boolean(Class, params) {
  return new Class({
    type: "boolean",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _unknown(Class) {
  return new Class({
    type: "unknown"
  });
}
// @__NO_SIDE_EFFECTS__
function _never(Class, params) {
  return new Class({
    type: "never",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _lt(value, params) {
  return new $ZodCheckLessThan({
    check: "less_than",
    ...normalizeParams(params),
    value,
    inclusive: false
  });
}
// @__NO_SIDE_EFFECTS__
function _lte(value, params) {
  return new $ZodCheckLessThan({
    check: "less_than",
    ...normalizeParams(params),
    value,
    inclusive: true
  });
}
// @__NO_SIDE_EFFECTS__
function _gt(value, params) {
  return new $ZodCheckGreaterThan({
    check: "greater_than",
    ...normalizeParams(params),
    value,
    inclusive: false
  });
}
// @__NO_SIDE_EFFECTS__
function _gte(value, params) {
  return new $ZodCheckGreaterThan({
    check: "greater_than",
    ...normalizeParams(params),
    value,
    inclusive: true
  });
}
// @__NO_SIDE_EFFECTS__
function _multipleOf(value, params) {
  return new $ZodCheckMultipleOf({
    check: "multiple_of",
    ...normalizeParams(params),
    value
  });
}
// @__NO_SIDE_EFFECTS__
function _maxLength(maximum, params) {
  const ch = new $ZodCheckMaxLength({
    check: "max_length",
    ...normalizeParams(params),
    maximum
  });
  return ch;
}
// @__NO_SIDE_EFFECTS__
function _minLength(minimum, params) {
  return new $ZodCheckMinLength({
    check: "min_length",
    ...normalizeParams(params),
    minimum
  });
}
// @__NO_SIDE_EFFECTS__
function _length(length, params) {
  return new $ZodCheckLengthEquals({
    check: "length_equals",
    ...normalizeParams(params),
    length
  });
}
// @__NO_SIDE_EFFECTS__
function _regex(pattern, params) {
  return new $ZodCheckRegex({
    check: "string_format",
    format: "regex",
    ...normalizeParams(params),
    pattern
  });
}
// @__NO_SIDE_EFFECTS__
function _lowercase(params) {
  return new $ZodCheckLowerCase({
    check: "string_format",
    format: "lowercase",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _uppercase(params) {
  return new $ZodCheckUpperCase({
    check: "string_format",
    format: "uppercase",
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _includes(includes, params) {
  return new $ZodCheckIncludes({
    check: "string_format",
    format: "includes",
    ...normalizeParams(params),
    includes
  });
}
// @__NO_SIDE_EFFECTS__
function _startsWith(prefix, params) {
  return new $ZodCheckStartsWith({
    check: "string_format",
    format: "starts_with",
    ...normalizeParams(params),
    prefix
  });
}
// @__NO_SIDE_EFFECTS__
function _endsWith(suffix, params) {
  return new $ZodCheckEndsWith({
    check: "string_format",
    format: "ends_with",
    ...normalizeParams(params),
    suffix
  });
}
// @__NO_SIDE_EFFECTS__
function _overwrite(tx) {
  return new $ZodCheckOverwrite({
    check: "overwrite",
    tx
  });
}
// @__NO_SIDE_EFFECTS__
function _normalize(form) {
  return /* @__PURE__ */ _overwrite((input) => input.normalize(form));
}
// @__NO_SIDE_EFFECTS__
function _trim() {
  return /* @__PURE__ */ _overwrite((input) => input.trim());
}
// @__NO_SIDE_EFFECTS__
function _toLowerCase() {
  return /* @__PURE__ */ _overwrite((input) => input.toLowerCase());
}
// @__NO_SIDE_EFFECTS__
function _toUpperCase() {
  return /* @__PURE__ */ _overwrite((input) => input.toUpperCase());
}
// @__NO_SIDE_EFFECTS__
function _slugify() {
  return /* @__PURE__ */ _overwrite((input) => slugify(input));
}
// @__NO_SIDE_EFFECTS__
function _array(Class, element, params) {
  return new Class({
    type: "array",
    element,
    // get element() {
    //   return element;
    // },
    ...normalizeParams(params)
  });
}
// @__NO_SIDE_EFFECTS__
function _refine(Class, fn, _params) {
  const schema = new Class({
    type: "custom",
    check: "custom",
    fn,
    ...normalizeParams(_params)
  });
  return schema;
}
// @__NO_SIDE_EFFECTS__
function _superRefine(fn) {
  const ch = /* @__PURE__ */ _check((payload) => {
    payload.addIssue = (issue$1) => {
      if (typeof issue$1 === "string") {
        payload.issues.push(issue(issue$1, payload.value, ch._zod.def));
      } else {
        const _issue = issue$1;
        if (_issue.fatal)
          _issue.continue = false;
        _issue.code ?? (_issue.code = "custom");
        _issue.input ?? (_issue.input = payload.value);
        _issue.inst ?? (_issue.inst = ch);
        _issue.continue ?? (_issue.continue = !ch._zod.def.abort);
        payload.issues.push(issue(_issue));
      }
    };
    return fn(payload.value, payload);
  });
  return ch;
}
// @__NO_SIDE_EFFECTS__
function _check(fn, params) {
  const ch = new $ZodCheck({
    check: "custom",
    ...normalizeParams(params)
  });
  ch._zod.check = fn;
  return ch;
}
function initializeContext(params) {
  let target = params?.target ?? "draft-2020-12";
  if (target === "draft-4")
    target = "draft-04";
  if (target === "draft-7")
    target = "draft-07";
  return {
    processors: params.processors ?? {},
    metadataRegistry: params?.metadata ?? globalRegistry,
    target,
    unrepresentable: params?.unrepresentable ?? "throw",
    override: params?.override ?? (() => {
    }),
    io: params?.io ?? "output",
    counter: 0,
    seen: /* @__PURE__ */ new Map(),
    cycles: params?.cycles ?? "ref",
    reused: params?.reused ?? "inline",
    external: params?.external ?? void 0
  };
}
function process$1(schema, ctx, _params = { path: [], schemaPath: [] }) {
  var _a2;
  const def = schema._zod.def;
  const seen = ctx.seen.get(schema);
  if (seen) {
    seen.count++;
    const isCycle = _params.schemaPath.includes(schema);
    if (isCycle) {
      seen.cycle = _params.path;
    }
    return seen.schema;
  }
  const result = { schema: {}, count: 1, cycle: void 0, path: _params.path };
  ctx.seen.set(schema, result);
  const overrideSchema = schema._zod.toJSONSchema?.();
  if (overrideSchema) {
    result.schema = overrideSchema;
  } else {
    const params = {
      ..._params,
      schemaPath: [..._params.schemaPath, schema],
      path: _params.path
    };
    if (schema._zod.processJSONSchema) {
      schema._zod.processJSONSchema(ctx, result.schema, params);
    } else {
      const _json = result.schema;
      const processor = ctx.processors[def.type];
      if (!processor) {
        throw new Error(`[toJSONSchema]: Non-representable type encountered: ${def.type}`);
      }
      processor(schema, ctx, _json, params);
    }
    const parent = schema._zod.parent;
    if (parent) {
      if (!result.ref)
        result.ref = parent;
      process$1(parent, ctx, params);
      ctx.seen.get(parent).isParent = true;
    }
  }
  const meta = ctx.metadataRegistry.get(schema);
  if (meta)
    Object.assign(result.schema, meta);
  if (ctx.io === "input" && isTransforming(schema)) {
    delete result.schema.examples;
    delete result.schema.default;
  }
  if (ctx.io === "input" && result.schema._prefault)
    (_a2 = result.schema).default ?? (_a2.default = result.schema._prefault);
  delete result.schema._prefault;
  const _result = ctx.seen.get(schema);
  return _result.schema;
}
function extractDefs(ctx, schema) {
  const root = ctx.seen.get(schema);
  if (!root)
    throw new Error("Unprocessed schema. This is a bug in Zod.");
  const idToSchema = /* @__PURE__ */ new Map();
  for (const entry of ctx.seen.entries()) {
    const id = ctx.metadataRegistry.get(entry[0])?.id;
    if (id) {
      const existing = idToSchema.get(id);
      if (existing && existing !== entry[0]) {
        throw new Error(`Duplicate schema id "${id}" detected during JSON Schema conversion. Two different schemas cannot share the same id when converted together.`);
      }
      idToSchema.set(id, entry[0]);
    }
  }
  const makeURI = (entry) => {
    const defsSegment = ctx.target === "draft-2020-12" ? "$defs" : "definitions";
    if (ctx.external) {
      const externalId = ctx.external.registry.get(entry[0])?.id;
      const uriGenerator = ctx.external.uri ?? ((id2) => id2);
      if (externalId) {
        return { ref: uriGenerator(externalId) };
      }
      const id = entry[1].defId ?? entry[1].schema.id ?? `schema${ctx.counter++}`;
      entry[1].defId = id;
      return { defId: id, ref: `${uriGenerator("__shared")}#/${defsSegment}/${id}` };
    }
    if (entry[1] === root) {
      return { ref: "#" };
    }
    const uriPrefix = `#`;
    const defUriPrefix = `${uriPrefix}/${defsSegment}/`;
    const defId = entry[1].schema.id ?? `__schema${ctx.counter++}`;
    return { defId, ref: defUriPrefix + defId };
  };
  const extractToDef = (entry) => {
    if (entry[1].schema.$ref) {
      return;
    }
    const seen = entry[1];
    const { ref, defId } = makeURI(entry);
    seen.def = { ...seen.schema };
    if (defId)
      seen.defId = defId;
    const schema2 = seen.schema;
    for (const key in schema2) {
      delete schema2[key];
    }
    schema2.$ref = ref;
  };
  if (ctx.cycles === "throw") {
    for (const entry of ctx.seen.entries()) {
      const seen = entry[1];
      if (seen.cycle) {
        throw new Error(`Cycle detected: #/${seen.cycle?.join("/")}/<root>

Set the \`cycles\` parameter to \`"ref"\` to resolve cyclical schemas with defs.`);
      }
    }
  }
  for (const entry of ctx.seen.entries()) {
    const seen = entry[1];
    if (schema === entry[0]) {
      extractToDef(entry);
      continue;
    }
    if (ctx.external) {
      const ext = ctx.external.registry.get(entry[0])?.id;
      if (schema !== entry[0] && ext) {
        extractToDef(entry);
        continue;
      }
    }
    const id = ctx.metadataRegistry.get(entry[0])?.id;
    if (id) {
      extractToDef(entry);
      continue;
    }
    if (seen.cycle) {
      extractToDef(entry);
      continue;
    }
    if (seen.count > 1) {
      if (ctx.reused === "ref") {
        extractToDef(entry);
        continue;
      }
    }
  }
}
function finalize(ctx, schema) {
  const root = ctx.seen.get(schema);
  if (!root)
    throw new Error("Unprocessed schema. This is a bug in Zod.");
  const flattenRef = (zodSchema) => {
    const seen = ctx.seen.get(zodSchema);
    if (seen.ref === null)
      return;
    const schema2 = seen.def ?? seen.schema;
    const _cached = { ...schema2 };
    const ref = seen.ref;
    seen.ref = null;
    if (ref) {
      flattenRef(ref);
      const refSeen = ctx.seen.get(ref);
      const refSchema = refSeen.schema;
      if (refSchema.$ref && (ctx.target === "draft-07" || ctx.target === "draft-04" || ctx.target === "openapi-3.0")) {
        schema2.allOf = schema2.allOf ?? [];
        schema2.allOf.push(refSchema);
      } else {
        Object.assign(schema2, refSchema);
      }
      Object.assign(schema2, _cached);
      const isParentRef = zodSchema._zod.parent === ref;
      if (isParentRef) {
        for (const key in schema2) {
          if (key === "$ref" || key === "allOf")
            continue;
          if (!(key in _cached)) {
            delete schema2[key];
          }
        }
      }
      if (refSchema.$ref && refSeen.def) {
        for (const key in schema2) {
          if (key === "$ref" || key === "allOf")
            continue;
          if (key in refSeen.def && JSON.stringify(schema2[key]) === JSON.stringify(refSeen.def[key])) {
            delete schema2[key];
          }
        }
      }
    }
    const parent = zodSchema._zod.parent;
    if (parent && parent !== ref) {
      flattenRef(parent);
      const parentSeen = ctx.seen.get(parent);
      if (parentSeen?.schema.$ref) {
        schema2.$ref = parentSeen.schema.$ref;
        if (parentSeen.def) {
          for (const key in schema2) {
            if (key === "$ref" || key === "allOf")
              continue;
            if (key in parentSeen.def && JSON.stringify(schema2[key]) === JSON.stringify(parentSeen.def[key])) {
              delete schema2[key];
            }
          }
        }
      }
    }
    ctx.override({
      zodSchema,
      jsonSchema: schema2,
      path: seen.path ?? []
    });
  };
  for (const entry of [...ctx.seen.entries()].reverse()) {
    flattenRef(entry[0]);
  }
  const result = {};
  if (ctx.target === "draft-2020-12") {
    result.$schema = "https://json-schema.org/draft/2020-12/schema";
  } else if (ctx.target === "draft-07") {
    result.$schema = "http://json-schema.org/draft-07/schema#";
  } else if (ctx.target === "draft-04") {
    result.$schema = "http://json-schema.org/draft-04/schema#";
  } else if (ctx.target === "openapi-3.0") ;
  else ;
  if (ctx.external?.uri) {
    const id = ctx.external.registry.get(schema)?.id;
    if (!id)
      throw new Error("Schema is missing an `id` property");
    result.$id = ctx.external.uri(id);
  }
  Object.assign(result, root.def ?? root.schema);
  const defs = ctx.external?.defs ?? {};
  for (const entry of ctx.seen.entries()) {
    const seen = entry[1];
    if (seen.def && seen.defId) {
      defs[seen.defId] = seen.def;
    }
  }
  if (ctx.external) ;
  else {
    if (Object.keys(defs).length > 0) {
      if (ctx.target === "draft-2020-12") {
        result.$defs = defs;
      } else {
        result.definitions = defs;
      }
    }
  }
  try {
    const finalized = JSON.parse(JSON.stringify(result));
    Object.defineProperty(finalized, "~standard", {
      value: {
        ...schema["~standard"],
        jsonSchema: {
          input: createStandardJSONSchemaMethod(schema, "input", ctx.processors),
          output: createStandardJSONSchemaMethod(schema, "output", ctx.processors)
        }
      },
      enumerable: false,
      writable: false
    });
    return finalized;
  } catch (_err) {
    throw new Error("Error converting schema to JSON.");
  }
}
function isTransforming(_schema, _ctx) {
  const ctx = _ctx ?? { seen: /* @__PURE__ */ new Set() };
  if (ctx.seen.has(_schema))
    return false;
  ctx.seen.add(_schema);
  const def = _schema._zod.def;
  if (def.type === "transform")
    return true;
  if (def.type === "array")
    return isTransforming(def.element, ctx);
  if (def.type === "set")
    return isTransforming(def.valueType, ctx);
  if (def.type === "lazy")
    return isTransforming(def.getter(), ctx);
  if (def.type === "promise" || def.type === "optional" || def.type === "nonoptional" || def.type === "nullable" || def.type === "readonly" || def.type === "default" || def.type === "prefault") {
    return isTransforming(def.innerType, ctx);
  }
  if (def.type === "intersection") {
    return isTransforming(def.left, ctx) || isTransforming(def.right, ctx);
  }
  if (def.type === "record" || def.type === "map") {
    return isTransforming(def.keyType, ctx) || isTransforming(def.valueType, ctx);
  }
  if (def.type === "pipe") {
    return isTransforming(def.in, ctx) || isTransforming(def.out, ctx);
  }
  if (def.type === "object") {
    for (const key in def.shape) {
      if (isTransforming(def.shape[key], ctx))
        return true;
    }
    return false;
  }
  if (def.type === "union") {
    for (const option of def.options) {
      if (isTransforming(option, ctx))
        return true;
    }
    return false;
  }
  if (def.type === "tuple") {
    for (const item of def.items) {
      if (isTransforming(item, ctx))
        return true;
    }
    if (def.rest && isTransforming(def.rest, ctx))
      return true;
    return false;
  }
  return false;
}
const createToJSONSchemaMethod = (schema, processors = {}) => (params) => {
  const ctx = initializeContext({ ...params, processors });
  process$1(schema, ctx);
  extractDefs(ctx, schema);
  return finalize(ctx, schema);
};
const createStandardJSONSchemaMethod = (schema, io, processors = {}) => (params) => {
  const { libraryOptions, target } = params ?? {};
  const ctx = initializeContext({ ...libraryOptions ?? {}, target, io, processors });
  process$1(schema, ctx);
  extractDefs(ctx, schema);
  return finalize(ctx, schema);
};
const formatMap = {
  guid: "uuid",
  url: "uri",
  datetime: "date-time",
  json_string: "json-string",
  regex: ""
  // do not set
};
const stringProcessor = (schema, ctx, _json, _params) => {
  const json = _json;
  json.type = "string";
  const { minimum, maximum, format: format2, patterns, contentEncoding } = schema._zod.bag;
  if (typeof minimum === "number")
    json.minLength = minimum;
  if (typeof maximum === "number")
    json.maxLength = maximum;
  if (format2) {
    json.format = formatMap[format2] ?? format2;
    if (json.format === "")
      delete json.format;
    if (format2 === "time") {
      delete json.format;
    }
  }
  if (contentEncoding)
    json.contentEncoding = contentEncoding;
  if (patterns && patterns.size > 0) {
    const regexes = [...patterns];
    if (regexes.length === 1)
      json.pattern = regexes[0].source;
    else if (regexes.length > 1) {
      json.allOf = [
        ...regexes.map((regex) => ({
          ...ctx.target === "draft-07" || ctx.target === "draft-04" || ctx.target === "openapi-3.0" ? { type: "string" } : {},
          pattern: regex.source
        }))
      ];
    }
  }
};
const numberProcessor = (schema, ctx, _json, _params) => {
  const json = _json;
  const { minimum, maximum, format: format2, multipleOf, exclusiveMaximum, exclusiveMinimum } = schema._zod.bag;
  if (typeof format2 === "string" && format2.includes("int"))
    json.type = "integer";
  else
    json.type = "number";
  if (typeof exclusiveMinimum === "number") {
    if (ctx.target === "draft-04" || ctx.target === "openapi-3.0") {
      json.minimum = exclusiveMinimum;
      json.exclusiveMinimum = true;
    } else {
      json.exclusiveMinimum = exclusiveMinimum;
    }
  }
  if (typeof minimum === "number") {
    json.minimum = minimum;
    if (typeof exclusiveMinimum === "number" && ctx.target !== "draft-04") {
      if (exclusiveMinimum >= minimum)
        delete json.minimum;
      else
        delete json.exclusiveMinimum;
    }
  }
  if (typeof exclusiveMaximum === "number") {
    if (ctx.target === "draft-04" || ctx.target === "openapi-3.0") {
      json.maximum = exclusiveMaximum;
      json.exclusiveMaximum = true;
    } else {
      json.exclusiveMaximum = exclusiveMaximum;
    }
  }
  if (typeof maximum === "number") {
    json.maximum = maximum;
    if (typeof exclusiveMaximum === "number" && ctx.target !== "draft-04") {
      if (exclusiveMaximum <= maximum)
        delete json.maximum;
      else
        delete json.exclusiveMaximum;
    }
  }
  if (typeof multipleOf === "number")
    json.multipleOf = multipleOf;
};
const booleanProcessor = (_schema, _ctx, json, _params) => {
  json.type = "boolean";
};
const neverProcessor = (_schema, _ctx, json, _params) => {
  json.not = {};
};
const unknownProcessor = (_schema, _ctx, _json, _params) => {
};
const enumProcessor = (schema, _ctx, json, _params) => {
  const def = schema._zod.def;
  const values = getEnumValues(def.entries);
  if (values.every((v) => typeof v === "number"))
    json.type = "number";
  if (values.every((v) => typeof v === "string"))
    json.type = "string";
  json.enum = values;
};
const customProcessor = (_schema, ctx, _json, _params) => {
  if (ctx.unrepresentable === "throw") {
    throw new Error("Custom types cannot be represented in JSON Schema");
  }
};
const transformProcessor = (_schema, ctx, _json, _params) => {
  if (ctx.unrepresentable === "throw") {
    throw new Error("Transforms cannot be represented in JSON Schema");
  }
};
const arrayProcessor = (schema, ctx, _json, params) => {
  const json = _json;
  const def = schema._zod.def;
  const { minimum, maximum } = schema._zod.bag;
  if (typeof minimum === "number")
    json.minItems = minimum;
  if (typeof maximum === "number")
    json.maxItems = maximum;
  json.type = "array";
  json.items = process$1(def.element, ctx, { ...params, path: [...params.path, "items"] });
};
const objectProcessor = (schema, ctx, _json, params) => {
  const json = _json;
  const def = schema._zod.def;
  json.type = "object";
  json.properties = {};
  const shape = def.shape;
  for (const key in shape) {
    json.properties[key] = process$1(shape[key], ctx, {
      ...params,
      path: [...params.path, "properties", key]
    });
  }
  const allKeys = new Set(Object.keys(shape));
  const requiredKeys = new Set([...allKeys].filter((key) => {
    const v = def.shape[key]._zod;
    if (ctx.io === "input") {
      return v.optin === void 0;
    } else {
      return v.optout === void 0;
    }
  }));
  if (requiredKeys.size > 0) {
    json.required = Array.from(requiredKeys);
  }
  if (def.catchall?._zod.def.type === "never") {
    json.additionalProperties = false;
  } else if (!def.catchall) {
    if (ctx.io === "output")
      json.additionalProperties = false;
  } else if (def.catchall) {
    json.additionalProperties = process$1(def.catchall, ctx, {
      ...params,
      path: [...params.path, "additionalProperties"]
    });
  }
};
const unionProcessor = (schema, ctx, json, params) => {
  const def = schema._zod.def;
  const isExclusive = def.inclusive === false;
  const options = def.options.map((x, i) => process$1(x, ctx, {
    ...params,
    path: [...params.path, isExclusive ? "oneOf" : "anyOf", i]
  }));
  if (isExclusive) {
    json.oneOf = options;
  } else {
    json.anyOf = options;
  }
};
const intersectionProcessor = (schema, ctx, json, params) => {
  const def = schema._zod.def;
  const a = process$1(def.left, ctx, {
    ...params,
    path: [...params.path, "allOf", 0]
  });
  const b = process$1(def.right, ctx, {
    ...params,
    path: [...params.path, "allOf", 1]
  });
  const isSimpleIntersection = (val) => "allOf" in val && Object.keys(val).length === 1;
  const allOf = [
    ...isSimpleIntersection(a) ? a.allOf : [a],
    ...isSimpleIntersection(b) ? b.allOf : [b]
  ];
  json.allOf = allOf;
};
const recordProcessor = (schema, ctx, _json, params) => {
  const json = _json;
  const def = schema._zod.def;
  json.type = "object";
  const keyType = def.keyType;
  const keyBag = keyType._zod.bag;
  const patterns = keyBag?.patterns;
  if (def.mode === "loose" && patterns && patterns.size > 0) {
    const valueSchema = process$1(def.valueType, ctx, {
      ...params,
      path: [...params.path, "patternProperties", "*"]
    });
    json.patternProperties = {};
    for (const pattern of patterns) {
      json.patternProperties[pattern.source] = valueSchema;
    }
  } else {
    if (ctx.target === "draft-07" || ctx.target === "draft-2020-12") {
      json.propertyNames = process$1(def.keyType, ctx, {
        ...params,
        path: [...params.path, "propertyNames"]
      });
    }
    json.additionalProperties = process$1(def.valueType, ctx, {
      ...params,
      path: [...params.path, "additionalProperties"]
    });
  }
  const keyValues = keyType._zod.values;
  if (keyValues) {
    const validKeyValues = [...keyValues].filter((v) => typeof v === "string" || typeof v === "number");
    if (validKeyValues.length > 0) {
      json.required = validKeyValues;
    }
  }
};
const nullableProcessor = (schema, ctx, json, params) => {
  const def = schema._zod.def;
  const inner = process$1(def.innerType, ctx, params);
  const seen = ctx.seen.get(schema);
  if (ctx.target === "openapi-3.0") {
    seen.ref = def.innerType;
    json.nullable = true;
  } else {
    json.anyOf = [inner, { type: "null" }];
  }
};
const nonoptionalProcessor = (schema, ctx, _json, params) => {
  const def = schema._zod.def;
  process$1(def.innerType, ctx, params);
  const seen = ctx.seen.get(schema);
  seen.ref = def.innerType;
};
const defaultProcessor = (schema, ctx, json, params) => {
  const def = schema._zod.def;
  process$1(def.innerType, ctx, params);
  const seen = ctx.seen.get(schema);
  seen.ref = def.innerType;
  json.default = JSON.parse(JSON.stringify(def.defaultValue));
};
const prefaultProcessor = (schema, ctx, json, params) => {
  const def = schema._zod.def;
  process$1(def.innerType, ctx, params);
  const seen = ctx.seen.get(schema);
  seen.ref = def.innerType;
  if (ctx.io === "input")
    json._prefault = JSON.parse(JSON.stringify(def.defaultValue));
};
const catchProcessor = (schema, ctx, json, params) => {
  const def = schema._zod.def;
  process$1(def.innerType, ctx, params);
  const seen = ctx.seen.get(schema);
  seen.ref = def.innerType;
  let catchValue;
  try {
    catchValue = def.catchValue(void 0);
  } catch {
    throw new Error("Dynamic catch values are not supported in JSON Schema");
  }
  json.default = catchValue;
};
const pipeProcessor = (schema, ctx, _json, params) => {
  const def = schema._zod.def;
  const innerType = ctx.io === "input" ? def.in._zod.def.type === "transform" ? def.out : def.in : def.out;
  process$1(innerType, ctx, params);
  const seen = ctx.seen.get(schema);
  seen.ref = innerType;
};
const readonlyProcessor = (schema, ctx, json, params) => {
  const def = schema._zod.def;
  process$1(def.innerType, ctx, params);
  const seen = ctx.seen.get(schema);
  seen.ref = def.innerType;
  json.readOnly = true;
};
const optionalProcessor = (schema, ctx, _json, params) => {
  const def = schema._zod.def;
  process$1(def.innerType, ctx, params);
  const seen = ctx.seen.get(schema);
  seen.ref = def.innerType;
};
const ZodISODateTime = /* @__PURE__ */ $constructor("ZodISODateTime", (inst, def) => {
  $ZodISODateTime.init(inst, def);
  ZodStringFormat.init(inst, def);
});
function datetime(params) {
  return /* @__PURE__ */ _isoDateTime(ZodISODateTime, params);
}
const ZodISODate = /* @__PURE__ */ $constructor("ZodISODate", (inst, def) => {
  $ZodISODate.init(inst, def);
  ZodStringFormat.init(inst, def);
});
function date(params) {
  return /* @__PURE__ */ _isoDate(ZodISODate, params);
}
const ZodISOTime = /* @__PURE__ */ $constructor("ZodISOTime", (inst, def) => {
  $ZodISOTime.init(inst, def);
  ZodStringFormat.init(inst, def);
});
function time(params) {
  return /* @__PURE__ */ _isoTime(ZodISOTime, params);
}
const ZodISODuration = /* @__PURE__ */ $constructor("ZodISODuration", (inst, def) => {
  $ZodISODuration.init(inst, def);
  ZodStringFormat.init(inst, def);
});
function duration(params) {
  return /* @__PURE__ */ _isoDuration(ZodISODuration, params);
}
const initializer = (inst, issues) => {
  $ZodError.init(inst, issues);
  inst.name = "ZodError";
  Object.defineProperties(inst, {
    format: {
      value: (mapper) => formatError(inst, mapper)
      // enumerable: false,
    },
    flatten: {
      value: (mapper) => flattenError(inst, mapper)
      // enumerable: false,
    },
    addIssue: {
      value: (issue2) => {
        inst.issues.push(issue2);
        inst.message = JSON.stringify(inst.issues, jsonStringifyReplacer, 2);
      }
      // enumerable: false,
    },
    addIssues: {
      value: (issues2) => {
        inst.issues.push(...issues2);
        inst.message = JSON.stringify(inst.issues, jsonStringifyReplacer, 2);
      }
      // enumerable: false,
    },
    isEmpty: {
      get() {
        return inst.issues.length === 0;
      }
      // enumerable: false,
    }
  });
};
const ZodRealError = $constructor("ZodError", initializer, {
  Parent: Error
});
const parse = /* @__PURE__ */ _parse(ZodRealError);
const parseAsync = /* @__PURE__ */ _parseAsync(ZodRealError);
const safeParse = /* @__PURE__ */ _safeParse(ZodRealError);
const safeParseAsync = /* @__PURE__ */ _safeParseAsync(ZodRealError);
const encode = /* @__PURE__ */ _encode(ZodRealError);
const decode = /* @__PURE__ */ _decode(ZodRealError);
const encodeAsync = /* @__PURE__ */ _encodeAsync(ZodRealError);
const decodeAsync = /* @__PURE__ */ _decodeAsync(ZodRealError);
const safeEncode = /* @__PURE__ */ _safeEncode(ZodRealError);
const safeDecode = /* @__PURE__ */ _safeDecode(ZodRealError);
const safeEncodeAsync = /* @__PURE__ */ _safeEncodeAsync(ZodRealError);
const safeDecodeAsync = /* @__PURE__ */ _safeDecodeAsync(ZodRealError);
const ZodType = /* @__PURE__ */ $constructor("ZodType", (inst, def) => {
  $ZodType.init(inst, def);
  Object.assign(inst["~standard"], {
    jsonSchema: {
      input: createStandardJSONSchemaMethod(inst, "input"),
      output: createStandardJSONSchemaMethod(inst, "output")
    }
  });
  inst.toJSONSchema = createToJSONSchemaMethod(inst, {});
  inst.def = def;
  inst.type = def.type;
  Object.defineProperty(inst, "_def", { value: def });
  inst.check = (...checks) => {
    return inst.clone(mergeDefs(def, {
      checks: [
        ...def.checks ?? [],
        ...checks.map((ch) => typeof ch === "function" ? { _zod: { check: ch, def: { check: "custom" }, onattach: [] } } : ch)
      ]
    }), {
      parent: true
    });
  };
  inst.with = inst.check;
  inst.clone = (def2, params) => clone(inst, def2, params);
  inst.brand = () => inst;
  inst.register = ((reg, meta) => {
    reg.add(inst, meta);
    return inst;
  });
  inst.parse = (data, params) => parse(inst, data, params, { callee: inst.parse });
  inst.safeParse = (data, params) => safeParse(inst, data, params);
  inst.parseAsync = async (data, params) => parseAsync(inst, data, params, { callee: inst.parseAsync });
  inst.safeParseAsync = async (data, params) => safeParseAsync(inst, data, params);
  inst.spa = inst.safeParseAsync;
  inst.encode = (data, params) => encode(inst, data, params);
  inst.decode = (data, params) => decode(inst, data, params);
  inst.encodeAsync = async (data, params) => encodeAsync(inst, data, params);
  inst.decodeAsync = async (data, params) => decodeAsync(inst, data, params);
  inst.safeEncode = (data, params) => safeEncode(inst, data, params);
  inst.safeDecode = (data, params) => safeDecode(inst, data, params);
  inst.safeEncodeAsync = async (data, params) => safeEncodeAsync(inst, data, params);
  inst.safeDecodeAsync = async (data, params) => safeDecodeAsync(inst, data, params);
  inst.refine = (check, params) => inst.check(refine(check, params));
  inst.superRefine = (refinement) => inst.check(superRefine(refinement));
  inst.overwrite = (fn) => inst.check(/* @__PURE__ */ _overwrite(fn));
  inst.optional = () => optional(inst);
  inst.exactOptional = () => exactOptional(inst);
  inst.nullable = () => nullable(inst);
  inst.nullish = () => optional(nullable(inst));
  inst.nonoptional = (params) => nonoptional(inst, params);
  inst.array = () => array(inst);
  inst.or = (arg) => union([inst, arg]);
  inst.and = (arg) => intersection(inst, arg);
  inst.transform = (tx) => pipe(inst, transform(tx));
  inst.default = (def2) => _default(inst, def2);
  inst.prefault = (def2) => prefault(inst, def2);
  inst.catch = (params) => _catch(inst, params);
  inst.pipe = (target) => pipe(inst, target);
  inst.readonly = () => readonly(inst);
  inst.describe = (description) => {
    const cl = inst.clone();
    globalRegistry.add(cl, { description });
    return cl;
  };
  Object.defineProperty(inst, "description", {
    get() {
      return globalRegistry.get(inst)?.description;
    },
    configurable: true
  });
  inst.meta = (...args) => {
    if (args.length === 0) {
      return globalRegistry.get(inst);
    }
    const cl = inst.clone();
    globalRegistry.add(cl, args[0]);
    return cl;
  };
  inst.isOptional = () => inst.safeParse(void 0).success;
  inst.isNullable = () => inst.safeParse(null).success;
  inst.apply = (fn) => fn(inst);
  return inst;
});
const _ZodString = /* @__PURE__ */ $constructor("_ZodString", (inst, def) => {
  $ZodString.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => stringProcessor(inst, ctx, json);
  const bag = inst._zod.bag;
  inst.format = bag.format ?? null;
  inst.minLength = bag.minimum ?? null;
  inst.maxLength = bag.maximum ?? null;
  inst.regex = (...args) => inst.check(/* @__PURE__ */ _regex(...args));
  inst.includes = (...args) => inst.check(/* @__PURE__ */ _includes(...args));
  inst.startsWith = (...args) => inst.check(/* @__PURE__ */ _startsWith(...args));
  inst.endsWith = (...args) => inst.check(/* @__PURE__ */ _endsWith(...args));
  inst.min = (...args) => inst.check(/* @__PURE__ */ _minLength(...args));
  inst.max = (...args) => inst.check(/* @__PURE__ */ _maxLength(...args));
  inst.length = (...args) => inst.check(/* @__PURE__ */ _length(...args));
  inst.nonempty = (...args) => inst.check(/* @__PURE__ */ _minLength(1, ...args));
  inst.lowercase = (params) => inst.check(/* @__PURE__ */ _lowercase(params));
  inst.uppercase = (params) => inst.check(/* @__PURE__ */ _uppercase(params));
  inst.trim = () => inst.check(/* @__PURE__ */ _trim());
  inst.normalize = (...args) => inst.check(/* @__PURE__ */ _normalize(...args));
  inst.toLowerCase = () => inst.check(/* @__PURE__ */ _toLowerCase());
  inst.toUpperCase = () => inst.check(/* @__PURE__ */ _toUpperCase());
  inst.slugify = () => inst.check(/* @__PURE__ */ _slugify());
});
const ZodString = /* @__PURE__ */ $constructor("ZodString", (inst, def) => {
  $ZodString.init(inst, def);
  _ZodString.init(inst, def);
  inst.email = (params) => inst.check(/* @__PURE__ */ _email(ZodEmail, params));
  inst.url = (params) => inst.check(/* @__PURE__ */ _url(ZodURL, params));
  inst.jwt = (params) => inst.check(/* @__PURE__ */ _jwt(ZodJWT, params));
  inst.emoji = (params) => inst.check(/* @__PURE__ */ _emoji(ZodEmoji, params));
  inst.guid = (params) => inst.check(/* @__PURE__ */ _guid(ZodGUID, params));
  inst.uuid = (params) => inst.check(/* @__PURE__ */ _uuid(ZodUUID, params));
  inst.uuidv4 = (params) => inst.check(/* @__PURE__ */ _uuidv4(ZodUUID, params));
  inst.uuidv6 = (params) => inst.check(/* @__PURE__ */ _uuidv6(ZodUUID, params));
  inst.uuidv7 = (params) => inst.check(/* @__PURE__ */ _uuidv7(ZodUUID, params));
  inst.nanoid = (params) => inst.check(/* @__PURE__ */ _nanoid(ZodNanoID, params));
  inst.guid = (params) => inst.check(/* @__PURE__ */ _guid(ZodGUID, params));
  inst.cuid = (params) => inst.check(/* @__PURE__ */ _cuid(ZodCUID, params));
  inst.cuid2 = (params) => inst.check(/* @__PURE__ */ _cuid2(ZodCUID2, params));
  inst.ulid = (params) => inst.check(/* @__PURE__ */ _ulid(ZodULID, params));
  inst.base64 = (params) => inst.check(/* @__PURE__ */ _base64(ZodBase64, params));
  inst.base64url = (params) => inst.check(/* @__PURE__ */ _base64url(ZodBase64URL, params));
  inst.xid = (params) => inst.check(/* @__PURE__ */ _xid(ZodXID, params));
  inst.ksuid = (params) => inst.check(/* @__PURE__ */ _ksuid(ZodKSUID, params));
  inst.ipv4 = (params) => inst.check(/* @__PURE__ */ _ipv4(ZodIPv4, params));
  inst.ipv6 = (params) => inst.check(/* @__PURE__ */ _ipv6(ZodIPv6, params));
  inst.cidrv4 = (params) => inst.check(/* @__PURE__ */ _cidrv4(ZodCIDRv4, params));
  inst.cidrv6 = (params) => inst.check(/* @__PURE__ */ _cidrv6(ZodCIDRv6, params));
  inst.e164 = (params) => inst.check(/* @__PURE__ */ _e164(ZodE164, params));
  inst.datetime = (params) => inst.check(datetime(params));
  inst.date = (params) => inst.check(date(params));
  inst.time = (params) => inst.check(time(params));
  inst.duration = (params) => inst.check(duration(params));
});
function string(params) {
  return /* @__PURE__ */ _string(ZodString, params);
}
const ZodStringFormat = /* @__PURE__ */ $constructor("ZodStringFormat", (inst, def) => {
  $ZodStringFormat.init(inst, def);
  _ZodString.init(inst, def);
});
const ZodEmail = /* @__PURE__ */ $constructor("ZodEmail", (inst, def) => {
  $ZodEmail.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodGUID = /* @__PURE__ */ $constructor("ZodGUID", (inst, def) => {
  $ZodGUID.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodUUID = /* @__PURE__ */ $constructor("ZodUUID", (inst, def) => {
  $ZodUUID.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodURL = /* @__PURE__ */ $constructor("ZodURL", (inst, def) => {
  $ZodURL.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodEmoji = /* @__PURE__ */ $constructor("ZodEmoji", (inst, def) => {
  $ZodEmoji.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodNanoID = /* @__PURE__ */ $constructor("ZodNanoID", (inst, def) => {
  $ZodNanoID.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodCUID = /* @__PURE__ */ $constructor("ZodCUID", (inst, def) => {
  $ZodCUID.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodCUID2 = /* @__PURE__ */ $constructor("ZodCUID2", (inst, def) => {
  $ZodCUID2.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodULID = /* @__PURE__ */ $constructor("ZodULID", (inst, def) => {
  $ZodULID.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodXID = /* @__PURE__ */ $constructor("ZodXID", (inst, def) => {
  $ZodXID.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodKSUID = /* @__PURE__ */ $constructor("ZodKSUID", (inst, def) => {
  $ZodKSUID.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodIPv4 = /* @__PURE__ */ $constructor("ZodIPv4", (inst, def) => {
  $ZodIPv4.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodIPv6 = /* @__PURE__ */ $constructor("ZodIPv6", (inst, def) => {
  $ZodIPv6.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodCIDRv4 = /* @__PURE__ */ $constructor("ZodCIDRv4", (inst, def) => {
  $ZodCIDRv4.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodCIDRv6 = /* @__PURE__ */ $constructor("ZodCIDRv6", (inst, def) => {
  $ZodCIDRv6.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodBase64 = /* @__PURE__ */ $constructor("ZodBase64", (inst, def) => {
  $ZodBase64.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodBase64URL = /* @__PURE__ */ $constructor("ZodBase64URL", (inst, def) => {
  $ZodBase64URL.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodE164 = /* @__PURE__ */ $constructor("ZodE164", (inst, def) => {
  $ZodE164.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodJWT = /* @__PURE__ */ $constructor("ZodJWT", (inst, def) => {
  $ZodJWT.init(inst, def);
  ZodStringFormat.init(inst, def);
});
const ZodNumber = /* @__PURE__ */ $constructor("ZodNumber", (inst, def) => {
  $ZodNumber.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => numberProcessor(inst, ctx, json);
  inst.gt = (value, params) => inst.check(/* @__PURE__ */ _gt(value, params));
  inst.gte = (value, params) => inst.check(/* @__PURE__ */ _gte(value, params));
  inst.min = (value, params) => inst.check(/* @__PURE__ */ _gte(value, params));
  inst.lt = (value, params) => inst.check(/* @__PURE__ */ _lt(value, params));
  inst.lte = (value, params) => inst.check(/* @__PURE__ */ _lte(value, params));
  inst.max = (value, params) => inst.check(/* @__PURE__ */ _lte(value, params));
  inst.int = (params) => inst.check(int(params));
  inst.safe = (params) => inst.check(int(params));
  inst.positive = (params) => inst.check(/* @__PURE__ */ _gt(0, params));
  inst.nonnegative = (params) => inst.check(/* @__PURE__ */ _gte(0, params));
  inst.negative = (params) => inst.check(/* @__PURE__ */ _lt(0, params));
  inst.nonpositive = (params) => inst.check(/* @__PURE__ */ _lte(0, params));
  inst.multipleOf = (value, params) => inst.check(/* @__PURE__ */ _multipleOf(value, params));
  inst.step = (value, params) => inst.check(/* @__PURE__ */ _multipleOf(value, params));
  inst.finite = () => inst;
  const bag = inst._zod.bag;
  inst.minValue = Math.max(bag.minimum ?? Number.NEGATIVE_INFINITY, bag.exclusiveMinimum ?? Number.NEGATIVE_INFINITY) ?? null;
  inst.maxValue = Math.min(bag.maximum ?? Number.POSITIVE_INFINITY, bag.exclusiveMaximum ?? Number.POSITIVE_INFINITY) ?? null;
  inst.isInt = (bag.format ?? "").includes("int") || Number.isSafeInteger(bag.multipleOf ?? 0.5);
  inst.isFinite = true;
  inst.format = bag.format ?? null;
});
function number(params) {
  return /* @__PURE__ */ _number(ZodNumber, params);
}
const ZodNumberFormat = /* @__PURE__ */ $constructor("ZodNumberFormat", (inst, def) => {
  $ZodNumberFormat.init(inst, def);
  ZodNumber.init(inst, def);
});
function int(params) {
  return /* @__PURE__ */ _int(ZodNumberFormat, params);
}
const ZodBoolean = /* @__PURE__ */ $constructor("ZodBoolean", (inst, def) => {
  $ZodBoolean.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => booleanProcessor(inst, ctx, json);
});
function boolean(params) {
  return /* @__PURE__ */ _boolean(ZodBoolean, params);
}
const ZodUnknown = /* @__PURE__ */ $constructor("ZodUnknown", (inst, def) => {
  $ZodUnknown.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => unknownProcessor();
});
function unknown() {
  return /* @__PURE__ */ _unknown(ZodUnknown);
}
const ZodNever = /* @__PURE__ */ $constructor("ZodNever", (inst, def) => {
  $ZodNever.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => neverProcessor(inst, ctx, json);
});
function never(params) {
  return /* @__PURE__ */ _never(ZodNever, params);
}
const ZodArray = /* @__PURE__ */ $constructor("ZodArray", (inst, def) => {
  $ZodArray.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => arrayProcessor(inst, ctx, json, params);
  inst.element = def.element;
  inst.min = (minLength, params) => inst.check(/* @__PURE__ */ _minLength(minLength, params));
  inst.nonempty = (params) => inst.check(/* @__PURE__ */ _minLength(1, params));
  inst.max = (maxLength, params) => inst.check(/* @__PURE__ */ _maxLength(maxLength, params));
  inst.length = (len, params) => inst.check(/* @__PURE__ */ _length(len, params));
  inst.unwrap = () => inst.element;
});
function array(element, params) {
  return /* @__PURE__ */ _array(ZodArray, element, params);
}
const ZodObject = /* @__PURE__ */ $constructor("ZodObject", (inst, def) => {
  $ZodObjectJIT.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => objectProcessor(inst, ctx, json, params);
  defineLazy(inst, "shape", () => {
    return def.shape;
  });
  inst.keyof = () => _enum(Object.keys(inst._zod.def.shape));
  inst.catchall = (catchall) => inst.clone({ ...inst._zod.def, catchall });
  inst.passthrough = () => inst.clone({ ...inst._zod.def, catchall: unknown() });
  inst.loose = () => inst.clone({ ...inst._zod.def, catchall: unknown() });
  inst.strict = () => inst.clone({ ...inst._zod.def, catchall: never() });
  inst.strip = () => inst.clone({ ...inst._zod.def, catchall: void 0 });
  inst.extend = (incoming) => {
    return extend(inst, incoming);
  };
  inst.safeExtend = (incoming) => {
    return safeExtend(inst, incoming);
  };
  inst.merge = (other) => merge(inst, other);
  inst.pick = (mask) => pick(inst, mask);
  inst.omit = (mask) => omit(inst, mask);
  inst.partial = (...args) => partial(ZodOptional, inst, args[0]);
  inst.required = (...args) => required(ZodNonOptional, inst, args[0]);
});
function object(shape, params) {
  const def = {
    type: "object",
    shape: shape ?? {},
    ...normalizeParams(params)
  };
  return new ZodObject(def);
}
const ZodUnion = /* @__PURE__ */ $constructor("ZodUnion", (inst, def) => {
  $ZodUnion.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => unionProcessor(inst, ctx, json, params);
  inst.options = def.options;
});
function union(options, params) {
  return new ZodUnion({
    type: "union",
    options,
    ...normalizeParams(params)
  });
}
const ZodIntersection = /* @__PURE__ */ $constructor("ZodIntersection", (inst, def) => {
  $ZodIntersection.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => intersectionProcessor(inst, ctx, json, params);
});
function intersection(left, right) {
  return new ZodIntersection({
    type: "intersection",
    left,
    right
  });
}
const ZodRecord = /* @__PURE__ */ $constructor("ZodRecord", (inst, def) => {
  $ZodRecord.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => recordProcessor(inst, ctx, json, params);
  inst.keyType = def.keyType;
  inst.valueType = def.valueType;
});
function record(keyType, valueType, params) {
  return new ZodRecord({
    type: "record",
    keyType,
    valueType,
    ...normalizeParams(params)
  });
}
const ZodEnum = /* @__PURE__ */ $constructor("ZodEnum", (inst, def) => {
  $ZodEnum.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => enumProcessor(inst, ctx, json);
  inst.enum = def.entries;
  inst.options = Object.values(def.entries);
  const keys = new Set(Object.keys(def.entries));
  inst.extract = (values, params) => {
    const newEntries = {};
    for (const value of values) {
      if (keys.has(value)) {
        newEntries[value] = def.entries[value];
      } else
        throw new Error(`Key ${value} not found in enum`);
    }
    return new ZodEnum({
      ...def,
      checks: [],
      ...normalizeParams(params),
      entries: newEntries
    });
  };
  inst.exclude = (values, params) => {
    const newEntries = { ...def.entries };
    for (const value of values) {
      if (keys.has(value)) {
        delete newEntries[value];
      } else
        throw new Error(`Key ${value} not found in enum`);
    }
    return new ZodEnum({
      ...def,
      checks: [],
      ...normalizeParams(params),
      entries: newEntries
    });
  };
});
function _enum(values, params) {
  const entries = Array.isArray(values) ? Object.fromEntries(values.map((v) => [v, v])) : values;
  return new ZodEnum({
    type: "enum",
    entries,
    ...normalizeParams(params)
  });
}
const ZodTransform = /* @__PURE__ */ $constructor("ZodTransform", (inst, def) => {
  $ZodTransform.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => transformProcessor(inst, ctx);
  inst._zod.parse = (payload, _ctx) => {
    if (_ctx.direction === "backward") {
      throw new $ZodEncodeError(inst.constructor.name);
    }
    payload.addIssue = (issue$1) => {
      if (typeof issue$1 === "string") {
        payload.issues.push(issue(issue$1, payload.value, def));
      } else {
        const _issue = issue$1;
        if (_issue.fatal)
          _issue.continue = false;
        _issue.code ?? (_issue.code = "custom");
        _issue.input ?? (_issue.input = payload.value);
        _issue.inst ?? (_issue.inst = inst);
        payload.issues.push(issue(_issue));
      }
    };
    const output = def.transform(payload.value, payload);
    if (output instanceof Promise) {
      return output.then((output2) => {
        payload.value = output2;
        return payload;
      });
    }
    payload.value = output;
    return payload;
  };
});
function transform(fn) {
  return new ZodTransform({
    type: "transform",
    transform: fn
  });
}
const ZodOptional = /* @__PURE__ */ $constructor("ZodOptional", (inst, def) => {
  $ZodOptional.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => optionalProcessor(inst, ctx, json, params);
  inst.unwrap = () => inst._zod.def.innerType;
});
function optional(innerType) {
  return new ZodOptional({
    type: "optional",
    innerType
  });
}
const ZodExactOptional = /* @__PURE__ */ $constructor("ZodExactOptional", (inst, def) => {
  $ZodExactOptional.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => optionalProcessor(inst, ctx, json, params);
  inst.unwrap = () => inst._zod.def.innerType;
});
function exactOptional(innerType) {
  return new ZodExactOptional({
    type: "optional",
    innerType
  });
}
const ZodNullable = /* @__PURE__ */ $constructor("ZodNullable", (inst, def) => {
  $ZodNullable.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => nullableProcessor(inst, ctx, json, params);
  inst.unwrap = () => inst._zod.def.innerType;
});
function nullable(innerType) {
  return new ZodNullable({
    type: "nullable",
    innerType
  });
}
const ZodDefault = /* @__PURE__ */ $constructor("ZodDefault", (inst, def) => {
  $ZodDefault.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => defaultProcessor(inst, ctx, json, params);
  inst.unwrap = () => inst._zod.def.innerType;
  inst.removeDefault = inst.unwrap;
});
function _default(innerType, defaultValue) {
  return new ZodDefault({
    type: "default",
    innerType,
    get defaultValue() {
      return typeof defaultValue === "function" ? defaultValue() : shallowClone(defaultValue);
    }
  });
}
const ZodPrefault = /* @__PURE__ */ $constructor("ZodPrefault", (inst, def) => {
  $ZodPrefault.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => prefaultProcessor(inst, ctx, json, params);
  inst.unwrap = () => inst._zod.def.innerType;
});
function prefault(innerType, defaultValue) {
  return new ZodPrefault({
    type: "prefault",
    innerType,
    get defaultValue() {
      return typeof defaultValue === "function" ? defaultValue() : shallowClone(defaultValue);
    }
  });
}
const ZodNonOptional = /* @__PURE__ */ $constructor("ZodNonOptional", (inst, def) => {
  $ZodNonOptional.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => nonoptionalProcessor(inst, ctx, json, params);
  inst.unwrap = () => inst._zod.def.innerType;
});
function nonoptional(innerType, params) {
  return new ZodNonOptional({
    type: "nonoptional",
    innerType,
    ...normalizeParams(params)
  });
}
const ZodCatch = /* @__PURE__ */ $constructor("ZodCatch", (inst, def) => {
  $ZodCatch.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => catchProcessor(inst, ctx, json, params);
  inst.unwrap = () => inst._zod.def.innerType;
  inst.removeCatch = inst.unwrap;
});
function _catch(innerType, catchValue) {
  return new ZodCatch({
    type: "catch",
    innerType,
    catchValue: typeof catchValue === "function" ? catchValue : () => catchValue
  });
}
const ZodPipe = /* @__PURE__ */ $constructor("ZodPipe", (inst, def) => {
  $ZodPipe.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => pipeProcessor(inst, ctx, json, params);
  inst.in = def.in;
  inst.out = def.out;
});
function pipe(in_, out) {
  return new ZodPipe({
    type: "pipe",
    in: in_,
    out
    // ...util.normalizeParams(params),
  });
}
const ZodReadonly = /* @__PURE__ */ $constructor("ZodReadonly", (inst, def) => {
  $ZodReadonly.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => readonlyProcessor(inst, ctx, json, params);
  inst.unwrap = () => inst._zod.def.innerType;
});
function readonly(innerType) {
  return new ZodReadonly({
    type: "readonly",
    innerType
  });
}
const ZodCustom = /* @__PURE__ */ $constructor("ZodCustom", (inst, def) => {
  $ZodCustom.init(inst, def);
  ZodType.init(inst, def);
  inst._zod.processJSONSchema = (ctx, json, params) => customProcessor(inst, ctx);
});
function refine(fn, _params = {}) {
  return /* @__PURE__ */ _refine(ZodCustom, fn, _params);
}
function superRefine(fn) {
  return /* @__PURE__ */ _superRefine(fn);
}
const OpenClawConfigSchema = object({
  gateway: object({
    port: number().default(18789),
    bind: _enum(["loopback", "all"]).default("loopback"),
    auth: object({
      mode: _enum(["token", "password", "none"]).default("none"),
      token: string().optional()
    }).default({ mode: "none" })
  }).default({ port: 18789, bind: "loopback", auth: { mode: "none" } }),
  agents: object({
    defaults: object({
      model: object({
        primary: string()
      })
    })
  }).optional(),
  models: object({
    mode: _enum(["merge", "replace"]).optional(),
    providers: record(string(), object({
      baseUrl: string().optional(),
      apiKey: string().optional(),
      api: string().optional(),
      models: array(object({
        id: string(),
        name: string().optional(),
        reasoning: boolean().optional(),
        input: array(string()).optional(),
        cost: object({
          input: number(),
          output: number()
        }).optional(),
        contextWindow: number().optional(),
        maxTokens: number().optional()
      })).optional()
    })).optional()
  }).optional()
});
const ENV_URLS = {
  test: {
    jprxGateway: "https://jprx.sparta.html5.qq.com/",
    wxLoginRedirectUri: "https://security-test.guanjia.qq.com/login",
    beaconUrl: "https://pcmgrmonitor.3g.qq.com/test/datareport",
    qclawBaseUrl: "https://jprx.sparta.html5.qq.com/aizone/v1",
    wechatWsUrl: "wss://jprx.sparta.html5.qq.com/agentwss"
  },
  production: {
    jprxGateway: "https://jprx.m.qq.com/",
    wxLoginRedirectUri: "https://security.guanjia.qq.com/login",
    beaconUrl: "https://pcmgrmonitor.3g.qq.com/datareport",
    qclawBaseUrl: "https://mmgrcalltoken.3g.qq.com/aizone/v1",
    wechatWsUrl: "wss://mmgrcalltoken.3g.qq.com/agentwss"
  }
};
function getEnvUrls(env) {
  return ENV_URLS[env];
}
function readConfigFileSync(filePath) {
  const raw = fs.readFileSync(filePath, "utf-8");
  return JSON5.parse(raw);
}
async function readConfigFile(filePath) {
  const raw = await fs$1.readFile(filePath, "utf-8");
  return JSON5.parse(raw);
}
function writeConfigFileSync(filePath, data) {
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf-8");
}
async function writeConfigFile(filePath, data) {
  await fs$1.writeFile(filePath, JSON.stringify(data, null, 2), "utf-8");
}
function resolveNestedArray(config2, keyPath, mode = "readonly") {
  let current = config2;
  for (let i = 0; i < keyPath.length - 1; i++) {
    const key = keyPath[i];
    if (current[key] == null || typeof current[key] !== "object") {
      if (mode === "readonly") return null;
      current[key] = {};
    }
    current = current[key];
  }
  const leafKey = keyPath[keyPath.length - 1];
  const arr = Array.isArray(current[leafKey]) ? current[leafKey] : [];
  return { parent: current, leafKey, arr };
}
function readConfigField(configPath, keyPath) {
  try {
    const config2 = readConfigFileSync(configPath);
    const keys = keyPath.split(".");
    let value = config2;
    for (const key of keys) {
      if (value == null || typeof value !== "object") {
        return void 0;
      }
      value = value[key];
    }
    return value;
  } catch {
    return void 0;
  }
}
function mergeTemplateWithProtection(userConfig, templateConfig, protectedPaths) {
  return mergeRecursive(userConfig, templateConfig, protectedPaths, "");
}
function mergeRecursive(target, source, protectedPaths, currentPath) {
  let changed = false;
  for (const key of Object.keys(source)) {
    const fullPath = currentPath ? `${currentPath}.${key}` : key;
    const sourceValue = source[key];
    const targetValue = target[key];
    if (isProtected(fullPath, protectedPaths)) {
      continue;
    }
    if (isAncestorOfProtected(fullPath, protectedPaths)) {
      if (isPlainObject(sourceValue) && isPlainObject(targetValue)) {
        const subChanged = mergeRecursive(
          targetValue,
          sourceValue,
          protectedPaths,
          fullPath
        );
        if (subChanged) changed = true;
        continue;
      }
      if (isPlainObject(sourceValue) && !isPlainObject(targetValue)) {
        const newObj = {};
        target[key] = newObj;
        const subChanged = mergeRecursive(
          newObj,
          sourceValue,
          protectedPaths,
          fullPath
        );
        changed = true;
        if (subChanged) changed = true;
        continue;
      }
    }
    if (isPlainObject(sourceValue) && isPlainObject(targetValue)) {
      const subChanged = mergeRecursive(
        targetValue,
        sourceValue,
        protectedPaths,
        fullPath
      );
      if (subChanged) changed = true;
      continue;
    }
    if (!deepEqual(targetValue, sourceValue)) {
      target[key] = structuredClone(sourceValue);
      changed = true;
    }
  }
  return changed;
}
function isProtected(path2, protectedPaths) {
  return protectedPaths.some((p) => p === path2);
}
function isAncestorOfProtected(path2, protectedPaths) {
  const prefix = `${path2}.`;
  return protectedPaths.some((p) => p.startsWith(prefix));
}
function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function deepEqual(a, b) {
  if (a === b) return true;
  if (a === void 0 || b === void 0) return false;
  if (a === null || b === null) return a === b;
  try {
    return JSON.stringify(a) === JSON.stringify(b);
  } catch {
    return false;
  }
}
function removePluginConfigKeys(config2, keysToRemove, logPrefix) {
  if (keysToRemove.length === 0) return false;
  let changed = false;
  const channels = config2.channels;
  const plugins = config2.plugins;
  const entries = plugins?.entries;
  const allow = plugins?.allow;
  for (const name of keysToRemove) {
    if (channels && name in channels) {
      delete channels[name];
      changed = true;
      mainLogger.info(`[ConfigPatcher] ${logPrefix}: removed channels.${name}`);
    }
    if (entries && name in entries) {
      delete entries[name];
      changed = true;
      mainLogger.info(`[ConfigPatcher] ${logPrefix}: removed plugins.entries.${name}`);
    }
    if (Array.isArray(allow)) {
      const idx = allow.indexOf(name);
      if (idx !== -1) {
        allow.splice(idx, 1);
        changed = true;
        mainLogger.info(`[ConfigPatcher] ${logPrefix}: removed plugins.allow entry: ${name}`);
      }
    }
  }
  return changed;
}
function stripExtraPluginConfigKeys(userConfig, templateConfig) {
  const templatePlugins = templateConfig.plugins;
  const templateEntries = templatePlugins?.entries;
  if (!templateEntries) return false;
  const userPlugins = userConfig.plugins;
  const userEntries = userPlugins?.entries;
  if (!userEntries) return false;
  let changed = false;
  for (const pluginName of Object.keys(templateEntries)) {
    const templateEntry = templateEntries[pluginName];
    const templatePluginConfig = templateEntry?.config;
    if (!templatePluginConfig) continue;
    const userEntry = userEntries[pluginName];
    const userPluginConfig = userEntry?.config;
    if (!userPluginConfig) continue;
    const allowedKeys = new Set(Object.keys(templatePluginConfig));
    for (const key of Object.keys(userPluginConfig)) {
      if (!allowedKeys.has(key)) {
        delete userPluginConfig[key];
        changed = true;
        mainLogger.info(
          `[ConfigPatcher] Stripped stale config key: plugins.entries.${pluginName}.config.${key}`
        );
      }
    }
  }
  return changed;
}
function removeBundledPathsFromArray(config2, keyPath, suffix) {
  const resolved = resolveNestedArray(config2, keyPath, "readonly");
  if (!resolved) return false;
  const { arr } = resolved;
  let changed = false;
  for (let i = arr.length - 1; i >= 0; i--) {
    const item = arr[i];
    if (typeof item === "string" && item.endsWith(suffix)) {
      arr.splice(i, 1);
      changed = true;
      mainLogger.info(`[ConfigPatcher] Cleanup: removed bundled path: ${item}`);
    }
  }
  return changed;
}
function cleanupDuplicateExtensions(stateDir) {
  const userExtDir = path.join(stateDir, "extensions");
  if (!fs.existsSync(userExtDir)) return;
  try {
    const namesToCleanup = new Set(FORCED_CLEANUP_EXTENSIONS);
    const bundledExtDir = getBundledExtensionsDir();
    if (fs.existsSync(bundledExtDir)) {
      const bundledNames = fs.readdirSync(bundledExtDir, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name);
      for (const name of bundledNames) {
        namesToCleanup.add(name);
      }
    }
    for (const name of namesToCleanup) {
      const duplicatePath = path.join(userExtDir, name);
      if (fs.existsSync(duplicatePath)) {
        fs.rmSync(duplicatePath, { recursive: true, force: true });
        mainLogger.info(`[ConfigPatcher] Removed duplicate extension from user dir: ${duplicatePath}`);
      }
    }
  } catch (err) {
    mainLogger.error(
      "[ConfigPatcher] Failed to cleanup duplicate extensions:",
      err instanceof Error ? err.message : "Unknown error"
    );
  }
}
function injectEnvUrls(configPath) {
  if (!fs.existsSync(configPath)) {
    return false;
  }
  try {
    const rawEnv = "production";
    const env = rawEnv === "production" ? "production" : "test";
    const envUrls = getEnvUrls(env);
    const content = readConfigFileSync(configPath);
    let changed = false;
    const models = content.models;
    const providers = models?.providers;
    const qclaw = providers?.qclaw;
    if (qclaw && qclaw.baseUrl !== envUrls.qclawBaseUrl) {
      qclaw.baseUrl = envUrls.qclawBaseUrl;
      changed = true;
    }
    const channels = content.channels;
    const wechatAccess = channels?.["wechat-access"];
    if (wechatAccess && wechatAccess.wsUrl !== envUrls.wechatWsUrl) {
      wechatAccess.wsUrl = envUrls.wechatWsUrl;
      changed = true;
    }
    if (changed) {
      writeConfigFileSync(configPath, content);
      mainLogger.info(`[ConfigPatcher] Injected env URLs (env=${env}, baseUrl=${envUrls.qclawBaseUrl})`);
    }
    return changed;
  } catch (err) {
    mainLogger.error(
      "[ConfigPatcher] Failed to inject env URLs:",
      err instanceof Error ? err.message : "Unknown error"
    );
    return false;
  }
}
function ensureAllowedOriginsForPath(configPath) {
  try {
    if (!fs.existsSync(configPath)) return;
    const config2 = readConfigFileSync(configPath);
    const gateway = config2.gateway ?? {};
    config2.gateway = gateway;
    const controlUi = gateway.controlUi ?? {};
    gateway.controlUi = controlUi;
    const origins = Array.isArray(controlUi.allowedOrigins) ? controlUi.allowedOrigins : [];
    const requiredOrigins = ELECTRON_REQUIRED_ORIGINS;
    let changed = false;
    for (const origin of requiredOrigins) {
      if (!origins.includes(origin)) {
        origins.push(origin);
        changed = true;
      }
    }
    if (changed) {
      controlUi.allowedOrigins = origins;
      writeConfigFileSync(configPath, config2);
    }
  } catch (err) {
    mainLogger.error("Failed to patch allowedOrigins:", err);
  }
}
function patchExternalConfig(externalStateDir) {
  const configPath = path.join(externalStateDir, OPENCLAW_CONFIG_FILE_NAME);
  cleanupDuplicateExtensions(externalStateDir);
  cleanupForcedExtensionConfigs(configPath);
  patchConfigFile(configPath);
  injectEnvUrls(configPath);
  ensureAllowedOriginsForPath(configPath);
  ensureBundledPaths(configPath);
}
function cleanupForcedExtensionConfigs(configPath) {
  if (FORCED_CLEANUP_EXTENSIONS.length === 0) return;
  if (!fs.existsSync(configPath)) return;
  try {
    const config2 = readConfigFileSync(configPath);
    const changed = removePluginConfigKeys(config2, FORCED_CLEANUP_EXTENSIONS, "Forced cleanup");
    if (changed) {
      writeConfigFileSync(configPath, config2);
      mainLogger.info("[ConfigPatcher] Cleaned up forced-removal plugin configs");
    }
  } catch (err) {
    mainLogger.error(
      "[ConfigPatcher] Failed to cleanup forced extension configs:",
      err instanceof Error ? err.message : "Unknown error"
    );
  }
}
function patchConfigFile(configPath) {
  if (!fs.existsSync(configPath)) {
    mainLogger.warn("[ConfigPatcher] External config not found, skipping patch");
    return;
  }
  try {
    const externalConfig = readConfigFileSync(configPath);
    const templatePath = getDefaultConfigSourcePath();
    if (!fs.existsSync(templatePath)) return;
    const templateConfig = readConfigFileSync(templatePath);
    let changed = mergeTemplateWithProtection(externalConfig, templateConfig, PROTECTED_CONFIG_PATHS);
    changed = stripExtraPluginConfigKeys(externalConfig, templateConfig) || changed;
    if (changed) {
      writeConfigFileSync(configPath, externalConfig);
      mainLogger.info("[ConfigPatcher] External config patched successfully");
    } else {
      mainLogger.info("[ConfigPatcher] External config already up-to-date");
    }
  } catch (err) {
    mainLogger.error(
      "[ConfigPatcher] Failed to patch config:",
      err instanceof Error ? err.message : "Unknown error"
    );
  }
}
function ensureBundledPaths(configPath) {
  if (!fs.existsSync(configPath)) return;
  try {
    const config2 = readConfigFileSync(configPath);
    let changed = false;
    const bundledExtDir = getBundledExtensionsDir();
    if (fs.existsSync(bundledExtDir)) {
      changed = ensureArrayValue(config2, ["plugins", "load", "paths"], bundledExtDir) || changed;
    }
    const bundledSkillsDir = getBundledSkillsDir();
    if (fs.existsSync(bundledSkillsDir)) {
      changed = ensureArrayValue(config2, ["skills", "load", "extraDirs"], bundledSkillsDir) || changed;
    }
    if (changed) {
      writeConfigFileSync(configPath, config2);
      mainLogger.info("[ConfigPatcher] Injected bundled resource paths into external config");
    }
  } catch (err) {
    mainLogger.error(
      "[ConfigPatcher] Failed to inject bundled paths:",
      err instanceof Error ? err.message : "Unknown error"
    );
  }
}
function ensureArrayValue(config2, keyPath, value) {
  const resolved = resolveNestedArray(config2, keyPath, "ensure");
  const { parent, leafKey, arr } = resolved;
  if (arr.includes(value)) return false;
  const suffix = BUNDLED_PATH_SUFFIXES.find((s) => value.endsWith(s));
  if (suffix) {
    const existingIdx = arr.findIndex(
      (item) => typeof item === "string" && item.endsWith(suffix)
    );
    if (existingIdx !== -1) {
      arr[existingIdx] = value;
      parent[leafKey] = arr;
      return true;
    }
  }
  arr.push(value);
  parent[leafKey] = arr;
  return true;
}
function cleanupInjectedConfig(configPath) {
  if (!fs.existsSync(configPath)) return;
  const templatePath = getDefaultConfigSourcePath();
  if (!fs.existsSync(templatePath)) return;
  try {
    const config2 = readConfigFileSync(configPath);
    const templateConfig = readConfigFileSync(templatePath);
    let changed = false;
    const templateChannels = templateConfig.channels;
    const templatePlugins = templateConfig.plugins;
    const templateEntries = templatePlugins?.entries;
    const keysFromTemplate = /* @__PURE__ */ new Set();
    if (templateChannels) {
      for (const k of Object.keys(templateChannels)) keysFromTemplate.add(k);
    }
    if (templateEntries) {
      for (const k of Object.keys(templateEntries)) keysFromTemplate.add(k);
    }
    changed = removePluginConfigKeys(config2, [...keysFromTemplate], "Cleanup") || changed;
    changed = removeBundledPathsFromArray(config2, ["plugins", "load", "paths"], BUNDLED_PATH_SUFFIXES[0]) || changed;
    changed = removeBundledPathsFromArray(config2, ["skills", "load", "extraDirs"], BUNDLED_PATH_SUFFIXES[1]) || changed;
    const controlUi = config2.gateway?.controlUi;
    if (controlUi && Array.isArray(controlUi.allowedOrigins)) {
      const origins = controlUi.allowedOrigins;
      for (const origin of ELECTRON_REQUIRED_ORIGINS) {
        const idx = origins.indexOf(origin);
        if (idx !== -1) {
          origins.splice(idx, 1);
          changed = true;
          mainLogger.info(`[ConfigPatcher] Cleanup: removed Electron origin: ${origin}`);
        }
      }
    }
    if (changed) {
      writeConfigFileSync(configPath, config2);
      mainLogger.info("[ConfigPatcher] Cleaned up injected config from external openclaw.json");
    } else {
      mainLogger.info("[ConfigPatcher] No injected config to clean up in external openclaw.json");
    }
  } catch (err) {
    mainLogger.error(
      "[ConfigPatcher] Failed to cleanup injected config:",
      err instanceof Error ? err.message : "Unknown error"
    );
  }
}
function writeQClawMeta(stateDir, configPath, pid, port) {
  const meta = {
    cli: {
      nodeBinary: getExecNodePath(),
      openclawMjs: getOpenClawEntryPath(),
      pid
    },
    stateDir,
    configPath,
    port,
    platform: process.platform
  };
  const metaDir = path.join(os.homedir(), OPENCLAW_STATE_DIR_NAME);
  fs.mkdirSync(metaDir, { recursive: true });
  const filePath = path.join(metaDir, QCLAW_META_FILE_NAME);
  fs.writeFileSync(filePath, JSON.stringify(meta, null, 2), "utf-8");
  mainLogger.info(`QClaw meta written to ${filePath} (PID: ${String(pid)})`);
}
const SUPERVISOR_BASE_DELAY = 1e3;
const SUPERVISOR_MAX_DELAY = 16e3;
const SUPERVISOR_BACKOFF_MULTIPLIER = 2;
const SUPERVISOR_JITTER_FACTOR = 0.3;
const SUPERVISOR_MAX_RETRIES = 5;
const SUPERVISOR_RETRY_WINDOW = 3e5;
const SUPERVISOR_STABLE_THRESHOLD = 6e4;
const SUPERVISOR_HEALTH_CHECK_INTERVAL = 3e4;
const SUPERVISOR_HEALTH_FAIL_THRESHOLD = 3;
const HEALTH_CHECK_ENDPOINT = "/v1/health";
const HEALTH_CHECK_TIMEOUT = 5e3;
const HEALTH_CHECK_DEFAULT_RETRIES = 3;
const HEALTH_CHECK_DEFAULT_RETRY_DELAY_MS = 1e3;
const HEALTH_WAIT_DEFAULT_RETRIES = 30;
const HEALTH_WAIT_DEFAULT_RETRY_DELAY_MS = 500;
const BACKUP_KEEP_COUNT = 5;
const BACKUP_DIR_NAME = "backups";
const GATEWAY_DEFAULT_BIND = "loopback";
const DEFAULT_MODEL_PRIMARY = "claude-sonnet-4.5";
const PORT_RELEASE_MAX_WAIT_MS = 3e3;
const PORT_RELEASE_CHECK_INTERVAL_MS = 200;
const PROCESS_KILL_COMMAND_TIMEOUT_MS = 5e3;
async function checkHealth(port, timeout = HEALTH_CHECK_TIMEOUT) {
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeout);
    const response = await fetch(`http://${LOCALHOST_ADDRESS}:${port}${HEALTH_CHECK_ENDPOINT}`, {
      signal: controller.signal,
      method: "GET",
      headers: {
        "Accept": "application/json"
      }
    });
    clearTimeout(timeoutId);
    return response.ok;
  } catch {
    return false;
  }
}
async function checkHealthWithRetry(options = {}) {
  const {
    port = 0,
    timeout = HEALTH_CHECK_TIMEOUT,
    retries = HEALTH_CHECK_DEFAULT_RETRIES,
    retryDelay = HEALTH_CHECK_DEFAULT_RETRY_DELAY_MS
  } = options;
  for (let attempt = 1; attempt <= retries; attempt++) {
    const isHealthy = await checkHealth(port, timeout);
    if (isHealthy) {
      return true;
    }
    if (attempt < retries) {
      await new Promise((resolve) => setTimeout(resolve, retryDelay));
    }
  }
  return false;
}
async function waitForHealth(options = {}) {
  const {
    port = 0,
    timeout = HEALTH_CHECK_TIMEOUT,
    retries = HEALTH_WAIT_DEFAULT_RETRIES,
    retryDelay = HEALTH_WAIT_DEFAULT_RETRY_DELAY_MS,
    isProcessAlive
  } = options;
  for (let attempt = 1; attempt <= retries; attempt++) {
    if (isProcessAlive && !isProcessAlive()) {
      throw new Error("Process exited during health check wait");
    }
    const isHealthy = await checkHealth(port, timeout);
    if (isHealthy) {
      return;
    }
    if (attempt < retries) {
      await new Promise((resolve) => setTimeout(resolve, retryDelay));
    }
  }
  throw new Error(
    `Health check failed after ${retries} attempts. Gateway may not be running.`
  );
}
class OpenClawService extends EventEmitter {
  process = null;
  status = "stopped";
  startTime = 0;
  currentPort;
  startupTimeout = OPENCLAW_STARTUP_TIMEOUT;
  shutdownTimeout = OPENCLAW_SHUTDOWN_TIMEOUT;
  /** 标记当前停止是否为主动操作（stop/shutdown），用于区分意外退出 */
  intentionalStop = false;
  serviceConfig;
  constructor(config2) {
    super();
    this.serviceConfig = {
      stateDir: config2?.stateDir ?? OPENCLAW_STATE_DIR,
      configPath: config2?.configPath ?? OPENCLAW_CONFIG_PATH,
      gatewayPort: config2?.gatewayPort ?? OPENCLAW_DEFAULT_GATEWAY_PORT
    };
    this.currentPort = this.serviceConfig.gatewayPort;
  }
  async start(options = {}) {
    if (this.status === "starting" || this.status === "running") {
      throw new Error(`Service is already ${this.status}`);
    }
    this.intentionalStop = false;
    this.updateStatus("starting");
    this.startTime = Date.now();
    this.initializeEnvironment();
    const openclawPath = this.getOpenClawPath();
    const args = this.buildArgs(options);
    this.emit("log", this.createLogEntry("info", `Starting OpenClaw on port ${this.currentPort}`));
    try {
      await this.ensurePortAvailable(this.currentPort);
      const nodePath = this.getNodePath();
      const cleanEnv = this.createCleanEnv();
      this.emit("log", this.createLogEntry("info", `Using Node.js: ${nodePath} (${process.versions.node})`));
      this.process = spawn(nodePath, args, {
        cwd: openclawPath,
        env: cleanEnv,
        stdio: ["pipe", "pipe", "pipe"],
        detached: false
      });
      this.setupProcessHandlers();
      await this.waitForStartup();
      this.emit("log", this.createLogEntry("info", `Waiting for gateway to be ready on port ${this.currentPort}...`));
      await waitForHealth({
        port: this.currentPort,
        retries: OPENCLAW_HEALTH_WAIT_RETRIES,
        retryDelay: OPENCLAW_HEALTH_WAIT_INTERVAL,
        isProcessAlive: () => this.process !== null && !this.process.killed
      });
      this.updateStatus("running");
      this.emit("log", this.createLogEntry("info", `OpenClaw started (PID: ${this.process.pid})`));
      this.emit("status", this.getStatus());
      writeQClawMeta(
        this.serviceConfig.stateDir,
        this.serviceConfig.configPath,
        this.process.pid ?? null,
        this.currentPort
      );
    } catch (error) {
      this.updateStatus("stopped");
      this.process = null;
      const message = error instanceof Error ? error.message : "Unknown error";
      this.emit("log", this.createLogEntry("error", `Failed to start OpenClaw: ${message}`));
      this.emit("status", this.getStatus());
      throw error;
    }
  }
  async stop() {
    if (this.status === "stopped" || this.status === "stopping") {
      return;
    }
    this.intentionalStop = true;
    this.updateStatus("stopping");
    this.emit("status", this.getStatus());
    if (!this.process) {
      this.updateStatus("stopped");
      return;
    }
    const pid = this.process.pid;
    const proc = this.process;
    return new Promise((resolve) => {
      let resolved = false;
      let sigkillTimerId = null;
      let finalTimerId = null;
      const finish = (logMsg, logLevel = "info") => {
        if (resolved) return;
        resolved = true;
        if (sigkillTimerId) {
          clearTimeout(sigkillTimerId);
          sigkillTimerId = null;
        }
        if (finalTimerId) {
          clearTimeout(finalTimerId);
          finalTimerId = null;
        }
        proc.removeAllListeners();
        this.process = null;
        this.updateStatus("stopped");
        this.emit("log", this.createLogEntry(logLevel, logMsg));
        this.emit("status", this.getStatus());
        resolve();
      };
      proc.once("exit", () => {
        finish(`OpenClaw stopped (PID: ${pid})`);
      });
      proc.once("error", (err) => {
        finish(`Process error during stop: ${err.message}`, "error");
      });
      if (process.platform === "win32") {
        proc.kill();
      } else if (pid) {
        try {
          process.kill(-pid, "SIGTERM");
        } catch {
          try {
            proc.kill("SIGTERM");
          } catch {
          }
        }
      } else {
        try {
          proc.kill("SIGTERM");
        } catch {
        }
      }
      sigkillTimerId = setTimeout(() => {
        sigkillTimerId = null;
        if (resolved) return;
        this.emit("log", this.createLogEntry("warn", "Shutdown timeout, forcing termination with SIGKILL..."));
        if (pid) {
          try {
            process.kill(-pid, "SIGKILL");
          } catch {
            try {
              proc.kill("SIGKILL");
            } catch {
            }
          }
        } else {
          try {
            proc.kill("SIGKILL");
          } catch {
          }
        }
      }, this.shutdownTimeout);
      finalTimerId = setTimeout(() => {
        finalTimerId = null;
        finish(`OpenClaw stop forced (PID: ${pid}, no exit event received after SIGKILL)`, "warn");
      }, this.shutdownTimeout * 2);
    });
  }
  async restart() {
    this.emit("log", this.createLogEntry("info", "Restarting OpenClaw..."));
    await this.stop();
    await new Promise((resolve) => setTimeout(resolve, RESTART_DELAY_MS));
    await this.start();
  }
  getStatus() {
    return {
      status: this.status,
      pid: this.process?.pid ?? null,
      uptime: this.startTime && this.status === "running" ? Date.now() - this.startTime : 0,
      port: this.currentPort
    };
  }
  updateStatus(status) {
    this.status = status;
  }
  getNodePath() {
    return getExecNodePath();
  }
  /**
   * 创建干净的环境变量，移除 Electron 特有的变量以确保子进程与 Electron 隔离
   */
  createCleanEnv() {
    const env = { ...process.env };
    const electronVars = Object.keys(env).filter(
      (key) => key.startsWith("ELECTRON_") || key === "ORIGINAL_XDG_CURRENT_DESKTOP" || key === "CHROME_DESKTOP"
    );
    for (const key of electronVars) {
      delete env[key];
    }
    env.ELECTRON_RUN_AS_NODE = ENV_VALUE_ENABLED;
    env.NODE_OPTIONS = NODE_OPTIONS_VALUE;
    env.OPENCLAW_NIX_MODE = ENV_VALUE_ENABLED;
    env.OPENCLAW_STATE_DIR = this.serviceConfig.stateDir;
    env.OPENCLAW_CONFIG_PATH = this.serviceConfig.configPath;
    env.OPENCLAW_NO_RESPAWN = ENV_VALUE_ENABLED;
    return env;
  }
  /**
   * 初始化 OpenClaw 运行环境
   * 在进程启动前统一完成所有前置准备工作：
   *   1. 确保配置文件存在并注入动态字段 (workspace、token)
   *   2. 注入预装资源路径 (bundled extensions/skills) 到配置中
   *   3. 从配置文件读取 gateway 端口
   */
  initializeEnvironment() {
    const configPath = this.serviceConfig.configPath;
    const stateDir = this.serviceConfig.stateDir;
    fs.mkdirSync(stateDir, { recursive: true });
    cleanupDuplicateExtensions(stateDir);
    cleanupForcedExtensionConfigs(configPath);
    this.ensureConfig(configPath, stateDir);
    this.patchConfigFromTemplate(configPath);
    this.injectEnvUrls(configPath);
    this.ensureExternalExtraDirs(configPath);
    const port = readConfigField(configPath, "gateway.port");
    this.currentPort = port ?? this.serviceConfig.gatewayPort;
  }
  /**
   * 确保配置文件存在
   * 如果目标配置文件不存在，则从内置模板复制并注入动态字段
   */
  ensureConfig(configPath, stateDir) {
    if (fs.existsSync(configPath)) {
      return;
    }
    const sourcePath = getDefaultConfigSourcePath();
    if (!fs.existsSync(sourcePath)) {
      this.emit(
        "log",
        this.createLogEntry("warn", `Default config template not found at ${sourcePath}`)
      );
      return;
    }
    fs.copyFileSync(sourcePath, configPath);
    try {
      const content = readConfigFileSync(configPath);
      if (content.agents?.defaults) {
        content.agents.defaults.workspace = path.join(stateDir, WORKSPACE_DIR_NAME);
      }
      if (content.gateway) {
        content.gateway.port = this.serviceConfig.gatewayPort;
      }
      if (content.gateway?.auth?.mode === "token") {
        content.gateway.auth.token = randomBytes(AUTH_TOKEN_BYTES).toString("hex");
      }
      writeConfigFileSync(configPath, content);
    } catch (err) {
      this.emit(
        "log",
        this.createLogEntry("warn", `Failed to initialize config: ${err instanceof Error ? err.message : "Unknown error"}`)
      );
    }
    this.emit(
      "log",
      this.createLogEntry("info", `Config file created at ${configPath}`)
    );
  }
  /**
   * 将内置模板的配置合并到已有配置中
   * 确保存量用户在版本升级后自动获取更新的配置
   *
   * 合并策略: 模板深度覆盖 + 用户字段保护
   * - PROTECTED_CONFIG_PATHS 中的字段保留用户值不覆盖
   * - 其余字段以模板为准覆盖到用户配置
   * - 用户自行添加的非模板字段保留不动
   * - 存量迁移: 将旧版 providers.default 的 apiKey 迁移到 providers.qclaw
   */
  patchConfigFromTemplate(configPath) {
    if (!fs.existsSync(configPath)) {
      return;
    }
    const templatePath = getDefaultConfigSourcePath();
    if (!fs.existsSync(templatePath)) {
      return;
    }
    try {
      const userConfig = readConfigFileSync(configPath);
      const templateConfig = readConfigFileSync(templatePath);
      const legacyMigrated = this.migrateLegacyDefaultProvider(userConfig);
      const templateMerged = mergeTemplateWithProtection(userConfig, templateConfig, PROTECTED_CONFIG_PATHS);
      const pluginConfigStripped = stripExtraPluginConfigKeys(userConfig, templateConfig);
      if (legacyMigrated || templateMerged || pluginConfigStripped) {
        writeConfigFileSync(configPath, userConfig);
        this.emit(
          "log",
          this.createLogEntry(
            "info",
            `Patched config from template (legacyMigrated=${String(legacyMigrated)}, templateMerged=${String(templateMerged)})`
          )
        );
      }
    } catch (err) {
      this.emit(
        "log",
        this.createLogEntry("warn", `Failed to patch config from template: ${err instanceof Error ? err.message : "Unknown error"}`)
      );
    }
  }
  /** 内置 provider key（模板中的默认模型提供商） */
  static BUILTIN_PROVIDER_KEY = "qclaw";
  /** 旧版内置 provider key（用于存量迁移） */
  static LEGACY_PROVIDER_KEY = "default";
  /**
   * 将旧版 providers.default 的配置迁移到 providers.qclaw
   *
   * 迁移内容:
   *   1. models.providers.default.apiKey → models.providers.qclaw.apiKey（仅当 qclaw 无 apiKey 时）
   *   2. agents.defaults.model.primary: "default/xxx" → "qclaw/xxx"
   *   3. 迁移完成后删除 models.providers.default
   *
   * @returns 是否产生了变更
   */
  migrateLegacyDefaultProvider(userConfig) {
    const legacyKey = OpenClawService.LEGACY_PROVIDER_KEY;
    const builtinKey = OpenClawService.BUILTIN_PROVIDER_KEY;
    const userModels = userConfig.models;
    const userProviders = userModels?.providers;
    const legacyProvider = userProviders?.[legacyKey];
    if (!legacyProvider || !userProviders) {
      return false;
    }
    let changed = false;
    const builtinProvider = userProviders[builtinKey];
    if (legacyProvider.apiKey && typeof legacyProvider.apiKey === "string") {
      if (!builtinProvider) {
        userProviders[builtinKey] = structuredClone(legacyProvider);
        changed = true;
      } else if (!builtinProvider.apiKey) {
        builtinProvider.apiKey = legacyProvider.apiKey;
        changed = true;
      }
    }
    delete userProviders[legacyKey];
    changed = true;
    const userAgents = userConfig.agents;
    const userDefaults = userAgents?.defaults;
    const userModel = userDefaults?.model;
    if (userModel?.primary !== void 0 && typeof userModel.primary === "string" && userModel.primary.startsWith(`${legacyKey}/`)) {
      userModel.primary = userModel.primary.replace(`${legacyKey}/`, `${builtinKey}/`);
      changed = true;
    }
    this.emit(
      "log",
      this.createLogEntry("info", `Migrated legacy provider '${legacyKey}' → '${builtinKey}'`)
    );
    return changed;
  }
  /**
   * 将 env-config 中的环境 URL 注入到用户配置
   *
   * 委托给 config-patcher 中的独立函数，并将结果通过事件发射通知调用者
   */
  injectEnvUrls(configPath) {
    const changed = injectEnvUrls(configPath);
    if (changed) {
      const rawEnv = "production";
      this.emit(
        "log",
        this.createLogEntry("info", `Injected env URLs (env=${rawEnv})`)
      );
    }
  }
  /**
   * 确保配置文件中包含预装资源路径和外部搜索路径
   *
   * 注入两类路径:
   *   1. Bundled 路径: app 内预装的 extensions/skills 目录（绝对路径，自动适配 dev/packaged）
   *   2. External 路径: 外部 CLI 安装的 skills/plugins 目录（~ 前缀路径）
   *
   * 每次启动时检查，确保存量用户升级后也能自动生效
   */
  ensureExternalExtraDirs(configPath) {
    if (!fs.existsSync(configPath)) {
      return;
    }
    try {
      const content = readConfigFileSync(configPath);
      const bundledSkillsDir = getBundledSkillsDir();
      const allSkillsDirs = [...OPENCLAW_CLAWHUB_SKILLS_EXTRA_DIRS, bundledSkillsDir];
      const bundledExtensionsDir = getBundledExtensionsDir();
      const allPluginDirs = [...OPENCLAW_EXTERNAL_PLUGIN_EXTRA_DIRS, bundledExtensionsDir];
      let changed = false;
      changed = this.ensureConfigArrayField(
        content,
        ["skills", "load", "extraDirs"],
        allSkillsDirs,
        "skills"
      ) || changed;
      changed = this.ensureConfigArrayField(
        content,
        ["plugins", "load", "paths"],
        allPluginDirs,
        "plugins"
      ) || changed;
      if (changed) {
        writeConfigFileSync(configPath, content);
      }
    } catch (err) {
      this.emit(
        "log",
        this.createLogEntry("warn", `Failed to ensure extra dirs: ${err instanceof Error ? err.message : "Unknown error"}`)
      );
    }
  }
  /**
   * 确保配置中指定路径的数组字段与实际文件系统保持同步
   *
   * 对 bundled 路径（以 openclaw/config/extensions 或 openclaw/config/skills 结尾）采用后缀匹配：
   * - 数组中已有相同后缀的条目且值正确 → 跳过
   * - 数组中已有相同后缀的条目但值不同 → 原地替换
   * - 数组中不存在同后缀条目 → 追加
   *
   * 对外部路径（~ 前缀）采用精确匹配：
   * - 添加：目录存在且尚未在配置中的路径
   * - 移除：之前添加但目录已不存在的路径（避免 OpenClaw 校验报错）
   *
   * @returns 是否有变更
   */
  ensureConfigArrayField(config2, keyPath, requiredValues, label) {
    const resolved = resolveNestedArray(config2, keyPath, "ensure");
    const { parent, leafKey, arr } = resolved;
    let changed = false;
    for (const v of requiredValues) {
      const resolvedPath = v.startsWith("~") ? path.join(os.homedir(), v.slice(1)) : v;
      const idx = arr.indexOf(v);
      if (idx !== -1 && !fs.existsSync(resolvedPath)) {
        arr.splice(idx, 1);
        changed = true;
        this.emit(
          "log",
          this.createLogEntry("info", `Removed non-existent ${label} dir from config: ${v}`)
        );
      }
    }
    for (const v of requiredValues) {
      if (arr.includes(v)) continue;
      const resolvedPath = v.startsWith("~") ? path.join(os.homedir(), v.slice(1)) : v;
      const suffix = BUNDLED_PATH_SUFFIXES.find((s) => v.endsWith(s));
      if (suffix) {
        const existingIdx = arr.findIndex(
          (item) => typeof item === "string" && item.endsWith(suffix)
        );
        if (existingIdx !== -1) {
          arr[existingIdx] = v;
          changed = true;
          this.emit(
            "log",
            this.createLogEntry("info", `Replaced outdated ${label} bundled dir in config: ${arr[existingIdx]} → ${v}`)
          );
          continue;
        }
      }
      if (fs.existsSync(resolvedPath)) {
        arr.push(v);
        changed = true;
        this.emit(
          "log",
          this.createLogEntry("info", `Added ${label} dir to config: ${v}`)
        );
      }
    }
    if (changed) {
      parent[leafKey] = arr;
    }
    return changed;
  }
  getOpenClawPath() {
    return getOpenClawPath();
  }
  buildArgs(options) {
    const entryPath = path.join(this.getOpenClawPath(), OPENCLAW_ENTRY_FILE);
    const args = [entryPath, OPENCLAW_COMMAND_GATEWAY];
    if (options.verbose) {
      args.push("--verbose");
    }
    return args;
  }
  setupProcessHandlers() {
    if (!this.process) return;
    this.process.stdout?.on("data", (data) => {
      const lines = data.toString("utf8").split("\n").filter((line) => line.trim());
      for (const line of lines) {
        this.emit("log", this.createLogEntry("info", line));
      }
    });
    this.process.stderr?.on("data", (data) => {
      const lines = data.toString("utf8").split("\n").filter((line) => line.trim());
      for (const line of lines) {
        this.emit("log", this.createLogEntry("error", line));
      }
    });
    this.process.on("exit", (code, signal) => {
      const message = `Process exited (code: ${code}, signal: ${signal})`;
      const wasRunning = this.status === "running" || this.status === "starting";
      if (wasRunning) {
        this.emit("log", this.createLogEntry("warn", message));
      }
      const isGracefulSelfRestart = code === 0 && signal === null;
      if (!this.intentionalStop && wasRunning && !isGracefulSelfRestart) {
        this.emit("unexpected-exit", { code, signal });
      }
      if (wasRunning || this.status === "stopping") {
        this.updateStatus("stopped");
        this.emit("status", this.getStatus());
      }
      this.process = null;
      this.intentionalStop = false;
    });
    this.process.on("error", (err) => {
      this.emit("log", this.createLogEntry("error", `Process error: ${err.message}`));
      if (this.status === "starting" || this.status === "running") {
        this.updateStatus("stopped");
        this.emit("status", this.getStatus());
      }
    });
  }
  async waitForStartup() {
    return new Promise((resolve, reject) => {
      if (!this.process) {
        reject(new Error("Process not initialized"));
        return;
      }
      const timeoutId = setTimeout(() => {
        reject(new Error("Process startup timeout"));
      }, this.startupTimeout);
      const checkExit = () => {
        if (!this.process || this.process.killed) {
          clearTimeout(timeoutId);
          reject(new Error("Process exited during startup"));
        }
      };
      this.process.once("exit", () => {
        checkExit();
      });
      this.process.once("error", (err) => {
        clearTimeout(timeoutId);
        reject(err);
      });
      this.process.once("spawn", () => {
        clearTimeout(timeoutId);
        resolve();
      });
      if (this.process.pid) {
        clearTimeout(timeoutId);
        resolve();
      }
    });
  }
  /**
   * 检查端口是否可用，如果被占用则尝试清理残留进程
   * 防止旧进程逃逸后占用端口导致新进程启动失败
   */
  async ensurePortAvailable(port) {
    const inUse = await this.isPortInUse(port);
    if (!inUse) return;
    this.emit("log", this.createLogEntry("warn", `Port ${port} is already in use, attempting to kill orphan process...`));
    const killed = this.killProcessOnPort(port);
    if (!killed) {
      throw new Error(`Port ${port} is occupied by another process and could not be freed`);
    }
    const maxWait = PORT_RELEASE_MAX_WAIT_MS;
    const interval = PORT_RELEASE_CHECK_INTERVAL_MS;
    let waited = 0;
    while (waited < maxWait) {
      await new Promise((resolve) => setTimeout(resolve, interval));
      waited += interval;
      if (!await this.isPortInUse(port)) {
        this.emit("log", this.createLogEntry("info", `Port ${port} freed successfully`));
        return;
      }
    }
    throw new Error(`Port ${port} is still occupied after attempting cleanup`);
  }
  isPortInUse(port) {
    return new Promise((resolve) => {
      const server = net.createServer();
      server.once("error", (err) => {
        if (err.code === "EADDRINUSE") {
          resolve(true);
        } else {
          resolve(false);
        }
      });
      server.once("listening", () => {
        server.close(() => resolve(false));
      });
      server.listen(port, LOCALHOST_ADDRESS);
    });
  }
  /**
   * 查找并杀死占用指定端口的进程
   * 仅在 Unix 系统上有效（macOS/Linux）
   */
  killProcessOnPort(port) {
    try {
      if (process.platform === "win32") {
        const output = execSync(`netstat -ano | findstr :${port} | findstr LISTENING`, { encoding: "utf8", timeout: PROCESS_KILL_COMMAND_TIMEOUT_MS });
        const match = output.trim().split(/\s+/).pop();
        if (match) {
          const orphanPid = parseInt(match, 10);
          if (!isNaN(orphanPid) && orphanPid > 0) {
            this.emit("log", this.createLogEntry("warn", `Killing orphan process PID ${orphanPid} on port ${port}`));
            execSync(`taskkill /F /PID ${orphanPid}`, { timeout: PROCESS_KILL_COMMAND_TIMEOUT_MS });
            return true;
          }
        }
      } else {
        const output = execSync(`lsof -ti :${port}`, { encoding: "utf8", timeout: PROCESS_KILL_COMMAND_TIMEOUT_MS });
        const pids = output.trim().split("\n").map((s) => parseInt(s, 10)).filter((p) => !isNaN(p) && p > 0);
        if (pids.length > 0) {
          for (const orphanPid of pids) {
            this.emit("log", this.createLogEntry("warn", `Killing orphan process PID ${orphanPid} on port ${port}`));
            try {
              process.kill(orphanPid, "SIGKILL");
            } catch {
            }
          }
          return true;
        }
      }
    } catch {
    }
    return false;
  }
  createLogEntry(level, message) {
    return {
      level,
      message,
      timestamp: Date.now()
    };
  }
}
class ProcessSupervisor extends EventEmitter {
  // 配置参数
  baseDelay;
  maxDelay;
  backoffMultiplier;
  jitterFactor;
  maxRetries;
  retryWindow;
  stableThreshold;
  healthCheckInterval;
  healthFailThreshold;
  // 运行状态
  state = "disabled";
  crashHistory = [];
  retryTimerId = null;
  stableTimerId = null;
  healthTimerId = null;
  consecutiveHealthFailures = 0;
  currentPort = 0;
  isRestarting = false;
  healthCheckPaused = false;
  // 外部注入的重启函数
  restartFn = null;
  constructor(options = {}) {
    super();
    this.baseDelay = options.baseDelay ?? SUPERVISOR_BASE_DELAY;
    this.maxDelay = options.maxDelay ?? SUPERVISOR_MAX_DELAY;
    this.backoffMultiplier = options.backoffMultiplier ?? SUPERVISOR_BACKOFF_MULTIPLIER;
    this.jitterFactor = options.jitterFactor ?? SUPERVISOR_JITTER_FACTOR;
    this.maxRetries = options.maxRetries ?? SUPERVISOR_MAX_RETRIES;
    this.retryWindow = options.retryWindow ?? SUPERVISOR_RETRY_WINDOW;
    this.stableThreshold = options.stableThreshold ?? SUPERVISOR_STABLE_THRESHOLD;
    this.healthCheckInterval = options.healthCheckInterval ?? SUPERVISOR_HEALTH_CHECK_INTERVAL;
    this.healthFailThreshold = options.healthFailThreshold ?? SUPERVISOR_HEALTH_FAIL_THRESHOLD;
  }
  // ==================== Public API ====================
  /**
   * 启用 supervisor，注入重启回调和当前端口
   */
  enable(restartFn, port) {
    this.restartFn = restartFn;
    this.currentPort = port;
    this.state = "active";
    mainLogger.info("[Supervisor] Enabled");
  }
  /**
   * 禁用 supervisor（应用退出时调用）
   * 取消所有定时器，防止退出后触发重启
   */
  disable() {
    this.state = "disabled";
    this.clearAllTimers();
    this.restartFn = null;
    mainLogger.info("[Supervisor] Disabled");
  }
  /**
   * 通知 supervisor 进程已成功启动
   * 启动稳定性定时器和运行时健康探测
   */
  notifyStarted(port) {
    if (this.state === "disabled") return;
    this.currentPort = port;
    this.consecutiveHealthFailures = 0;
    this.isRestarting = false;
    this.startStableTimer();
    this.startHealthCheck();
    if (this.state === "recovering") {
      this.state = "active";
      this.emit("restart-success");
    }
  }
  /**
   * 通知 supervisor 进程已停止（主动停止不触发重启）
   */
  notifyIntentionalStop() {
    this.clearAllTimers();
  }
  /**
   * 通知 supervisor 进程意外退出
   * 这是触发自动重启逻辑的核心入口
   */
  notifyUnexpectedExit(exitCode, signal) {
    if (this.state === "disabled") return;
    this.clearStableTimer();
    this.clearHealthCheck();
    const record2 = {
      timestamp: Date.now(),
      exitCode,
      signal
    };
    this.crashHistory.push(record2);
    mainLogger.warn(
      `[Supervisor] Unexpected exit detected (code: ${exitCode}, signal: ${signal})`
    );
    this.pruneOldCrashes();
    const recentCrashCount = this.crashHistory.length;
    if (recentCrashCount >= this.maxRetries) {
      this.openCircuit(
        `Service crashed ${recentCrashCount} times within ${this.retryWindow / 1e3}s window`
      );
      return;
    }
    this.scheduleRestart(recentCrashCount);
  }
  /**
   * 手动重置熔断器（用户主动启动时调用）
   */
  resetCircuit() {
    if (this.state === "circuit_open") {
      mainLogger.info("[Supervisor] Circuit reset by user action");
      this.crashHistory = [];
      this.state = "active";
      this.emit("circuit-reset");
    }
  }
  /**
   * 暂停健康检查评估。
   * 健康检查定时器继续运行，但检查结果被忽略。
   * 用于 Electron 侧感知到配置变更将触发 OpenClaw in-process restart 时，
   * 在重启窗口期内避免误判为假死。
   */
  pauseHealthCheck() {
    this.healthCheckPaused = true;
    this.consecutiveHealthFailures = 0;
    mainLogger.info("[Supervisor] Health check paused (config restart window)");
  }
  /**
   * 恢复健康检查评估。
   */
  resumeHealthCheck() {
    this.healthCheckPaused = false;
    this.consecutiveHealthFailures = 0;
    mainLogger.info("[Supervisor] Health check resumed");
  }
  /**
   * 更新 supervisor 跟踪的端口（配置变更时）
   */
  updatePort(port) {
    this.currentPort = port;
  }
  /**
   * 获取 supervisor 当前状态
   */
  getStatus() {
    return {
      state: this.state,
      restartCount: this.getRecentCrashCount(),
      nextRetryAt: this.retryTimerId ? this.nextRetryAt : null,
      circuitOpenReason: this.state === "circuit_open" ? this.circuitOpenReason : null,
      crashHistory: [...this.crashHistory],
      consecutiveHealthFailures: this.consecutiveHealthFailures
    };
  }
  // ==================== Private: Restart Logic ====================
  nextRetryAt = null;
  circuitOpenReason = null;
  /**
   * 计算退避延迟：delay = min(base * mult^attempt, max) * (1 ± jitter)
   */
  calculateDelay(attempt) {
    const rawDelay = Math.min(
      this.baseDelay * Math.pow(this.backoffMultiplier, attempt),
      this.maxDelay
    );
    const jitter = 1 + (Math.random() * 2 - 1) * this.jitterFactor;
    return Math.round(rawDelay * jitter);
  }
  /**
   * 安排一次延迟重启
   */
  scheduleRestart(attempt) {
    if (this.state === "disabled" || this.state === "circuit_open") return;
    this.state = "recovering";
    const delay = this.calculateDelay(attempt);
    this.nextRetryAt = Date.now() + delay;
    mainLogger.info(
      `[Supervisor] Scheduling restart attempt #${attempt + 1} in ${delay}ms`
    );
    this.emit("restart-scheduled", { delay, attempt: attempt + 1 });
    this.retryTimerId = setTimeout(() => {
      this.retryTimerId = null;
      this.nextRetryAt = null;
      this.executeRestart();
    }, delay);
  }
  /**
   * 执行重启
   */
  async executeRestart() {
    if (this.state === "disabled" || this.state === "circuit_open" || !this.restartFn) {
      return;
    }
    if (this.isRestarting) {
      mainLogger.warn("[Supervisor] Restart already in progress, skipping");
      return;
    }
    this.isRestarting = true;
    this.emit("restart-attempt");
    mainLogger.info("[Supervisor] Executing restart...");
    try {
      await this.restartFn();
    } catch (error) {
      this.isRestarting = false;
      const message = error instanceof Error ? error.message : "Unknown error";
      mainLogger.error(`[Supervisor] Restart failed: ${message}`);
      this.emit("restart-failed", { error: message });
      this.notifyUnexpectedExit(null, null);
    }
  }
  // ==================== Private: Circuit Breaker ====================
  /**
   * 触发熔断
   */
  openCircuit(reason) {
    this.state = "circuit_open";
    this.circuitOpenReason = reason;
    this.clearRetryTimer();
    mainLogger.error(`[Supervisor] Circuit OPEN: ${reason}`);
    this.emit("circuit-open", {
      reason,
      crashHistory: [...this.crashHistory]
    });
  }
  // ==================== Private: Health Check ====================
  /**
   * 启动运行时周期性健康探测
   */
  startHealthCheck() {
    this.clearHealthCheck();
    if (this.currentPort <= 0) return;
    this.healthTimerId = setInterval(async () => {
      if (this.state !== "active" || this.isRestarting || this.healthCheckPaused) return;
      const healthy = await checkHealth(this.currentPort, HEALTH_CHECK_TIMEOUT);
      if (healthy) {
        if (this.consecutiveHealthFailures > 0) {
          this.consecutiveHealthFailures = 0;
        }
        return;
      }
      this.consecutiveHealthFailures++;
      mainLogger.warn(
        `[Supervisor] Health check failed (${this.consecutiveHealthFailures}/${this.healthFailThreshold})`
      );
      this.emit("health-failure", {
        consecutiveFailures: this.consecutiveHealthFailures
      });
      if (this.consecutiveHealthFailures >= this.healthFailThreshold) {
        mainLogger.error(
          `[Supervisor] Process appears unresponsive after ${this.consecutiveHealthFailures} consecutive health check failures, triggering restart`
        );
        this.consecutiveHealthFailures = 0;
        this.clearHealthCheck();
        this.clearStableTimer();
        this.emit("health-restart");
        this.notifyUnexpectedExit(null, "HEALTH_CHECK_TIMEOUT");
      }
    }, this.healthCheckInterval);
  }
  // ==================== Private: Stability ====================
  /**
   * 启动稳定性定时器
   * 进程持续运行超过 stableThreshold 后，清空 crash 历史记录
   */
  startStableTimer() {
    this.clearStableTimer();
    this.stableTimerId = setTimeout(() => {
      this.stableTimerId = null;
      if (this.state === "active" && this.crashHistory.length > 0) {
        mainLogger.info(
          `[Supervisor] Process stable for ${this.stableThreshold / 1e3}s, resetting crash history`
        );
        this.crashHistory = [];
        this.emit("stable");
      }
    }, this.stableThreshold);
  }
  // ==================== Private: Utilities ====================
  /**
   * 清理 retryWindow 之外的 crash 记录
   */
  pruneOldCrashes() {
    const cutoff = Date.now() - this.retryWindow;
    this.crashHistory = this.crashHistory.filter((c) => c.timestamp >= cutoff);
  }
  /**
   * 获取当前时间窗口内的 crash 次数
   */
  getRecentCrashCount() {
    const cutoff = Date.now() - this.retryWindow;
    return this.crashHistory.filter((c) => c.timestamp >= cutoff).length;
  }
  clearRetryTimer() {
    if (this.retryTimerId) {
      clearTimeout(this.retryTimerId);
      this.retryTimerId = null;
      this.nextRetryAt = null;
    }
  }
  clearStableTimer() {
    if (this.stableTimerId) {
      clearTimeout(this.stableTimerId);
      this.stableTimerId = null;
    }
  }
  clearHealthCheck() {
    if (this.healthTimerId) {
      clearInterval(this.healthTimerId);
      this.healthTimerId = null;
    }
    this.consecutiveHealthFailures = 0;
  }
  clearAllTimers() {
    this.clearRetryTimer();
    this.clearStableTimer();
    this.clearHealthCheck();
  }
}
class ExternalInstanceMonitor extends EventEmitter {
  port;
  intervalId = null;
  lastHealthy = false;
  constructor(port) {
    super();
    this.port = port;
  }
  start() {
    if (this.intervalId) return;
    mainLogger.info(`[ExternalMonitor] Starting health polling for port ${this.port}`);
    void this.poll();
    this.intervalId = setInterval(() => void this.poll(), EXTERNAL_MONITOR_POLL_INTERVAL_MS);
  }
  stop() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
      mainLogger.info("[ExternalMonitor] Stopped health polling");
    }
  }
  getStatus() {
    return {
      status: this.lastHealthy ? "running" : "stopped",
      pid: null,
      // External process, PID unknown
      uptime: 0,
      // Unknown
      port: this.port
    };
  }
  async poll() {
    const healthy = await checkHealth(this.port);
    if (healthy !== this.lastHealthy) {
      this.lastHealthy = healthy;
      const status = healthy ? "running" : "stopped";
      const logEntry = {
        level: "info",
        message: `[ExternalMonitor] External instance ${status} (port ${this.port})`,
        timestamp: Date.now()
      };
      this.emit("log", logEntry);
      this.emit("status", this.getStatus());
    }
  }
}
class StoreManager {
  data = {};
  filePath;
  constructor(filePath) {
    this.filePath = filePath ?? path.join(app.getPath("userData"), APP_STORE_FILE_NAME);
    this.load();
  }
  get(key) {
    return this.data[key];
  }
  set(key, value) {
    this.data[key] = value;
    this.save();
  }
  delete(key) {
    delete this.data[key];
    this.save();
  }
  has(key) {
    return key in this.data;
  }
  load() {
    try {
      if (fs.existsSync(this.filePath)) {
        const raw = fs.readFileSync(this.filePath, "utf-8");
        this.data = JSON.parse(raw);
      }
    } catch (err) {
      mainLogger.warn(
        "[StoreManager] Failed to load store, starting fresh:",
        err instanceof Error ? err.message : "Unknown error"
      );
      this.data = {};
    }
  }
  save() {
    try {
      const dir = path.dirname(this.filePath);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(this.filePath, JSON.stringify(this.data, null, 2), "utf-8");
    } catch (err) {
      mainLogger.error(
        "[StoreManager] Failed to save store:",
        err instanceof Error ? err.message : "Unknown error"
      );
    }
  }
}
let storeManagerInstance = null;
function getStoreManager() {
  if (!storeManagerInstance) {
    storeManagerInstance = new StoreManager();
  }
  return storeManagerInstance;
}
async function detectExternalInstance() {
  const configDir = path.join(os.homedir(), OPENCLAW_EXTERNAL_STATE_DIR_NAME);
  const configPath = path.join(configDir, OPENCLAW_CONFIG_FILE_NAME);
  if (!fs.existsSync(configPath)) {
    return { detected: false };
  }
  const port = readConfigField(configPath, "gateway.port") ?? OPENCLAW_EXTERNAL_GATEWAY_PORT_DEFAULT;
  const healthy = await checkHealth(port, INSTANCE_DETECTION_TIMEOUT_MS);
  return {
    detected: healthy,
    port,
    healthy,
    configDir
  };
}
let currentBootState = null;
async function runBootSequence(mainWindow2) {
  const store = getStoreManager();
  const externalInfo = await detectExternalInstance();
  const persisted = store.get(STORE_KEY_INSTANCE_MODE);
  currentBootState = computeBootState(externalInfo, persisted);
  mainLogger.info("[Boot] Boot state:", JSON.stringify(currentBootState));
  mainWindow2.webContents.send("instance:bootState", currentBootState);
  if (currentBootState.mode && !currentBootState.needsUserChoice) {
    await initializeWithMode(currentBootState.mode, externalInfo);
  }
}
async function retryBootSequence() {
  const store = getStoreManager();
  const persisted = store.get(STORE_KEY_INSTANCE_MODE);
  let externalInfo = { detected: false };
  for (let attempt = 1; attempt <= INSTANCE_RETRY_DETECTION_MAX_ATTEMPTS; attempt++) {
    externalInfo = await detectExternalInstance();
    mainLogger.info(
      `[Boot] Retry detection attempt ${attempt}/${INSTANCE_RETRY_DETECTION_MAX_ATTEMPTS}: detected=${String(externalInfo.detected)}`
    );
    if (externalInfo.detected) {
      break;
    }
    if (attempt < INSTANCE_RETRY_DETECTION_MAX_ATTEMPTS) {
      await new Promise((resolve) => setTimeout(resolve, INSTANCE_RETRY_DETECTION_INTERVAL_MS));
    }
  }
  currentBootState = computeBootState(externalInfo, persisted);
  mainLogger.info("[Boot] Retry boot state:", JSON.stringify(currentBootState));
  if (currentBootState.mode && !currentBootState.needsUserChoice) {
    await initializeWithMode(currentBootState.mode, externalInfo);
  }
  return currentBootState;
}
async function initializeWithMode(mode, externalInfo, _userInitiated = false) {
  mainLogger.info(`[Boot] Initializing with mode: ${mode}`);
  const store = getStoreManager();
  const bootState = currentBootState;
  if (mode === "isolated" && bootState?.previousMode === "shared") {
    migrateConfigFromExternal();
  }
  store.set(STORE_KEY_INSTANCE_MODE, {
    mode,
    externalDetectedAtSelection: externalInfo?.detected ?? false,
    selectedAt: Date.now()
  });
  const runtimeConfig = resolveRuntimeConfig(mode, externalInfo);
  const processManager = getProcessManager();
  prepareForStart(mode, runtimeConfig);
  processManager.initialize(mode, runtimeConfig);
  if (mode === "shared") {
    writeQClawMeta(
      runtimeConfig.stateDir,
      runtimeConfig.configPath,
      null,
      runtimeConfig.gatewayPort
    );
  }
  if (mode === "isolated") {
    try {
      await processManager.start();
    } catch (error) {
      mainLogger.error(
        "[Boot] Service start failed:",
        error instanceof Error ? error.message : String(error)
      );
    }
  }
}
function computeBootState(external, persisted) {
  const normalizedMode = normalizeMode(persisted?.mode);
  if (!external.detected) {
    if (normalizedMode === "shared") {
      return { mode: null, externalInstance: external, needsUserChoice: true, previousMode: "shared" };
    }
    return { mode: "isolated", externalInstance: external, needsUserChoice: false, previousMode: normalizedMode ?? null };
  }
  if (!persisted) {
    return { mode: null, externalInstance: external, needsUserChoice: true, previousMode: null };
  }
  if (persisted.externalDetectedAtSelection) {
    return { mode: normalizedMode, externalInstance: external, needsUserChoice: false, previousMode: normalizedMode };
  }
  return { mode: null, externalInstance: external, needsUserChoice: true, previousMode: normalizedMode };
}
function normalizeMode(mode) {
  if (!mode) return void 0;
  if (mode === "standalone") return "isolated";
  return mode;
}
function resolveRuntimeConfig(mode, externalInfo) {
  switch (mode) {
    case "shared": {
      const externalStateDir = externalInfo?.configDir ?? OPENCLAW_STATE_DIR;
      return {
        mode,
        stateDir: externalStateDir,
        configPath: externalInfo?.configDir ? `${externalInfo.configDir}/${OPENCLAW_CONFIG_FILE_NAME}` : OPENCLAW_CONFIG_PATH,
        backupDir: externalInfo?.configDir ? `${externalInfo.configDir}/${BACKUP_DIR_NAME}` : OPENCLAW_BACKUP_DIR,
        gatewayPort: externalInfo?.port ?? OPENCLAW_DEFAULT_GATEWAY_PORT
      };
    }
    case "isolated":
      return {
        mode,
        stateDir: OPENCLAW_STATE_DIR,
        configPath: OPENCLAW_CONFIG_PATH,
        backupDir: OPENCLAW_BACKUP_DIR,
        gatewayPort: OPENCLAW_DEFAULT_GATEWAY_PORT
      };
  }
}
function migrateConfigFromExternal() {
  const externalConfigPath = path.join(
    os.homedir(),
    OPENCLAW_EXTERNAL_STATE_DIR_NAME,
    OPENCLAW_CONFIG_FILE_NAME
  );
  if (!fs.existsSync(externalConfigPath)) {
    mainLogger.info("[Boot] No external config found, skipping migration");
    return;
  }
  try {
    const externalConfig = readConfigFileSync(externalConfigPath);
    let isolatedConfig = {};
    let createdFromTemplate = false;
    if (fs.existsSync(OPENCLAW_CONFIG_PATH)) {
      isolatedConfig = readConfigFileSync(OPENCLAW_CONFIG_PATH);
    } else {
      const templatePath = getDefaultConfigSourcePath();
      if (fs.existsSync(templatePath)) {
        isolatedConfig = readConfigFileSync(templatePath);
        const agents = isolatedConfig.agents;
        if (agents?.defaults) {
          const defaults = agents.defaults;
          defaults.workspace = path.join(OPENCLAW_STATE_DIR, WORKSPACE_DIR_NAME);
        }
        const gateway = isolatedConfig.gateway;
        if (gateway) {
          gateway.port = OPENCLAW_DEFAULT_GATEWAY_PORT;
        }
        const auth = gateway?.auth;
        if (auth?.mode === "token") {
          auth.token = randomBytes(AUTH_TOKEN_BYTES).toString("hex");
        }
        mainLogger.info("[Boot] Initialized isolated config from template for migration");
        createdFromTemplate = true;
      }
    }
    let changed = false;
    const externalChannels = externalConfig.channels;
    const externalTA = externalChannels?.["wechat-access"];
    const externalToken = externalTA?.token;
    if (externalToken) {
      const isolatedChannels = isolatedConfig.channels ?? {};
      const isolatedTA = isolatedChannels["wechat-access"] ?? {};
      const currentToken = isolatedTA.token;
      if (!currentToken) {
        isolatedTA.token = externalToken;
        isolatedChannels["wechat-access"] = isolatedTA;
        isolatedConfig.channels = isolatedChannels;
        changed = true;
        mainLogger.info("[Boot] Migrated wechat-access token from external config");
      }
    }
    if (changed || createdFromTemplate) {
      fs.mkdirSync(path.dirname(OPENCLAW_CONFIG_PATH), { recursive: true });
      writeConfigFileSync(OPENCLAW_CONFIG_PATH, isolatedConfig);
      mainLogger.info(`[Boot] Config migration completed (fromTemplate=${String(createdFromTemplate)}, tokenMigrated=${String(changed)})`);
    } else {
      mainLogger.info("[Boot] No config fields need migration");
    }
  } catch (err) {
    mainLogger.error(
      "[Boot] Config migration failed:",
      err instanceof Error ? err.message : "Unknown error"
    );
  }
}
function prepareForStart(mode, runtimeConfig) {
  if (mode === "shared") {
    patchExternalConfig(runtimeConfig.stateDir);
  } else {
    const externalConfigPath = path.join(
      os.homedir(),
      OPENCLAW_EXTERNAL_STATE_DIR_NAME,
      OPENCLAW_CONFIG_FILE_NAME
    );
    cleanupInjectedConfig(externalConfigPath);
    ensureAllowedOriginsForPath(runtimeConfig.configPath);
  }
}
function getBootState() {
  return currentBootState;
}
const RUM_AEGIS_ID = "zYmXYIzad2el6jj8Qa";
const RUM_COLLECT_URL = "https://aegis.qq.com/collect/events";
const RUM_FROM_MAIN = "qclaw://main";
const RUM_FROM_RENDERER = "qclaw://renderer";
const RUM_EXT1_MAX_LEN = 256;
const RUM_EXT2_MAX_LEN = 1024;
const RUM_EVENT_MAIN_UNCAUGHT_EXCEPTION = "main_uncaught_exception";
const RUM_EVENT_MAIN_UNHANDLED_REJECTION = "main_unhandled_rejection";
const RUM_EVENT_RENDERER_PROCESS_GONE = "renderer_process_gone";
const RUM_EVENT_CHILD_PROCESS_GONE = "child_process_gone";
const RUM_EVENT_OPENCLAW_UNEXPECTED_EXIT = "openclaw_unexpected_exit";
const RUM_EVENT_OPENCLAW_CIRCUIT_OPEN = "openclaw_circuit_open";
const RUM_EVENT_OPENCLAW_HEALTH_RESTART = "openclaw_health_restart";
const RUM_EVENT_APP_LAUNCH = "app_launch";
const RUM_EVENT_APP_QUIT = "app_quit";
const RUM_EVENT_SERVICE_START = "service_start";
const RUM_EVENT_SERVICE_STOP = "service_stop";
const { machineId: machineId$2 } = pkg;
function truncate(str, maxLen) {
  if (str.length <= maxLen) return str;
  return str.slice(0, maxLen - 3) + "...";
}
let cachedMachineId = "";
machineId$2().then((id) => {
  cachedMachineId = id;
}).catch(() => {
});
function buildExt3() {
  const version2 = app.getVersion();
  const platform2 = process.platform;
  const arch = process.arch;
  const env = app.isPackaged ? "prod" : "dev";
  const uptime = Math.floor(process.uptime());
  return `v:${version2}|p:${platform2}|a:${arch}|env:${env}|up:${uptime}s`;
}
function queryStringify(obj) {
  return Object.entries(obj).map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`).join("&");
}
function rumReport(event, from = RUM_FROM_MAIN) {
  try {
    const payload = { name: event.name };
    if (event.ext1) payload["ext1"] = truncate(event.ext1, RUM_EXT1_MAX_LEN);
    if (event.ext2) payload["ext2"] = truncate(event.ext2, RUM_EXT2_MAX_LEN);
    if (event.ext3) payload["ext3"] = event.ext3;
    else payload["ext3"] = buildExt3();
    const queryObj = {
      id: RUM_AEGIS_ID,
      payload: JSON.stringify([payload]),
      from
    };
    if (cachedMachineId) {
      queryObj["uin"] = cachedMachineId;
    }
    const url = `${RUM_COLLECT_URL}?${queryStringify(queryObj)}`;
    fetch(url).catch(() => {
    });
  } catch {
  }
}
function formatBytes(bytes) {
  const mb = bytes / (1024 * 1024);
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)}GB`;
  return `${Math.floor(mb)}MB`;
}
class ProcessManager extends EventEmitter {
  service = null;
  supervisor = null;
  externalMonitor = null;
  mode = null;
  runtimeConfig = null;
  isShuttingDown = false;
  constructor() {
    super();
    this.setupExitHandlers();
  }
  /**
   * 初始化 ProcessManager
   * 根据运行模式创建 service (isolated) 或 externalMonitor (shared)
   * 必须在 start() 之前调用
   */
  initialize(mode, config2) {
    if (this.mode !== null) {
      mainLogger.warn("[ProcessManager] Already initialized, skipping");
      return;
    }
    this.mode = mode;
    this.runtimeConfig = config2;
    mainLogger.info(`[ProcessManager] Initializing in '${mode}' mode, gateway port: ${config2.gatewayPort}`);
    mainLogger.info(`[ProcessManager] Runtime config: stateDir=${config2.stateDir}, configPath=${config2.configPath}`);
    if (mode === "shared") {
      this.externalMonitor = new ExternalInstanceMonitor(config2.gatewayPort);
      this.setupExternalMonitorListeners();
      this.externalMonitor.start();
    } else {
      const serviceConfig = {
        stateDir: config2.stateDir,
        configPath: config2.configPath,
        gatewayPort: config2.gatewayPort
      };
      this.service = new OpenClawService(serviceConfig);
      this.supervisor = new ProcessSupervisor();
      this.setupServiceListeners();
      this.setupSupervisorListeners();
    }
  }
  /**
   * 启动 OpenClaw 服务
   * 启动成功后自动启用 supervisor 监控
   */
  async start(options) {
    if (this.mode === "shared") {
      mainLogger.info("[ProcessManager] Shared mode — skipping process start (externally managed)");
      return;
    }
    if (!this.service) {
      throw new Error("ProcessManager not initialized. Call initialize() first.");
    }
    if (this.isShuttingDown) {
      throw new Error("Application is shutting down");
    }
    mainLogger.info(`[ProcessManager] Starting service in '${this.mode}' mode`);
    if (this.mode && this.runtimeConfig) {
      prepareForStart(this.mode, this.runtimeConfig);
    }
    this.supervisor?.resetCircuit();
    const startBegin = Date.now();
    await this.service.start(options);
    const startupDuration = Date.now() - startBegin;
    if (this.supervisor) {
      const status = this.service.getStatus();
      this.supervisor.enable(
        () => this.supervisedRestart(),
        status.port
      );
      this.supervisor.notifyStarted(status.port);
    }
    const startedStatus = this.service.getStatus();
    rumReport({
      name: RUM_EVENT_SERVICE_START,
      ext1: `mode:${this.mode}|port:${startedStatus.port}|startup:${startupDuration}ms`
    });
  }
  /**
   * 停止 OpenClaw 服务
   * 通知 supervisor 这是主动停止
   */
  async stop() {
    if (this.mode === "shared") {
      mainLogger.info("[ProcessManager] Shared mode — skipping process stop");
      return;
    }
    if (!this.service) return;
    mainLogger.info(`[ProcessManager] Stopping service (mode: '${this.mode}')`);
    this.supervisor?.notifyIntentionalStop();
    await this.service.stop();
    rumReport({
      name: RUM_EVENT_SERVICE_STOP,
      ext1: `mode:${this.mode}`
    });
  }
  /**
   * 重启 OpenClaw 服务
   */
  async restart() {
    if (this.mode === "shared") {
      mainLogger.info("[ProcessManager] Shared mode — skipping process restart");
      return;
    }
    if (!this.service) {
      throw new Error("ProcessManager not initialized. Call initialize() first.");
    }
    if (this.isShuttingDown) {
      throw new Error("Application is shutting down");
    }
    if (this.mode && this.runtimeConfig) {
      prepareForStart(this.mode, this.runtimeConfig);
    }
    this.supervisor?.notifyIntentionalStop();
    await this.service.restart();
    if (this.supervisor) {
      const status = this.service.getStatus();
      this.supervisor.enable(
        () => this.supervisedRestart(),
        status.port
      );
      this.supervisor.notifyStarted(status.port);
    }
  }
  /**
   * 获取服务状态（融合 supervisor 信息）
   */
  getStatus() {
    if (this.mode === "shared" && this.externalMonitor) {
      return this.externalMonitor.getStatus();
    }
    if (!this.service) {
      return {
        status: "stopped",
        pid: null,
        uptime: 0,
        port: this.runtimeConfig?.gatewayPort ?? OPENCLAW_DEFAULT_GATEWAY_PORT
      };
    }
    const serviceStatus = this.service.getStatus();
    const supervisorStatus = this.supervisor?.getStatus();
    return {
      ...serviceStatus,
      // 当 service 是 stopped 但 supervisor 在恢复中时，覆盖显示为 recovering
      status: this.getSynthesizedStatus(serviceStatus, supervisorStatus),
      restartCount: supervisorStatus?.restartCount,
      nextRetryAt: supervisorStatus?.nextRetryAt ?? void 0,
      circuitOpenReason: supervisorStatus?.circuitOpenReason ?? void 0
    };
  }
  /** 获取当前运行模式 */
  getMode() {
    return this.mode;
  }
  /** 获取运行时配置 */
  getRuntimeConfig() {
    return this.runtimeConfig;
  }
  /**
   * 订阅日志事件
   * 可在 initialize() 之前调用（PM 继承 EventEmitter，事件注册在 PM 自身）
   */
  onLog(listener) {
    this.on("log", listener);
  }
  /**
   * 订阅状态变更事件
   * 可在 initialize() 之前调用
   */
  onStatusChange(listener) {
    this.on("status", listener);
  }
  /**
   * 取消订阅
   */
  off(event, listener) {
    return this.removeListener(event, listener);
  }
  /**
   * 暂停 supervisor 健康检查。
   * 用于配置变更触发 OpenClaw in-process restart 时，避免短暂的服务不可用被误判为假死。
   */
  pauseHealthCheck() {
    this.supervisor?.pauseHealthCheck();
  }
  /**
   * 恢复 supervisor 健康检查。
   */
  resumeHealthCheck() {
    this.supervisor?.resumeHealthCheck();
  }
  /**
   * 标记应用正在关闭
   */
  prepareShutdown() {
    this.isShuttingDown = true;
  }
  /**
   * 停止服务并清理
   */
  async shutdown() {
    this.prepareShutdown();
    this.externalMonitor?.stop();
    this.externalMonitor?.removeAllListeners();
    this.supervisor?.disable();
    if (this.service && this.service.getStatus().status !== "stopped") {
      this.supervisor?.notifyIntentionalStop();
      await this.service.stop();
    }
    this.service?.removeAllListeners();
    this.supervisor?.removeAllListeners();
  }
  // ==================== Private ====================
  /**
   * Supervisor 触发的重启回调
   * 与用户手动 restart() 不同：不重置熔断，不通知 intentionalStop
   */
  async supervisedRestart() {
    if (this.isShuttingDown || !this.service) return;
    const currentStatus = this.service.getStatus();
    if (currentStatus.status !== "stopped") {
      this.supervisor?.notifyIntentionalStop();
      await this.service.stop();
      await new Promise((resolve) => setTimeout(resolve, RESTART_DELAY_MS));
    }
    if (this.mode && this.runtimeConfig) {
      prepareForStart(this.mode, this.runtimeConfig);
    }
    await this.service.start();
    const newStatus = this.service.getStatus();
    this.supervisor?.notifyStarted(newStatus.port);
  }
  /**
   * 综合 service 和 supervisor 状态，返回 UI 应展示的状态
   */
  getSynthesizedStatus(serviceStatus, supervisorStatus) {
    if (supervisorStatus?.state === "circuit_open") {
      return "circuit_open";
    }
    if (supervisorStatus?.state === "recovering" && serviceStatus.status === "stopped") {
      return "recovering";
    }
    return serviceStatus.status;
  }
  /**
   * 广播融合后的状态
   * 通过 PM 自己的 EventEmitter 发射，IPC 层监听的是 PM 的事件
   */
  broadcastSynthesizedStatus() {
    const synthesized = this.getStatus();
    this.emit("status", synthesized);
  }
  setupServiceListeners() {
    if (!this.service) return;
    this.service.on("log", (log) => {
      const level = log.level === "warn" ? "warn" : log.level === "error" ? "error" : "info";
      mainLogger[level]("[OpenClaw]", log.message);
      this.emit("log", log);
    });
    this.service.on("status", () => {
      mainLogger.info("[ProcessManager] Status changed:", this.service?.getStatus().status);
      this.emit("status", this.getStatus());
    });
    this.service.on("unexpected-exit", (data) => {
      mainLogger.warn(
        `[ProcessManager] Unexpected exit detected (code: ${data.code}, signal: ${data.signal}), notifying supervisor`
      );
      this.supervisor?.notifyUnexpectedExit(data.code, data.signal);
      const serviceStatus = this.service?.getStatus();
      const supervisorStatus = this.supervisor?.getStatus();
      rumReport({
        name: RUM_EVENT_OPENCLAW_UNEXPECTED_EXIT,
        ext1: `code:${data.code ?? "null"}|signal:${data.signal ?? "null"}|port:${serviceStatus?.port ?? "unknown"}|pid:${serviceStatus?.pid ?? "null"}`,
        ext2: `supervisor:${supervisorStatus?.state ?? "unknown"}|restarts:${supervisorStatus?.restartCount ?? 0}|uptime:${serviceStatus?.uptime ? Math.floor(serviceStatus.uptime / 1e3) + "s" : "0s"}`
      });
      this.broadcastSynthesizedStatus();
    });
  }
  setupExternalMonitorListeners() {
    if (!this.externalMonitor) return;
    this.externalMonitor.on("log", (log) => {
      mainLogger.info("[ExternalMonitor]", log.message);
      this.emit("log", log);
    });
    this.externalMonitor.on("status", () => {
      this.emit("status", this.getStatus());
    });
  }
  setupSupervisorListeners() {
    if (!this.supervisor) return;
    this.supervisor.on("restart-scheduled", ({ delay, attempt }) => {
      const log = {
        level: "info",
        message: `[Supervisor] Auto-restart #${attempt} scheduled in ${(delay / 1e3).toFixed(1)}s`,
        timestamp: Date.now()
      };
      this.emit("log", log);
      this.broadcastSynthesizedStatus();
    });
    this.supervisor.on("restart-attempt", () => {
      const log = { level: "info", message: "[Supervisor] Attempting auto-restart...", timestamp: Date.now() };
      this.emit("log", log);
    });
    this.supervisor.on("restart-success", () => {
      const log = { level: "info", message: "[Supervisor] Auto-restart succeeded", timestamp: Date.now() };
      this.emit("log", log);
    });
    this.supervisor.on("restart-failed", ({ error }) => {
      const log = { level: "error", message: `[Supervisor] Auto-restart failed: ${error}`, timestamp: Date.now() };
      this.emit("log", log);
      this.broadcastSynthesizedStatus();
    });
    this.supervisor.on("circuit-open", ({ reason, crashHistory }) => {
      const log = { level: "error", message: `[Supervisor] Circuit breaker OPEN: ${reason}`, timestamp: Date.now() };
      this.emit("log", log);
      this.broadcastSynthesizedStatus();
      const historyStr = crashHistory ? crashHistory.map((c) => `${new Date(c.timestamp).toISOString()}(code:${c.exitCode ?? "null"},sig:${c.signal ?? "null"})`).join(",") : "";
      rumReport({
        name: RUM_EVENT_OPENCLAW_CIRCUIT_OPEN,
        ext1: `${reason}|restarts:${this.supervisor?.getStatus().restartCount ?? 0}`,
        ext2: historyStr
      });
    });
    this.supervisor.on("circuit-reset", () => {
      const log = { level: "info", message: "[Supervisor] Circuit breaker reset", timestamp: Date.now() };
      this.emit("log", log);
    });
    this.supervisor.on("health-failure", ({ consecutiveFailures }) => {
      const log = {
        level: "warn",
        message: `[Supervisor] Health check failed (${consecutiveFailures} consecutive)`,
        timestamp: Date.now()
      };
      this.emit("log", log);
    });
    this.supervisor.on("health-restart", () => {
      const log = { level: "warn", message: "[Supervisor] Process unresponsive, triggering restart", timestamp: Date.now() };
      this.emit("log", log);
      const svcStatus = this.service?.getStatus();
      const supStatus = this.supervisor?.getStatus();
      rumReport({
        name: RUM_EVENT_OPENCLAW_HEALTH_RESTART,
        ext1: `port:${svcStatus?.port ?? "unknown"}|pid:${svcStatus?.pid ?? "null"}|failures:${supStatus?.consecutiveHealthFailures ?? "unknown"}`,
        ext2: `restarts:${supStatus?.restartCount ?? 0}|uptime:${svcStatus?.uptime ? Math.floor(svcStatus.uptime / 1e3) + "s" : "0s"}`
      });
    });
    this.supervisor.on("stable", () => {
      const log = { level: "info", message: "[Supervisor] Process stable, crash history reset", timestamp: Date.now() };
      this.emit("log", log);
    });
  }
  setupExitHandlers() {
    if (process.env.NODE_ENV === "development") {
      process.on("SIGINT", async () => {
        mainLogger.info("[ProcessManager] Received SIGINT, shutting down...");
        await this.shutdown();
        process.exit(0);
      });
      process.on("SIGTERM", async () => {
        mainLogger.info("[ProcessManager] Received SIGTERM, shutting down...");
        await this.shutdown();
        process.exit(0);
      });
    }
  }
}
let processManagerInstance = null;
function getProcessManager() {
  if (!processManagerInstance) {
    processManagerInstance = new ProcessManager();
  }
  return processManagerInstance;
}
function deepMerge(target, source) {
  const result = structuredClone(target);
  for (const key of Object.keys(source)) {
    const sourceVal = source[key];
    const targetVal = result[key];
    if (sourceVal !== null && sourceVal !== void 0 && typeof sourceVal === "object" && !Array.isArray(sourceVal) && targetVal !== null && targetVal !== void 0 && typeof targetVal === "object" && !Array.isArray(targetVal)) {
      result[key] = deepMerge(
        targetVal,
        sourceVal
      );
    } else {
      result[key] = structuredClone(sourceVal);
    }
  }
  return result;
}
const BACKUP_FILE_PATTERN = /^openclaw\.\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z\.json$/;
class ConfigManager {
  configPath;
  backupDir;
  defaultGatewayPort;
  templatePath;
  deps;
  /** 写入锁：链式 Promise，保证 read-merge-write 操作串行化，防止并发 lost update */
  writeLock = Promise.resolve();
  constructor(options) {
    this.configPath = options.configPath;
    this.defaultGatewayPort = options.defaultGatewayPort;
    this.templatePath = options.templatePath;
    this.backupDir = path.join(path.dirname(this.configPath), BACKUP_DIR_NAME);
    this.deps = options.deps;
  }
  getDefaultConfig() {
    return {
      gateway: {
        port: this.defaultGatewayPort,
        bind: GATEWAY_DEFAULT_BIND,
        auth: { mode: "none" }
      },
      agents: {
        defaults: {
          model: {
            primary: DEFAULT_MODEL_PRIMARY
          }
        }
      },
      models: {
        providers: {}
      }
    };
  }
  /**
   * 读取完整配置
   * 使用 safeParse 只做校验，返回原始 JSON 对象以保留 schema 未定义的字段（如 auth、messages、commands、session 等）
   */
  async get() {
    const exists = await this.exists();
    if (!exists) {
      return await this.createDefault();
    }
    const parsed = await readConfigFile(this.configPath);
    const result = OpenClawConfigSchema.safeParse(parsed);
    if (!result.success) {
      mainLogger.warn("[ConfigManager] 配置校验警告:", result.error.message);
    }
    return parsed;
  }
  /**
   * 写入配置（串行化）
   *
   * 通过 writeLock 保证多个并发调用按顺序执行，
   * 每次操作都读取最新磁盘内容再合并，避免 lost update。
   *
   * @returns { oldConfig, newConfig } — oldConfig 是写入前的磁盘快照（在锁内读取），
   *          供 updateField 回滚时使用，避免在锁外读取导致 TOCTOU 问题。
   */
  set(newConfig) {
    const operation = this.writeLock.then(async () => {
      const currentConfig = await this.get();
      const mergedConfig = deepMerge(
        currentConfig,
        newConfig
      );
      mainLogger.info("[ConfigManager] mergedConfig", JSON.stringify(mergedConfig, null, 2));
      const result = OpenClawConfigSchema.safeParse(mergedConfig);
      if (!result.success) {
        throw new Error(`配置校验失败: ${result.error.message}`);
      }
      await this.createBackup();
      try {
        await fs$1.mkdir(path.dirname(this.configPath), { recursive: true });
        await writeConfigFile(this.configPath, mergedConfig);
        return { oldConfig: currentConfig, newConfig: mergedConfig };
      } catch (error) {
        await this.rollback();
        throw error;
      }
    });
    this.writeLock = operation.then(() => {
    }, () => {
    });
    return operation;
  }
  async exists() {
    try {
      await fs$1.access(this.configPath);
      return true;
    } catch {
      return false;
    }
  }
  /**
   * 创建默认配置文件
   * 优先从内置模板读取完整配置（包含 channels、plugins 等 schema 未定义的字段），
   * 模板不可用时退回到精简骨架。
   */
  async createDefault() {
    let defaultConfig;
    if (this.templatePath && fs.existsSync(this.templatePath)) {
      defaultConfig = readConfigFileSync(this.templatePath);
      mainLogger.info("[ConfigManager] Creating default config from template");
    } else {
      defaultConfig = this.getDefaultConfig();
      mainLogger.warn("[ConfigManager] Template not found, using minimal default config");
    }
    await fs$1.mkdir(path.dirname(this.configPath), { recursive: true });
    await writeConfigFile(this.configPath, defaultConfig);
    return defaultConfig;
  }
  /**
   * 颗粒化获取配置字段
   * @param keyPath 点分隔路径，如 'gateway.port'、'models.providers.openai.apiKey'，传空字符串获取完整配置
   * @returns 字段值，路径不存在时返回 undefined
   */
  async getField(keyPath) {
    const config2 = await this.get();
    return this.getNestedValue(config2, keyPath);
  }
  /**
   * 颗粒化更新配置字段
   * 接收 JSON 格式的 partial 配置，完成校验/备份/写入/服务验证/回滚
   * @param partialConfig 要更新的部分配置（JSON 对象格式）
   * @returns ConfigUpdateResult 包含成功/失败状态、配置、服务重启信息
   */
  async updateField(partialConfig) {
    let oldConfig;
    let newConfig;
    try {
      const result = await this.set(partialConfig);
      oldConfig = result.oldConfig;
      newConfig = result.newConfig;
    } catch (error) {
      const currentConfig = await this.get();
      const message = error instanceof Error ? error.message : "配置校验失败";
      return {
        success: false,
        config: currentConfig,
        message: `配置更新失败: ${message}`,
        serviceRestarted: false,
        error: message
      };
    }
    if (!this.deps) {
      return {
        success: true,
        config: newConfig,
        message: "配置已更新",
        serviceRestarted: false
      };
    }
    const status = this.deps.getProcessStatus();
    if (status.status !== "running") {
      return {
        success: true,
        config: newConfig,
        message: "配置已更新（服务未运行，下次启动生效）",
        serviceRestarted: false
      };
    }
    try {
      await this.deps.restartProcess();
      const isHealthy = await this.deps.checkHealthWithRetry({
        port: newConfig.gateway.port,
        retries: 5,
        retryDelay: HEALTH_CHECK_DEFAULT_RETRY_DELAY_MS,
        timeout: HEALTH_CHECK_TIMEOUT
      });
      if (isHealthy) {
        return {
          success: true,
          config: newConfig,
          message: "配置已更新，服务重启成功",
          serviceRestarted: true
        };
      }
      throw new Error("服务健康检查未通过");
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : "服务重启失败";
      try {
        await this.set(oldConfig);
        await this.deps.restartProcess();
        await this.deps.checkHealthWithRetry({
          port: oldConfig.gateway.port,
          retries: HEALTH_CHECK_DEFAULT_RETRIES,
          retryDelay: HEALTH_CHECK_DEFAULT_RETRY_DELAY_MS,
          timeout: HEALTH_CHECK_TIMEOUT
        });
      } catch (rollbackError) {
        const rollbackMsg = rollbackError instanceof Error ? rollbackError.message : "未知错误";
        mainLogger.error("[ConfigManager] 配置回滚失败:", rollbackMsg);
      }
      const rolledBackConfig = await this.get();
      return {
        success: false,
        config: rolledBackConfig,
        message: "配置更新失败，已回滚到原配置",
        serviceRestarted: true,
        error: errorMessage
      };
    }
  }
  /**
   * 按点分隔路径获取嵌套对象的值
   */
  getNestedValue(obj, keyPath) {
    if (!keyPath) {
      return obj;
    }
    const keys = keyPath.split(".");
    let current = obj;
    for (const key of keys) {
      if (current === null || current === void 0 || typeof current !== "object") {
        return void 0;
      }
      current = current[key];
    }
    return current;
  }
  async getBackupList() {
    try {
      const files = await fs$1.readdir(this.backupDir);
      const backupFiles = files.filter((f) => BACKUP_FILE_PATTERN.test(f)).map((filename) => ({
        filename,
        path: path.join(this.backupDir, filename),
        timestamp: this.parseBackupTimestamp(filename)
      })).sort((a, b) => b.timestamp - a.timestamp);
      return backupFiles;
    } catch {
      return [];
    }
  }
  async rollback() {
    const backups = await this.getBackupList();
    if (backups.length === 0) {
      throw new Error("没有可用的备份文件");
    }
    const latestBackup = backups[0];
    await fs$1.copyFile(latestBackup.path, this.configPath);
  }
  async createBackup() {
    const configExists = await this.exists();
    if (!configExists) {
      return;
    }
    await fs$1.mkdir(this.backupDir, { recursive: true });
    const timestamp = (/* @__PURE__ */ new Date()).toISOString().replace(/[:.]/g, "-");
    const backupFilename = `openclaw.${timestamp}.json`;
    const backupPath = path.join(this.backupDir, backupFilename);
    await fs$1.copyFile(this.configPath, backupPath);
    await this.cleanOldBackups(BACKUP_KEEP_COUNT);
  }
  async cleanOldBackups(keepCount) {
    const backups = await this.getBackupList();
    const toDelete = backups.slice(keepCount);
    for (const backup of toDelete) {
      await fs$1.unlink(backup.path);
    }
  }
  parseBackupTimestamp(filename) {
    const match = filename.match(/openclaw\.(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d{3}Z)\.json/);
    if (!match) {
      return 0;
    }
    const timestampStr = match[1].replace(/-/g, ":").replace("T", "T");
    return new Date(timestampStr).getTime();
  }
}
function willTriggerRestart(partialConfig) {
  const changedPaths = extractChangedPaths(partialConfig);
  return changedPaths.some((p) => classifyPath(p) === "restart");
}
function extractChangedPaths(obj, prefix = "") {
  const paths = [];
  for (const key of Object.keys(obj)) {
    const fullPath = prefix ? `${prefix}.${key}` : key;
    const value = obj[key];
    if (value !== null && value !== void 0 && typeof value === "object" && !Array.isArray(value)) {
      paths.push(...extractChangedPaths(value, fullPath));
    } else {
      paths.push(fullPath);
    }
  }
  return paths;
}
const HIGH_PRIORITY_RULES = [
  { prefix: "gateway.remote", kind: "none" },
  { prefix: "gateway.reload", kind: "none" },
  { prefix: "hooks.gmail", kind: "hot" },
  { prefix: "hooks", kind: "hot" },
  { prefix: "agents.defaults.heartbeat", kind: "hot" },
  { prefix: "agent.heartbeat", kind: "hot" },
  { prefix: "cron", kind: "hot" },
  { prefix: "browser", kind: "hot" },
  // Channel 热重载规则：所有 channels.* 变更都是 channel 级热重载，不触发 gateway restart
  // WhatsApp 是唯一特例：通过 web 前缀触发重载，channels.whatsapp 自身为 none
  { prefix: "channels.whatsapp", kind: "none" },
  { prefix: "channels", kind: "hot" },
  { prefix: "web", kind: "hot" }
];
const LOW_PRIORITY_RULES = [
  { prefix: "meta", kind: "none" },
  { prefix: "identity", kind: "none" },
  { prefix: "wizard", kind: "none" },
  { prefix: "logging", kind: "none" },
  { prefix: "models", kind: "none" },
  { prefix: "agents", kind: "none" },
  { prefix: "tools", kind: "none" },
  { prefix: "bindings", kind: "none" },
  { prefix: "audio", kind: "none" },
  { prefix: "agent", kind: "none" },
  { prefix: "routing", kind: "none" },
  { prefix: "messages", kind: "none" },
  { prefix: "session", kind: "none" },
  { prefix: "talk", kind: "none" },
  { prefix: "skills", kind: "none" },
  { prefix: "plugins", kind: "restart" },
  { prefix: "ui", kind: "none" },
  { prefix: "gateway", kind: "restart" },
  { prefix: "discovery", kind: "restart" },
  { prefix: "canvasHost", kind: "restart" }
];
function classifyPath(configPath) {
  for (const rule of HIGH_PRIORITY_RULES) {
    if (matchesPrefix(configPath, rule.prefix)) {
      return rule.kind;
    }
  }
  for (const rule of LOW_PRIORITY_RULES) {
    if (matchesPrefix(configPath, rule.prefix)) {
      return rule.kind;
    }
  }
  return "restart";
}
function matchesPrefix(configPath, prefix) {
  return configPath === prefix || configPath.startsWith(`${prefix}.`);
}
const { machineId: machineId$1 } = pkg;
const logBuffer = [];
function pushLogBuffer(log) {
  logBuffer.push(log);
  if (logBuffer.length > LOG_BUFFER_CAPACITY) {
    logBuffer.splice(0, logBuffer.length - LOG_BUFFER_CAPACITY);
  }
}
function setupWindowMaximizeEvents(window2) {
  window2.on("maximize", () => {
    if (!window2.isDestroyed()) {
      window2.webContents.send("window:maximizeChange", true);
    }
  });
  window2.on("unmaximize", () => {
    if (!window2.isDestroyed()) {
      window2.webContents.send("window:maximizeChange", false);
    }
  });
}
function broadcastToWindows(channel, ...args) {
  for (const window2 of BrowserWindow.getAllWindows()) {
    if (!window2.isDestroyed()) {
      window2.webContents.send(channel, ...args);
    }
  }
}
let configManagerInstance = null;
function getConfigManager() {
  if (!configManagerInstance) {
    const runtimeConfig = getProcessManager().getRuntimeConfig();
    configManagerInstance = new ConfigManager({
      configPath: runtimeConfig?.configPath ?? OPENCLAW_CONFIG_PATH,
      defaultGatewayPort: OPENCLAW_DEFAULT_GATEWAY_PORT,
      templatePath: getDefaultConfigSourcePath()
    });
  }
  return configManagerInstance;
}
function handleDownloadResponse(response, filePath, sender, resolve, reject) {
  if (response.statusCode && response.statusCode >= 400) {
    reject(new Error(`HTTP ${response.statusCode}`));
    return;
  }
  const totalBytes = parseInt(response.headers["content-length"] || "0", 10);
  let receivedBytes = 0;
  const fileStream = createWriteStream(filePath);
  response.on("data", (chunk) => {
    receivedBytes += chunk.length;
    if (totalBytes > 0 && !sender.isDestroyed()) {
      const percent = Math.round(receivedBytes / totalBytes * 100);
      sender.send("app:downloadProgress", percent);
    }
  });
  response.pipe(fileStream);
  fileStream.on("finish", () => {
    fileStream.close();
    if (!sender.isDestroyed()) {
      sender.send("app:downloadProgress", 100);
    }
    resolve(filePath);
  });
  fileStream.on("error", (err) => {
    fileStream.close();
    reject(err);
  });
}
function setupIpcHandlers() {
  const processManager = getProcessManager();
  ipcMain.handle("window:minimize", async (event) => {
    BrowserWindow.fromWebContents(event.sender)?.minimize();
  });
  ipcMain.handle("window:maximize", async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win) {
      if (win.isMaximized()) {
        win.unmaximize();
      } else {
        win.maximize();
      }
    }
  });
  ipcMain.handle("window:close", async (event) => {
    BrowserWindow.fromWebContents(event.sender)?.close();
  });
  ipcMain.handle("window:isMaximized", async (event) => {
    return BrowserWindow.fromWebContents(event.sender)?.isMaximized() ?? false;
  });
  app.on("browser-window-created", (_event, window2) => {
    setupWindowMaximizeEvents(window2);
  });
  ipcMain.handle("process:start", async (_event, options) => {
    return processManager.start(options);
  });
  ipcMain.handle("process:stop", async () => {
    return processManager.stop();
  });
  ipcMain.handle("process:restart", async () => {
    return processManager.restart();
  });
  ipcMain.handle("process:getStatus", async () => {
    return processManager.getStatus();
  });
  ipcMain.handle("process:getLogs", async () => {
    return [...logBuffer];
  });
  ipcMain.handle("process:openControlUI", async () => {
    try {
      const configPath = getConfigPath();
      const config2 = readConfigFileSync(configPath);
      const token = config2.gateway?.auth?.token ?? "";
      const port = config2.gateway?.port ?? OPENCLAW_DEFAULT_GATEWAY_PORT;
      await shell.openExternal(`http://${LOCALHOST_ADDRESS}:${port}#token=${token}`);
    } catch (err) {
      openclawLogger.error("Failed to open Control UI:", err);
    }
  });
  processManager.onStatusChange((status) => {
    broadcastToWindows("process:status", status);
  });
  processManager.onLog((log) => {
    pushLogBuffer(log);
    broadcastToWindows("process:log", log);
    const level = log.level === "warn" ? "warn" : log.level === "error" ? "error" : "info";
    openclawLogger[level](log.message);
  });
  ipcMain.handle("config:getField", async (_event, keyPath) => {
    return getConfigManager().getField(keyPath);
  });
  ipcMain.handle("config:updateField", async (_event, partialConfig) => {
    const configManager = getConfigManager();
    const pm = getProcessManager();
    const status = pm.getStatus();
    const triggersRestart = status.status === "running" && willTriggerRestart(partialConfig);
    if (!triggersRestart) {
      return configManager.updateField(partialConfig);
    }
    openclawLogger.info("[IPC] Config change will trigger OpenClaw in-process restart, pausing health checks");
    pm.pauseHealthCheck();
    try {
      const result = await configManager.updateField(partialConfig);
      if (!result.success) {
        pm.resumeHealthCheck();
        return result;
      }
      const port = status.port;
      const isHealthy = await checkHealthWithRetry({
        port,
        retries: 30,
        retryDelay: 1e3,
        timeout: 5e3
      });
      pm.resumeHealthCheck();
      if (isHealthy) {
        openclawLogger.info("[IPC] OpenClaw in-process restart completed, service healthy");
        return {
          ...result,
          message: "配置已更新，服务已重新加载",
          serviceRestarted: true
        };
      } else {
        openclawLogger.warn("[IPC] OpenClaw did not become healthy after config restart");
        return {
          ...result,
          message: "配置已更新，但服务可能仍在重启中",
          serviceRestarted: true
        };
      }
    } catch (error) {
      pm.resumeHealthCheck();
      throw error;
    }
  });
  ipcMain.handle("app:get-machine-id", async () => {
    return machineId$1();
  });
  ipcMain.handle("app:get-version", async () => {
    return app.getVersion();
  });
  ipcMain.handle("app:get-channel", async () => {
    try {
      const channelPath = join(process.resourcesPath, "channel.json");
      const content = readFileSync(channelPath, "utf-8");
      const data = JSON.parse(content);
      return String(data.channel ?? "");
    } catch {
      return "";
    }
  });
  ipcMain.handle("app:openPath", async (_event, filePath) => {
    return shell.openPath(filePath);
  });
  ipcMain.handle("app:quit", async () => {
    app.quit();
  });
  ipcMain.handle("app:downloadFile", async (event, url, fileName) => {
    const downloadsDir = app.getPath("downloads");
    if (!existsSync(downloadsDir)) {
      mkdirSync(downloadsDir, { recursive: true });
    }
    const resolvedFileName = fileName || basename(new URL(url).pathname) || "update.dmg";
    const filePath = join(downloadsDir, resolvedFileName);
    const sender = event.sender;
    return new Promise((resolve, reject) => {
      const protocol = url.startsWith("https") ? require2("https") : require2("http");
      const request = protocol.get(url, (response) => {
        if (response.statusCode && response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
          const redirectUrl = response.headers.location;
          const redirectProtocol = redirectUrl.startsWith("https") ? require2("https") : require2("http");
          redirectProtocol.get(redirectUrl, (redirectResponse) => {
            handleDownloadResponse(redirectResponse, filePath, sender, resolve, reject);
          }).on("error", (err) => {
            openclawLogger.error("[IPC] downloadFile redirect error:", err);
            reject(err);
          });
          return;
        }
        handleDownloadResponse(response, filePath, sender, resolve, reject);
      });
      request.on("error", (err) => {
        openclawLogger.error("[IPC] downloadFile request error:", err);
        reject(err);
      });
    });
  });
  ipcMain.handle("instance:getBootState", async () => {
    return getBootState();
  });
  ipcMain.handle("instance:setMode", async (_event, mode) => {
    const bootState = getBootState();
    await initializeWithMode(mode, bootState?.externalInstance, true);
    broadcastToWindows("instance:modeChange", mode);
  });
  ipcMain.handle("instance:getMode", async () => {
    return processManager.getMode();
  });
  ipcMain.handle("instance:retryBoot", async () => {
    return retryBootSequence();
  });
  ipcMain.handle("rum:report", async (_event, event) => {
    rumReport(event, RUM_FROM_RENDERER);
  });
  ipcMain.handle("session:trimLastExchange", async (_event, sessionKey) => {
    try {
      const runtimeConfig = processManager.getRuntimeConfig();
      if (!runtimeConfig?.stateDir) {
        openclawLogger.warn("[IPC] trimLastExchange: stateDir 不可用");
        return false;
      }
      const parts = sessionKey.split(":");
      const agentId = parts[1] || "main";
      const sessionsJsonPath = join(
        runtimeConfig.stateDir,
        "agents",
        agentId,
        "sessions",
        "sessions.json"
      );
      const fs2 = await import("fs");
      if (!fs2.existsSync(sessionsJsonPath)) {
        openclawLogger.warn(`[IPC] trimLastExchange: sessions.json 不存在: ${sessionsJsonPath}`);
        return false;
      }
      const sessionsData = JSON.parse(fs2.readFileSync(sessionsJsonPath, "utf-8"));
      const sessionInfo = sessionsData[sessionKey];
      if (!sessionInfo?.sessionFile) {
        openclawLogger.warn(`[IPC] trimLastExchange: session 文件未找到: ${sessionKey}`);
        return false;
      }
      const { dirname, isAbsolute } = await import("path");
      const fullSessionPath = isAbsolute(sessionInfo.sessionFile) ? sessionInfo.sessionFile : join(dirname(sessionsJsonPath), sessionInfo.sessionFile);
      if (!fs2.existsSync(fullSessionPath)) {
        openclawLogger.warn(`[IPC] trimLastExchange: JSONL 文件不存在: ${fullSessionPath}`);
        return false;
      }
      const content = fs2.readFileSync(fullSessionPath, "utf-8");
      const lines = content.split("\n").filter((l) => l.trim());
      let lastUserIndex = -1;
      for (let i = lines.length - 1; i >= 0; i--) {
        const line = lines[i];
        if (!line) continue;
        try {
          const item = JSON.parse(line);
          if (item.type === "message" && item.message?.role === "user") {
            lastUserIndex = i;
            break;
          }
        } catch {
        }
      }
      if (lastUserIndex === -1) {
        openclawLogger.warn(`[IPC] trimLastExchange: 未找到 user 消息`);
        return false;
      }
      const remaining = lines.slice(0, lastUserIndex);
      fs2.writeFileSync(fullSessionPath, remaining.join("\n") + (remaining.length > 0 ? "\n" : ""));
      openclawLogger.info(
        `[IPC] trimLastExchange: 成功删除 session ${sessionKey} 最后 ${lines.length - lastUserIndex} 条消息`
      );
      return true;
    } catch (error) {
      openclawLogger.error("[IPC] trimLastExchange 失败:", error);
      return false;
    }
  });
  ipcMain.handle("debug:openLogFolder", async () => {
    const logsPath = app.getPath("logs");
    await shell.openPath(logsPath);
  });
  ipcMain.handle("debug:packQclaw", async () => {
    const scriptPath = app.isPackaged ? join(process.resourcesPath, "scripts", "pack-qclaw.cjs") : join(app.getAppPath(), "scripts", "pack-qclaw.cjs");
    const { packQclaw } = require2(scriptPath);
    const result = await packQclaw();
    shell.showItemInFolder(result.outputFile);
    return result;
  });
}
function getIconsBaseDir() {
  if (app.isPackaged) {
    return join(process.resourcesPath, "icons");
  }
  return join(__dirname, "../../resources/icons");
}
function getMacTrayIcon(iconsBaseDir) {
  const isDark = nativeTheme.shouldUseDarkColors;
  const variant = isDark ? "light" : "dark";
  const iconPath = join(iconsBaseDir, "tray", "mac", `${variant}.png`);
  if (existsSync(iconPath)) {
    return nativeImage.createFromPath(iconPath);
  }
  return nativeImage.createEmpty();
}
function getTrayIcon() {
  const iconsBaseDir = getIconsBaseDir();
  const platform2 = process.platform;
  if (platform2 === "darwin") {
    return getMacTrayIcon(iconsBaseDir);
  }
  let iconPath;
  if (platform2 === "win32") {
    iconPath = join(iconsBaseDir, "tray", "win", "tray.ico");
  } else {
    iconPath = join(iconsBaseDir, "tray", "linux", "tray.png");
  }
  if (existsSync(iconPath)) {
    return nativeImage.createFromPath(iconPath);
  }
  return nativeImage.createEmpty();
}
function getAppIcon() {
  if (process.platform === "darwin") {
    return void 0;
  }
  const iconPath = join(getIconsBaseDir(), "app", "linux", "icon.png");
  return existsSync(iconPath) ? iconPath : void 0;
}
class TrayManager {
  tray = null;
  mainWindow = null;
  _isQuitting = false;
  /**
   * 初始化托盘，绑定主窗口
   * 应在 mainWindow ready-to-show 后调用
   */
  init(mainWindow2) {
    this.mainWindow = mainWindow2;
    if (this.tray && !this.tray.isDestroyed()) {
      return;
    }
    this.createTray();
    this.setupWindowCloseHandler();
    this.setupThemeChangeHandler();
  }
  /**
   * 是否正在退出应用
   */
  get isQuitting() {
    return this._isQuitting;
  }
  /**
   * 标记退出并触发 app.quit()
   */
  quit() {
    this._isQuitting = true;
    app.quit();
  }
  /**
   * 销毁托盘图标
   */
  destroy() {
    this.tray?.destroy();
    this.tray = null;
  }
  createTray() {
    this.tray = new Tray(getTrayIcon());
    this.tray.setToolTip(TRAY_TOOLTIP);
    const contextMenu = Menu.buildFromTemplate([
      { label: "显示窗口", click: () => this.showWindow() },
      { type: "separator" },
      { label: "退出", click: () => this.quit() }
    ]);
    this.tray.on("right-click", () => {
      this.tray?.popUpContextMenu(contextMenu);
    });
    this.tray.on("click", () => this.showWindow());
    this.tray.on("double-click", () => this.showWindow());
  }
  /**
   * 监听系统主题变化，动态切换托盘图标
   * macOS 在亮色/暗色模式切换时更新图标颜色
   */
  setupThemeChangeHandler() {
    if (process.platform !== "darwin") return;
    nativeTheme.on("updated", () => {
      this.tray?.setImage(getTrayIcon());
    });
  }
  /**
   * 拦截窗口关闭：非退出状态下隐藏窗口而非销毁
   */
  setupWindowCloseHandler() {
    this.mainWindow?.on("close", (event) => {
      if (!this._isQuitting) {
        event.preventDefault();
        this.mainWindow?.hide();
      }
    });
  }
  showWindow() {
    if (!this.mainWindow) return;
    this.mainWindow.show();
    this.mainWindow.focus();
  }
}
let trayManagerInstance = null;
function getTrayManager() {
  if (!trayManagerInstance) {
    trayManagerInstance = new TrayManager();
  }
  return trayManagerInstance;
}
const RELOADABLE_REASONS = /* @__PURE__ */ new Set(["crashed", "oom"]);
class CrashHandler extends EventEmitter {
  crashReportDir;
  gpuFlagPath;
  /** webContentsId → reload 时间戳数组，用于限速 */
  rendererReloadHistory = /* @__PURE__ */ new Map();
  initialized = false;
  /** 预留：远程上报实现 */
  reporter = null;
  constructor() {
    super();
    const logsDir = app.getPath("logs");
    this.crashReportDir = path.join(logsDir, CRASH_REPORT_DIR_NAME);
    this.gpuFlagPath = path.join(app.getPath("userData"), GPU_DEGRADATION_FLAG_FILE);
  }
  /**
   * 初始化崩溃处理器
   * 必须在 app.whenReady() 之后、createWindow() 之前调用
   * 注册所有崩溃事件监听器
   */
  initialize() {
    if (this.initialized) {
      mainLogger.warn("[CrashHandler] Already initialized, skipping");
      return;
    }
    this.initialized = true;
    fs.mkdirSync(this.crashReportDir, { recursive: true });
    this.setupProcessErrorHandlers();
    this.setupChildProcessGoneHandler();
    this.setupBrowserWindowCreatedHandler();
    mainLogger.info("[CrashHandler] Initialized");
  }
  /**
   * 监听指定窗口的渲染进程崩溃
   * 通过 browser-window-created 事件自动调用，也可手动调用
   */
  watchWindow(window2) {
    window2.webContents.on("render-process-gone", (_event, details) => {
      const { reason, exitCode } = details;
      mainLogger.error(
        `[CrashHandler] Renderer process gone: reason=${reason}, exitCode=${exitCode}`
      );
      const isGpuCrash = reason === "gpu-dead";
      const report = this.createCrashReport({
        source: "render-process-gone",
        reason,
        exitCode,
        processType: "renderer",
        gpuDegradationTriggered: isGpuCrash
      });
      if (isGpuCrash) {
        this.setGpuDegradationFlag(reason);
      }
      this.persistCrashReport(report);
      if (!window2.isDestroyed() && RELOADABLE_REASONS.has(reason)) {
        report.rendererReloadAttempted = this.attemptRendererReload(window2);
        this.persistCrashReport(report);
      }
    });
  }
  /**
   * 预留：设置远程崩溃上报实现
   */
  setReporter(reporter) {
    this.reporter = reporter;
  }
  // ==================== 私有：事件处理器注册 ====================
  /**
   * 注册 uncaughtException 和 unhandledRejection 处理器
   * 注意：这些处理器从 ProcessManager.setupExitHandlers() 迁移至此
   */
  setupProcessErrorHandlers() {
    process.on("uncaughtException", (error) => {
      mainLogger.error("[CrashHandler] Uncaught exception:", error);
      const report = this.createCrashReport({
        source: "uncaughtException",
        reason: error.message,
        stack: error.stack,
        processType: "main"
      });
      this.persistCrashReport(report);
      this.emit("fatal-error", { error, exitCode: 1 });
    });
    process.on("unhandledRejection", (reason) => {
      const message = reason instanceof Error ? reason.message : String(reason);
      const stack = reason instanceof Error ? reason.stack : void 0;
      mainLogger.error("[CrashHandler] Unhandled rejection:", reason);
      const report = this.createCrashReport({
        source: "unhandledRejection",
        reason: message,
        stack,
        processType: "main"
      });
      this.persistCrashReport(report);
      this.emit("fatal-error", { error: reason instanceof Error ? reason : new Error(message), exitCode: 1 });
    });
  }
  /**
   * 注册 child-process-gone 监听器
   * 捕获 GPU 进程崩溃、Utility 进程崩溃等
   */
  setupChildProcessGoneHandler() {
    app.on("child-process-gone", (_event, details) => {
      const { type, reason, exitCode, name } = details;
      mainLogger.error(
        `[CrashHandler] Child process gone: type=${type}, reason=${reason}, exitCode=${exitCode}, name=${name ?? "unknown"}`
      );
      const isGpuProcess = type === "GPU";
      const report = this.createCrashReport({
        source: "child-process-gone",
        reason: `${type}: ${reason}`,
        exitCode,
        processType: isGpuProcess ? "gpu" : type.toLowerCase(),
        gpuDegradationTriggered: isGpuProcess
      });
      if (isGpuProcess) {
        this.setGpuDegradationFlag(reason);
      }
      this.persistCrashReport(report);
    });
  }
  /**
   * 自动监听新创建的 BrowserWindow
   */
  setupBrowserWindowCreatedHandler() {
    app.on("browser-window-created", (_event, window2) => {
      this.watchWindow(window2);
    });
  }
  // ==================== 私有：崩溃报告 ====================
  createCrashReport(params) {
    const now = /* @__PURE__ */ new Date();
    return {
      id: `crash-${now.getTime()}-${Math.random().toString(36).slice(2, 8)}`,
      source: params.source,
      timestamp: now.toISOString(),
      reason: params.reason,
      exitCode: params.exitCode,
      stack: params.stack,
      processType: params.processType,
      system: this.captureSystemSnapshot(),
      gpuDegradationTriggered: params.gpuDegradationTriggered ?? false,
      rendererReloadAttempted: false,
      appVersion: app.getVersion()
    };
  }
  captureSystemSnapshot() {
    const snapshot = {
      platform: process.platform,
      arch: process.arch,
      osVersion: os.release(),
      electronVersion: process.versions["electron"] ?? "unknown",
      chromeVersion: process.versions["chrome"] ?? "unknown",
      nodeVersion: process.versions["node"] ?? "unknown",
      totalMemory: os.totalmem(),
      freeMemory: os.freemem(),
      uptime: process.uptime()
    };
    try {
      const gpuInfo = app.getGPUFeatureStatus();
      snapshot.gpuFeatureStatus = gpuInfo;
    } catch {
    }
    return snapshot;
  }
  /**
   * 同步写入崩溃报告到磁盘
   * 使用 writeFileSync 确保进程退出前数据落盘
   */
  persistCrashReport(report) {
    try {
      fs.mkdirSync(this.crashReportDir, { recursive: true });
      const filePath = path.join(this.crashReportDir, `${report.id}.json`);
      fs.writeFileSync(filePath, JSON.stringify(report, null, 2), "utf-8");
      mainLogger.info(`[CrashHandler] Crash report saved: ${filePath}`);
      this.cleanupOldReports();
      this.reporter?.upload(report).catch(() => {
      });
    } catch (err) {
      mainLogger.error("[CrashHandler] Failed to persist crash report:", err);
    }
  }
  /**
   * 清理过期崩溃报告，保留最新 CRASH_REPORT_MAX_COUNT 条
   */
  cleanupOldReports() {
    try {
      const files = fs.readdirSync(this.crashReportDir).filter((f) => f.startsWith("crash-") && f.endsWith(".json")).sort();
      if (files.length > CRASH_REPORT_MAX_COUNT) {
        const toDelete = files.slice(0, files.length - CRASH_REPORT_MAX_COUNT);
        for (const file2 of toDelete) {
          fs.unlinkSync(path.join(this.crashReportDir, file2));
        }
      }
    } catch {
    }
  }
  // ==================== 私有：GPU 降级 ====================
  /**
   * 写入 GPU 降级标记文件
   * 下次启动时由 checkGpuDegradation() 读取并禁用硬件加速
   */
  setGpuDegradationFlag(reason) {
    try {
      const flag = {
        flaggedAt: Date.now(),
        reason,
        gpuInfo: this.getGpuInfoString()
      };
      fs.writeFileSync(this.gpuFlagPath, JSON.stringify(flag, null, 2), "utf-8");
      mainLogger.warn(
        "[CrashHandler] GPU degradation flag set, hardware acceleration will be disabled on next launch"
      );
    } catch (err) {
      mainLogger.error("[CrashHandler] Failed to set GPU degradation flag:", err);
    }
  }
  getGpuInfoString() {
    try {
      return JSON.stringify(app.getGPUFeatureStatus());
    } catch {
      return "unavailable";
    }
  }
  // ==================== 私有：渲染进程 Reload ====================
  /**
   * 尝试 reload 崩溃的渲染进程
   * 限速策略：RENDERER_RELOAD_WINDOW_MS 内最多 RENDERER_RELOAD_MAX_RETRIES 次
   * 返回是否成功发起 reload
   */
  attemptRendererReload(window2) {
    if (window2.isDestroyed()) return false;
    const wcId = window2.webContents.id;
    const now = Date.now();
    let history = this.rendererReloadHistory.get(wcId);
    if (!history) {
      history = [];
      this.rendererReloadHistory.set(wcId, history);
    }
    const cutoff = now - RENDERER_RELOAD_WINDOW_MS;
    const recentHistory = history.filter((t) => t > cutoff);
    this.rendererReloadHistory.set(wcId, recentHistory);
    if (recentHistory.length >= RENDERER_RELOAD_MAX_RETRIES) {
      mainLogger.error(
        `[CrashHandler] Renderer reload rate limit reached (${RENDERER_RELOAD_MAX_RETRIES} in ${RENDERER_RELOAD_WINDOW_MS / 1e3}s), not reloading`
      );
      return false;
    }
    recentHistory.push(now);
    mainLogger.info(`[CrashHandler] Scheduling renderer reload in ${RENDERER_RELOAD_DELAY_MS}ms`);
    setTimeout(() => {
      try {
        if (!window2.isDestroyed()) {
          window2.webContents.reload();
          mainLogger.info("[CrashHandler] Renderer reloaded successfully");
        }
      } catch (err) {
        mainLogger.error("[CrashHandler] Failed to reload renderer:", err);
      }
    }, RENDERER_RELOAD_DELAY_MS);
    return true;
  }
}
let crashHandlerInstance = null;
function getCrashHandler() {
  if (!crashHandlerInstance) {
    crashHandlerInstance = new CrashHandler();
  }
  return crashHandlerInstance;
}
function checkGpuDegradation() {
  try {
    const flagPath = path.join(app.getPath("userData"), GPU_DEGRADATION_FLAG_FILE);
    if (!fs.existsSync(flagPath)) {
      return false;
    }
    const raw = fs.readFileSync(flagPath, "utf-8");
    const flag = JSON.parse(raw);
    app.commandLine.appendSwitch("disable-gpu");
    app.commandLine.appendSwitch("disable-gpu-compositing");
    console.warn(
      `[CrashHandler] GPU degradation mode active (flagged at ${new Date(flag.flaggedAt).toISOString()}, reason: ${flag.reason}). Hardware acceleration disabled.`
    );
    fs.unlinkSync(flagPath);
    return true;
  } catch {
    return false;
  }
}
function checkBootCrashFlag() {
  try {
    const flagPath = path.join(app.getPath("userData"), BOOT_IN_PROGRESS_FLAG_FILE);
    if (!fs.existsSync(flagPath)) {
      return false;
    }
    app.commandLine.appendSwitch("disable-gpu");
    app.commandLine.appendSwitch("disable-gpu-compositing");
    console.warn(
      "[CrashHandler] Boot crash detected (previous boot-in-progress flag found). Hardware acceleration disabled."
    );
    fs.unlinkSync(flagPath);
    return true;
  } catch {
    return false;
  }
}
function setBootInProgressFlag() {
  try {
    const flagPath = path.join(app.getPath("userData"), BOOT_IN_PROGRESS_FLAG_FILE);
    fs.writeFileSync(flagPath, JSON.stringify({ startedAt: Date.now() }), "utf-8");
  } catch {
  }
}
function clearBootInProgressFlag() {
  try {
    const flagPath = path.join(app.getPath("userData"), BOOT_IN_PROGRESS_FLAG_FILE);
    if (fs.existsSync(flagPath)) {
      fs.unlinkSync(flagPath);
    }
  } catch {
  }
}
const CRASH_SOURCE_EVENT_MAP = {
  "uncaughtException": RUM_EVENT_MAIN_UNCAUGHT_EXCEPTION,
  "unhandledRejection": RUM_EVENT_MAIN_UNHANDLED_REJECTION,
  "render-process-gone": RUM_EVENT_RENDERER_PROCESS_GONE,
  "child-process-gone": RUM_EVENT_CHILD_PROCESS_GONE
};
function createRumCrashReporter() {
  return {
    async upload(report) {
      try {
        const eventName = CRASH_SOURCE_EVENT_MAP[report.source] ?? report.source;
        let ext1;
        let ext2;
        switch (report.source) {
          case "uncaughtException":
          case "unhandledRejection":
            ext1 = report.reason;
            ext2 = report.stack ?? "";
            break;
          case "render-process-gone":
            ext1 = `reason:${report.reason}|exit:${report.exitCode ?? "unknown"}`;
            ext2 = `gpu_degraded:${report.gpuDegradationTriggered}|reload:${report.rendererReloadAttempted}`;
            break;
          case "child-process-gone":
            ext1 = `type:${report.processType}|reason:${report.reason}|exit:${report.exitCode ?? "unknown"}`;
            ext2 = `mem:${formatBytes(report.system.freeMemory)}/${formatBytes(report.system.totalMemory)}|uptime:${Math.floor(report.system.uptime)}s`;
            break;
          default:
            ext1 = report.reason;
            ext2 = report.stack ?? "";
        }
        rumReport({ name: eventName, ext1, ext2 });
        return true;
      } catch (err) {
        mainLogger.warn("[RumReporter] Failed to upload crash report:", err);
        return false;
      }
    }
  };
}
const { machineId } = pkg;
function readInstallChannel() {
  try {
    const channelPath = join$1(process.resourcesPath, "channel.json");
    const content = readFileSync$1(channelPath, "utf-8");
    const data = JSON.parse(content);
    return data.channel || void 0;
  } catch {
    mainLogger.warn("[InstallReport] 读取 channel.json 失败，使用默认渠道");
    return void 0;
  }
}
async function createInstallReporter() {
  let guid2 = "";
  try {
    guid2 = await machineId();
  } catch {
  }
  const channel = readInstallChannel();
  const env = "production";
  const baseUrl = getEnvUrls(env).beaconUrl;
  return new InstallReporter({
    stateDir: OPENCLAW_STATE_DIR,
    appVersion: app.getVersion(),
    guid: guid2,
    baseUrl,
    channel,
    logger: {
      info: (msg, ...args) => mainLogger.info(msg, ...args),
      warn: (msg, ...args) => mainLogger.warn(msg, ...args)
    }
  });
}
async function reportInstallEvent() {
  const reporter = await createInstallReporter();
  await reporter.checkAndReport();
}
async function reportUninstallEvent() {
  const reporter = await createInstallReporter();
  await reporter.reportUninstall();
}
let mainWindow = null;
app.name = TRAY_TOOLTIP;
const gotTheLock = app.requestSingleInstanceLock();
if (!gotTheLock) {
  app.whenReady().then(() => {
    dialog.showMessageBoxSync({
      type: "warning",
      title: "QClaw",
      message: "应用已在运行",
      detail: "检测到已有 QClaw 实例正在运行，请先退出已有实例后再启动。",
      buttons: ["确定"]
    });
    app.exit(0);
  });
}
checkBootCrashFlag();
checkGpuDegradation();
setBootInProgressFlag();
app.on("second-instance", () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }
    mainWindow.show();
    mainWindow.focus();
  }
});
function getUIPath() {
  return join(__dirname, "../renderer/index.html");
}
function createWindow() {
  mainWindow = new BrowserWindow({
    width: MAIN_WINDOW_DEFAULT_WIDTH,
    height: MAIN_WINDOW_DEFAULT_HEIGHT,
    minWidth: MAIN_WINDOW_MIN_WIDTH,
    minHeight: MAIN_WINDOW_MIN_HEIGHT,
    show: false,
    autoHideMenuBar: true,
    // macOS: 使用原生红绿灯控件，隐藏标题栏但保留交通灯按钮
    // Windows: 完全无边框，使用自定义窗口控制按钮
    ...process.platform === "darwin" ? { titleBarStyle: "hiddenInset", trafficLightPosition: { x: 12, y: 16 } } : { frame: false, thickFrame: true },
    backgroundColor: "#ffffff",
    icon: getAppIcon(),
    webPreferences: {
      preload: join(__dirname, "../preload/index.mjs"),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false
    }
  });
  mainWindow.on("ready-to-show", () => {
    mainWindow.show();
    clearBootInProgressFlag();
    getTrayManager().init(mainWindow);
    runBootSequence(mainWindow).then(() => {
      const mode = getProcessManager().getMode() ?? "unknown";
      rumReport({ name: RUM_EVENT_APP_LAUNCH, ext1: `mode:${mode}` });
    }).catch((error) => {
      mainLogger.error("Boot sequence failed:", error);
    });
  });
  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url);
    return { action: "deny" };
  });
  if (is.dev) {
    mainWindow.loadURL(process.env["ELECTRON_RENDERER_URL"] || UI_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(getUIPath());
  }
}
app.whenReady().then(() => {
  electronApp.setAppUserModelId(APP_USER_MODEL_ID);
  const crashHandler = getCrashHandler();
  crashHandler.initialize();
  crashHandler.setReporter(createRumCrashReporter());
  crashHandler.on("fatal-error", async ({ exitCode }) => {
    try {
      const processManager = getProcessManager();
      await processManager.shutdown();
    } catch {
    }
    process.exit(exitCode);
  });
  setupIpcHandlers();
  reportInstallEvent().catch((err) => {
    mainLogger.warn("Install report failed:", err);
  });
  app.on("browser-window-created", (_, window2) => {
    optimizer.watchWindowShortcuts(window2);
    window2.webContents.on("before-input-event", (_2, input) => {
      const isMacDevTools = input.meta && input.alt && input.key.toLowerCase() === "i";
      const isF12 = input.key === "F12";
      if (isF12 || isMacDevTools) {
        window2.webContents.toggleDevTools();
      }
      const isDebugPanel = (input.meta || input.control) && input.shift && input.key.toLowerCase() === "d";
      if (isDebugPanel) {
        window2.webContents.send("debug:togglePanel");
      }
    });
  });
  createWindow();
  app.on("activate", () => {
    if (mainWindow === null || mainWindow.isDestroyed()) {
      createWindow();
    } else {
      mainWindow.show();
      mainWindow.focus();
    }
  });
});
app.on("window-all-closed", () => {
});
app.on("before-quit", async (event) => {
  const trayManager = getTrayManager();
  if (!trayManager.isQuitting) {
    event.preventDefault();
    trayManager.quit();
    return;
  }
  const uptimeSeconds = Math.floor(process.uptime());
  rumReport({ name: RUM_EVENT_APP_QUIT, ext1: `uptime:${uptimeSeconds}s` });
  reportUninstallEvent().catch((err) => {
    mainLogger.warn("Uninstall report failed:", err);
  });
  const processManager = getProcessManager();
  const status = processManager.getStatus();
  if (status.status !== "stopped") {
    event.preventDefault();
    try {
      await processManager.shutdown();
    } catch (error) {
      mainLogger.error("Error during shutdown:", error);
    }
    trayManager.destroy();
    app.exit(0);
  } else {
    trayManager.destroy();
  }
});
