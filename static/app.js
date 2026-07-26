(() => {
  "use strict";

  const API_URL = "/api/sessions";
  const HISTORY_API_URL = "/api/sessions/history";
  const CHAT_API_URL = "/api/chat";
  const NEW_CHAT_API_URL = "/api/chat/new";
  const INTERRUPT_CHAT_API_URL = "/api/chat/interrupt";
  const MODELS_API_URL = "/api/chat/models";
  const POLL_MS = 2000;
  const BASE_SCENE_WIDTH = 1600;
  const BASE_SCENE_HEIGHT = 980;
  const STATION_COLUMNS = 4;
  const STATION_X = [170, 455, 740, 1025];
  const STATION_Y_START = 250;
  const STATION_Y_GAP = 230;
  const BACKGROUND_DESK_COUNT = 12;
  const MIN_ZOOM = 0.18;
  const MAX_ZOOM = 1.8;
  const DEFAULT_SCENE_SCALE = 1.2;
  const FIT_PADDING = 0;
  const ACTION_REFRESH_MS = 8000;
  const REACTION_DURATION_MS = 2400;
  const ROAM_STORAGE_KEY = "codex-pixel-office.roaming.v1";
  const BOSS_BEHAVIORS = [
    { action: "review", message: "让我看看大家的进度。" },
    { action: "wave", message: "辛苦啦，今天也要优雅地交付。" },
    { action: "clipboard", message: "先同步目标，再开始行动。" },
    { action: "encourage", message: "做得不错，记得起来喝口水。" },
    { action: "review", message: "入口保持顺畅，开会也会更从容。" },
    { action: "clipboard", message: "白板上的重点不错，下一步再写清楚。" },
    { action: "review", message: "让我在会议桌边想一想取舍。" },
  ];
  // Adjacent stops trace the meeting room's open foreground and right-side aisles.
  const BOSS_DESTINATIONS = [
    { x: 1235, y: 425 },
    { x: 1315, y: 445 },
    { x: 1405, y: 445 },
    { x: 1490, y: 435 },
    { x: 1540, y: 395 },
    { x: 1540, y: 320 },
    { x: 1540, y: 245 },
  ];
  const BOSS_IDLE_MIN_MS = 3600;
  const BOSS_IDLE_VARIANCE_MS = 4200;
  const BOSS_TRAVEL_MS_PER_PIXEL = 24;
  const BOSS_TRAVEL_MIN_MS = 1400;
  const BOSS_TRAVEL_MAX_MS = 4200;

  const ACTIONS = {
    typing: { label: "敲键盘", bubble: "⌨" },
    reading: { label: "阅读上下文", bubble: "▤" },
    reviewing: { label: "代码审查", bubble: "✓" },
    pacing: { label: "踱步思考", bubble: "…" },
    whiteboard: { label: "白板推演", bubble: "✎" },
    terminal: { label: "操作终端", bubble: ">_" },
    server: { label: "检查服务器", bubble: "MCP" },
    searching: { label: "搜索资料", bubble: "⌕" },
    coffee: { label: "冲杯咖啡", bubble: "☕" },
    stretch: { label: "伸展休息", bubble: "↟" },
    sync: { label: "同步讨论", bubble: "↔" },
    nap: { label: "工位小憩", bubble: "Zz" },
    wander: { label: "办公室巡视", bubble: "· · ·" },
    celebrate: { label: "庆祝完成", bubble: "★" },
  };

  const ACTION_POOLS = {
    working: ["typing", "typing", "typing", "typing", "reading", "reading", "reviewing", "reviewing", "terminal", "searching", "stretch"],
    thinking: ["reading", "reading", "reading", "reviewing", "reviewing", "pacing", "pacing", "whiteboard", "whiteboard", "searching", "sync"],
    tool: ["terminal", "terminal", "terminal", "terminal", "server", "server", "server", "searching", "searching", "reviewing", "sync"],
    waiting: ["coffee", "coffee", "coffee", "stretch", "stretch", "sync", "sync", "wander", "wander", "reading", "nap"],
    idle: ["nap", "nap", "nap", "wander", "wander", "wander", "coffee", "coffee", "stretch", "stretch", "reading", "celebrate"],
  };

  const ACTION_CLASS_NAMES = [
    "action-typing", "action-reading", "action-reviewing", "action-pacing", "action-whiteboard",
    "action-terminal", "action-server", "action-searching", "action-coffee", "action-stretch",
    "action-sync", "action-nap", "action-wander", "action-celebrate",
  ];
  const REACTIONS = {
    spawn: { label: "刚刚入场", bubble: "HI" },
    wake: { label: "重新开工", bubble: "!" },
    alert: { label: "收到提醒", bubble: "!" },
    complete: { label: "任务完成", bubble: "✓" },
  };
  const REACTION_CLASS_NAMES = ["reaction-spawn", "reaction-wake", "reaction-alert", "reaction-complete"];

  const STATUS = {
    working: { label: "编写中", detail: "正在编写", bubble: "", meter: 84, color: "#47b783" },
    thinking: { label: "思考中", detail: "正在思考", bubble: "…", meter: 62, color: "#8a72ce" },
    tool: { label: "调用工具", detail: "工具调用", bubble: "", meter: 100, color: "#ee8b47" },
    waiting: { label: "等待中", detail: "等待指令", bubble: "☕", meter: 36, color: "#4da8c7" },
    idle: { label: "空闲", detail: "暂时空闲", bubble: "Zz", meter: 14, color: "#9a95a8" },
  };

  const PALETTES = [
    ["#6d58a6", "#43366b", "#503a3b", "#e7ad7d"],
    ["#4d91a3", "#315d6d", "#3f3438", "#d99a6c"],
    ["#bf6959", "#79433f", "#3b3035", "#efbd8f"],
    ["#5a9a6d", "#376246", "#68463d", "#c9855f"],
    ["#cf8a45", "#82572f", "#332e34", "#e3a575"],
    ["#8c65a6", "#59416c", "#9a6848", "#f0c39a"],
    ["#4479b0", "#2d4f73", "#50342f", "#b97855"],
    ["#b55b7f", "#713b52", "#2e2930", "#e8ad80"],
    ["#6e8e45", "#465b2f", "#79503d", "#d89668"],
    ["#9b7456", "#634a39", "#37303a", "#f0bf92"],
    ["#5c75a6", "#3a4a6b", "#c18452", "#d98f64"],
    ["#aa6652", "#6d4337", "#4a3533", "#c9825d"],
  ];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const elements = {
    viewport: $("#officeViewport"),
    scene: $("#officeScene"),
    workstationLayer: $("#workstationsLayer"),
    agentsLayer: $("#agentsLayer"),
    workstationTemplate: $("#workstationTemplate"),
    agentTemplate: $("#agentTemplate"),
    emptyOffice: $("#emptyOffice"),
    detailPanel: $("#detailPanel"),
    detailPlaceholder: $("#detailPlaceholder"),
    sessionDetail: $("#sessionDetail"),
    liveIndicator: $("#liveIndicator"),
    connectionText: $("#connectionText"),
    updatedTime: $("#updatedTime"),
    zoomOutput: $("#zoomOutput"),
    dragHint: $("#dragHint"),
    chatSection: $("#sessionChat"),
    chatLog: $("#chatLog"),
    chatForm: $("#chatForm"),
    chatInput: $("#chatInput"),
    chatSend: $("#chatSend"),
    chatInterrupt: $("#chatInterrupt"),
    chatStatus: $("#chatStatus"),
    chatAnnouncer: $("#chatAnnouncer"),
    chatModelSelect: $("#chatModelSelect"),
    chatModelStatus: $("#chatModelStatus"),
    overtimeButton: $("#overtimeButton"),
    overtimeModal: $("#overtimeModal"),
    overtimeDialog: $("#overtimeDialog"),
    overtimeClose: $("#overtimeClose"),
    overtimeForm: $("#overtimeForm"),
    overtimeNewPanel: $("#overtimeNewPanel"),
    overtimeHistoryPanel: $("#overtimeHistoryPanel"),
    overtimeCwd: $("#overtimeCwd"),
    overtimeSearch: $("#overtimeSearch"),
    overtimeHistoryStatus: $("#overtimeHistoryStatus"),
    overtimeHistoryList: $("#overtimeHistoryList"),
    overtimeModel: $("#overtimeModel"),
    overtimeModelHint: $("#overtimeModelHint"),
    overtimeMessage: $("#overtimeMessage"),
    overtimeMessageLabel: $("#overtimeMessageLabel"),
    overtimeProgress: $("#overtimeProgress"),
    overtimeProgressTitle: $("#overtimeProgressTitle"),
    overtimeProgressState: $("#overtimeProgressState"),
    overtimeProgressLog: $("#overtimeProgressLog"),
    overtimeError: $("#overtimeError"),
    overtimeFootnote: $("#overtimeFootnote"),
    overtimeCancel: $("#overtimeCancel"),
    overtimeSubmit: $("#overtimeSubmit"),
    overtimeAnnouncer: $("#overtimeAnnouncer"),
    bossNpc: $("#bossNpc"),
    bossBubble: $("#bossBubble"),
    bossSprite: $("#bossSprite"),
  };

  const state = {
    sessions: [],
    filter: "all",
    selectedId: null,
    stations: loadStationAssignments(),
    agentNodes: new Map(),
    deskNodes: new Map(),
    pollTimer: 0,
    pollInFlight: false,
    pollRefreshRequested: false,
    behaviorTimer: 0,
    reactionTimer: 0,
    behaviors: new Map(),
    currentBehaviors: new Map(),
    travelTimers: new Map(),
    chats: new Map(),
    chatRenderFrame: 0,
    models: [],
    defaultModel: "",
    modelsLoading: true,
    modelsError: "",
    modelsVersion: 0,
    modelSelections: new Map(),
    bossTimer: 0,
    bossSpeechTimer: 0,
    bossStep: 0,
    bossRoamTimer: 0,
    bossRoamDeadline: 0,
    bossRoamRemaining: 0,
    bossDestination: 0,
    bossDirection: 1,
    bossTravel: null,
    viewportObserver: null,
    roamingEnabled: true,
    roamingPreferenceExplicit: false,
    hasLoaded: false,
    databaseAvailable: true,
    pendingSelectionId: null,
    overtime: {
      mode: "new",
      open: false,
      sending: false,
      history: [],
      historyLoading: false,
      historyError: "",
      historySelectedId: "",
      historyController: null,
      historyTimer: 0,
      controller: null,
      chat: null,
      sessionId: "",
      modelSelection: "",
      returnFocus: null,
    },
    sceneWidth: BASE_SCENE_WIDTH,
    sceneHeight: BASE_SCENE_HEIGHT,
    view: { x: 0, y: 0, scale: 1, fitted: false, userMoved: false },
    drag: null,
  };

  function hashString(value) {
    let hash = 2166136261;
    const text = String(value || "");
    for (let i = 0; i < text.length; i += 1) {
      hash ^= text.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function numericSeed(session) {
    const provided = Number(session.color_seed);
    return Number.isFinite(provided) ? Math.abs(Math.trunc(provided)) : hashString(session.id);
  }

  function normalizeStatus(value, activity) {
    const rawStatus = String(value || "").toLowerCase();
    if (/tool|terminal|shell|command|exec|mcp/.test(rawStatus)) return "tool";
    if (/think|reason|plan|analy/.test(rawStatus)) return "thinking";
    if (/wait|approval|input|block/.test(rawStatus)) return "waiting";
    if (/work|active|writ|cod|run|edit/.test(rawStatus)) return "working";
    if (/idle|done|complete|sleep/.test(rawStatus)) return "idle";
    const text = String(activity || "").toLowerCase();
    if (/tool|terminal|shell|command|exec|mcp|browser|search/.test(text)) return "tool";
    if (/think|reason|plan|analy|思考|推理|规划/.test(text)) return "thinking";
    if (/wait|approval|input|block|等待|确认/.test(text)) return "waiting";
    if (/work|active|writ|cod|run|edit|工作|编写/.test(text)) return "working";
    return "idle";
  }

  function normalizeSession(raw, index) {
    const id = String(raw && (raw.id || raw.short_id) || `unknown-${index}`);
    const status = normalizeStatus(raw && raw.status, raw && raw.activity);
    return {
      id,
      title: String(raw && raw.title || `Codex 会话 ${index + 1}`),
      cwd: String(raw && raw.cwd || ""),
      model: String(raw && raw.model || "未知模型"),
      source: String(raw && raw.source || "Codex"),
      updated_at: raw && raw.updated_at ? String(raw.updated_at) : "",
      age_seconds: Math.max(0, Number(raw && raw.age_seconds) || 0),
      status,
      activity: String(raw && raw.activity || STATUS[status].detail),
      is_subagent: Boolean(raw && raw.is_subagent),
      parent_id: raw && raw.parent_id ? String(raw.parent_id) : "",
      color_seed: raw && raw.color_seed,
      short_id: String(raw && raw.short_id || id.slice(0, 8)),
      agent_nickname: String(raw && raw.agent_nickname || ""),
      agent_role: String(raw && raw.agent_role || ""),
    };
  }

  function loadStationAssignments() {
    try {
      const parsed = JSON.parse(localStorage.getItem("codex-pixel-office.stations.v1") || "{}");
      const map = new Map();
      Object.entries(parsed).forEach(([id, slot]) => {
        if (Number.isInteger(slot) && slot >= 0) map.set(id, slot);
      });
      return map;
    } catch (_) {
      return new Map();
    }
  }

  function saveStationAssignments() {
    try {
      const currentIds = new Set(state.sessions.map((session) => session.id));
      const output = {};
      state.stations.forEach((slot, id) => {
        if (currentIds.has(id)) output[id] = slot;
      });
      localStorage.setItem("codex-pixel-office.stations.v1", JSON.stringify(output));
    } catch (_) {
      // Storage is optional; the in-memory map still keeps desks stable.
    }
  }

  function ensureStationAssignments(sessions) {
    const sessionIds = new Set(sessions.map((session) => session.id));
    const hadDepartures = Array.from(state.stations.keys()).some((id) => !sessionIds.has(id));
    const used = new Set();

    sessions.forEach((session) => {
      const slot = state.stations.get(session.id);
      if (!Number.isInteger(slot) || slot < 0 || used.has(slot)) {
        state.stations.delete(session.id);
      } else {
        used.add(slot);
      }
    });

    const ordered = [...sessions].sort((a, b) => {
      if (a.is_subagent !== b.is_subagent) return Number(a.is_subagent) - Number(b.is_subagent);
      return a.id.localeCompare(b.id);
    });

    ordered.forEach((session) => {
      if (state.stations.has(session.id)) return;
      let candidates = [];
      if (session.parent_id && state.stations.has(session.parent_id)) {
        const parentSlot = state.stations.get(session.parent_id);
        candidates = [parentSlot + 1, parentSlot - 1, parentSlot + STATION_COLUMNS, parentSlot - STATION_COLUMNS];
      }
      let slot = candidates.find((candidate) => candidate >= 0 && !used.has(candidate));
      if (!Number.isInteger(slot)) {
        slot = 0;
        while (used.has(slot)) slot += 1;
      }
      state.stations.set(session.id, slot);
      used.add(slot);
    });

    Array.from(state.stations.keys()).forEach((id) => {
      if (!sessionIds.has(id)) state.stations.delete(id);
    });
    if (hadDepartures) compactSparseAssignments(sessions);
    saveStationAssignments();
  }

  function compactSparseAssignments(sessions) {
    if (!sessions.length) return;
    const entries = sessions
      .map((session) => [session.id, state.stations.get(session.id)])
      .filter((entry) => Number.isInteger(entry[1]))
      .sort((a, b) => a[1] - b[1]);
    const maxSlot = entries[entries.length - 1][1];
    const sparseBeyondOffice = sessions.length <= BACKGROUND_DESK_COUNT && maxSlot >= BACKGROUND_DESK_COUNT;
    const hasLargeGap = maxSlot >= sessions.length + STATION_COLUMNS;
    if (!sparseBeyondOffice && !hasLargeGap) return;

    const used = new Set(entries.map((entry) => entry[1]));
    let lowestFree = 0;
    while (used.has(lowestFree)) lowestFree += 1;
    for (let index = entries.length - 1; index >= 0; index -= 1) {
      const [id, slot] = entries[index];
      if (slot <= lowestFree) break;
      state.stations.set(id, lowestFree);
      used.delete(slot);
      used.add(lowestFree);
      while (used.has(lowestFree)) lowestFree += 1;
    }
  }

  function stationPosition(slot) {
    const column = slot % STATION_COLUMNS;
    const row = Math.floor(slot / STATION_COLUMNS);
    return { x: STATION_X[column], y: STATION_Y_START + row * STATION_Y_GAP, row };
  }

  function actionBucket(now = Date.now()) {
    return Math.floor(now / ACTION_REFRESH_MS);
  }

  function behaviorEntropy(session, bucket, salt) {
    return hashString([
      numericSeed(session),
      session.id,
      session.status,
      session.activity,
      session.is_subagent ? "subagent" : "main",
      session.parent_id,
      bucket,
      salt,
    ].join("|"));
  }

  function appendWeighted(target, action, weight) {
    for (let index = 0; index < weight; index += 1) target.push(action);
  }

  function activityActionHints(session) {
    const text = String(session.activity || "").toLowerCase();
    const hints = [];
    if (/done|complete|success|passed|finished|完成|成功|通过/.test(text)) appendWeighted(hints, "celebrate", 8);
    if (/terminal|shell|command|exec|命令|终端/.test(text)) appendWeighted(hints, "terminal", 6);
    if (/server|docker|mcp|ssh|deploy|network|服务|容器|网络/.test(text)) appendWeighted(hints, "server", 6);
    if (/search|browser|web|find|lookup|检索|搜索|浏览/.test(text)) appendWeighted(hints, "searching", 6);
    if (/review|test|check|diff|verify|audit|审查|测试|检查|验证/.test(text)) appendWeighted(hints, "reviewing", 5);
    if (/read|docs?|context|file|open|阅读|文档|上下文/.test(text)) appendWeighted(hints, "reading", 5);
    if (/plan|design|architect|whiteboard|规划|设计|架构/.test(text)) appendWeighted(hints, "whiteboard", 5);
    if (/sync|delegate|agent|collab|parent|同步|协作|代理/.test(text)) appendWeighted(hints, "sync", 5);
    if (/write|edit|code|patch|implement|编写|编辑|代码|实现/.test(text)) appendWeighted(hints, "typing", 6);
    return hints;
  }

  function chooseAction(session, record, now) {
    const bucket = actionBucket(now);
    if (record.action && record.actionBucket === bucket) return record.action;
    if (record.forcedAction && record.forcedUntil > now) {
      record.action = record.forcedAction;
      record.actionBucket = bucket;
      return record.action;
    }

    const candidates = [...(ACTION_POOLS[session.status] || ACTION_POOLS.idle), ...activityActionHints(session)];
    if (session.is_subagent) {
      candidates.push("sync", "reviewing");
      if (session.parent_id) candidates.push("sync", "sync");
    }
    const choice = candidates[behaviorEntropy(session, bucket, "action") % candidates.length] || "wander";
    record.action = choice;
    record.actionBucket = bucket;
    return choice;
  }

  function hasAlertSignal(session) {
    return /error|fail|blocked|approval|warning|denied|错误|失败|阻塞|批准|警告|拒绝/i.test(session.activity || "");
  }

  function triggerReaction(record, reaction, now) {
    record.reaction = reaction;
    record.reactionUntil = now + REACTION_DURATION_MS;
  }

  function scheduleReactionRefresh(now = Date.now()) {
    window.clearTimeout(state.reactionTimer);
    let nextExpiry = Infinity;
    state.behaviors.forEach((record) => {
      if (record.reaction && record.reactionUntil > now) nextExpiry = Math.min(nextExpiry, record.reactionUntil);
    });
    if (!Number.isFinite(nextExpiry)) {
      state.reactionTimer = 0;
      return;
    }
    state.reactionTimer = window.setTimeout(() => {
      state.reactionTimer = 0;
      refreshBehaviors();
      scheduleReactionRefresh();
    }, Math.max(30, nextExpiry - now + 30));
  }

  function syncBehaviorRecords(sessions, now = Date.now()) {
    const activeIds = new Set(sessions.map((session) => session.id));
    sessions.forEach((session) => {
      let record = state.behaviors.get(session.id);
      const alerting = hasAlertSignal(session);
      if (!record) {
        record = {
          status: session.status,
          alerting,
          action: "",
          actionBucket: -1,
          forcedAction: "",
          forcedUntil: 0,
          reaction: "",
          reactionUntil: 0,
        };
        triggerReaction(record, "spawn", now);
        state.behaviors.set(session.id, record);
        return;
      }

      if (record.status !== session.status) {
        const wasResting = record.status === "idle" || record.status === "waiting";
        const isActive = session.status === "working" || session.status === "thinking" || session.status === "tool";
        if (wasResting && isActive) triggerReaction(record, "wake", now);
        else if (session.status === "idle") {
          triggerReaction(record, "complete", now);
          record.forcedAction = "celebrate";
          record.forcedUntil = now + ACTION_REFRESH_MS * 2;
        } else {
          triggerReaction(record, "alert", now);
        }
        record.actionBucket = -1;
      } else if (!record.alerting && alerting) {
        triggerReaction(record, "alert", now);
      }
      record.status = session.status;
      record.alerting = alerting;
      if (record.forcedUntil <= now) record.forcedAction = "";
    });

    Array.from(state.behaviors.keys()).forEach((id) => {
      if (!activeIds.has(id)) state.behaviors.delete(id);
    });
    scheduleReactionRefresh(now);
  }

  function currentReaction(record, now) {
    if (!record || !record.reaction || record.reactionUntil <= now) return "";
    return record.reaction;
  }

  function preferredDestination(session, action, bucket) {
    if (!state.roamingEnabled || session.status === "working" || session.status === "tool") return "desk";
    if (action === "coffee") return "coffee";
    if (action === "nap") return "lounge";
    if (action === "whiteboard") return "whiteboard";
    if (action === "server") return "server";
    if (action === "sync") {
      if (session.parent_id && state.stations.has(session.parent_id)) return `parent:${session.parent_id}`;
      return "meeting";
    }
    if (action === "pacing" || action === "wander") return "wander";

    const roll = behaviorEntropy(session, bucket, "destination") % 100;
    if (session.is_subagent && session.parent_id && state.stations.has(session.parent_id)
      && (session.status === "thinking" || session.status === "waiting") && roll < 45) {
      return `parent:${session.parent_id}`;
    }
    if (session.status === "thinking" && roll < 32) return "whiteboard";
    if (session.status === "waiting" && roll < 58) return roll < 34 ? "coffee" : "meeting";
    if (session.status === "idle" && roll < 62) return roll < 28 ? "lounge" : "wander";
    if (action === "stretch" && (session.status === "waiting" || session.status === "idle")) return "lounge";
    return "desk";
  }

  function clampAgentPoint(point) {
    return {
      x: Math.max(76, Math.min(state.sceneWidth - 76, point.x)),
      y: Math.max(145, Math.min(state.sceneHeight - 72, point.y)),
    };
  }

  function overflowSlot(slots, index) {
    const base = slots[index % slots.length];
    const overflow = Math.floor(index / slots.length);
    if (!overflow) return base;
    const direction = overflow % 2 ? 1 : -1;
    const distance = 14 * Math.ceil(overflow / 2);
    return { x: base.x + direction * distance, y: base.y + overflow * 9 };
  }

  function destinationSlots(destination) {
    const bottom = state.sceneHeight;
    if (destination === "coffee") {
      return [
        { x: 1260, y: 575 }, { x: 1360, y: 575 }, { x: 1460, y: 575 },
        { x: 1260, y: 650 }, { x: 1360, y: 650 }, { x: 1460, y: 650 },
      ];
    }
    if (destination === "lounge") {
      return [
        { x: 1250, y: 610 }, { x: 1340, y: 610 }, { x: 1430, y: 610 },
        { x: 1295, y: 685 }, { x: 1385, y: 685 }, { x: 1475, y: 685 },
      ];
    }
    if (destination === "whiteboard") {
      return [
        { x: 1375, y: 285 }, { x: 1300, y: 305 }, { x: 1450, y: 305 },
        { x: 1250, y: 375 }, { x: 1500, y: 375 },
      ];
    }
    if (destination === "meeting") {
      return [
        { x: 1280, y: 350 }, { x: 1380, y: 350 }, { x: 1480, y: 350 },
        { x: 1360, y: 445 }, { x: 1460, y: 445 },
      ];
    }
    if (destination === "server") {
      return [
        { x: 1260, y: 805 }, { x: 1360, y: 805 }, { x: 1460, y: 805 },
        { x: 1260, y: 885 }, { x: 1360, y: 885 }, { x: 1460, y: 885 },
      ];
    }
    return [
      { x: 1125, y: 180 }, { x: 1135, y: 405 }, { x: 1125, y: 625 },
      { x: 900, y: bottom - 90 }, { x: 650, y: bottom - 90 }, { x: 400, y: bottom - 90 },
      { x: 860, y: 155 }, { x: 585, y: 155 }, { x: 315, y: 155 },
    ];
  }

  function destinationPoint(destinationKey, slotIndex) {
    if (destinationKey.startsWith("parent:")) {
      const parentId = destinationKey.slice(7);
      const parentSlot = state.stations.get(parentId);
      const parent = stationPosition(parentSlot);
      const offsets = [
        { x: 92, y: 35 }, { x: -92, y: 35 }, { x: 92, y: 112 }, { x: -92, y: 112 },
        { x: 0, y: 132 }, { x: 0, y: -68 }, { x: 132, y: 78 }, { x: -132, y: 78 },
      ];
      const offset = overflowSlot(offsets, slotIndex);
      return clampAgentPoint({ x: parent.x + offset.x, y: parent.y + 54 + offset.y });
    }
    return clampAgentPoint(overflowSlot(destinationSlots(destinationKey), slotIndex));
  }

  function destinationCapacity(destinationKey) {
    if (destinationKey.startsWith("parent:")) return { key: destinationKey, limit: 2 };
    if (destinationKey === "coffee" || destinationKey === "lounge") return { key: "break-zone", limit: 3 };
    if (destinationKey === "whiteboard" || destinationKey === "meeting") return { key: "collaboration-zone", limit: 4 };
    if (destinationKey === "server") return { key: "server-zone", limit: 2 };
    return { key: "wander-zone", limit: 4 };
  }

  function computeBehaviorLayout(now = Date.now()) {
    const bucket = actionBucket(now);
    const layout = new Map();
    const destinationGroups = new Map();
    const roamCandidates = [];
    const roamLimit = state.roamingEnabled
      ? Math.max(2, Math.min(10, Math.ceil(state.sessions.length * 0.4)))
      : 0;

    state.sessions.forEach((session) => {
      const record = state.behaviors.get(session.id);
      if (!record) return;
      const slot = state.stations.get(session.id);
      const station = stationPosition(slot);
      const action = chooseAction(session, record, now);
      const destinationKey = preferredDestination(session, action, bucket);
      const behavior = {
        action,
        reaction: currentReaction(record, now),
        destination: "desk",
        destinationSlot: -1,
        homeX: station.x,
        homeY: station.y + 54,
        x: station.x,
        y: station.y + 54,
        isRoaming: false,
      };
      layout.set(session.id, behavior);
      if (destinationKey !== "desk") {
        roamCandidates.push({
          session,
          behavior,
          destinationKey,
          priority: behaviorEntropy(session, bucket, `roam-priority:${destinationKey}`),
        });
      }
    });

    roamCandidates.sort((left, right) => left.priority - right.priority || left.session.id.localeCompare(right.session.id));
    const capacityCounts = new Map();
    let roamingCount = 0;
    roamCandidates.forEach((candidate) => {
      if (roamingCount >= roamLimit) return;
      const capacity = destinationCapacity(candidate.destinationKey);
      const used = capacityCounts.get(capacity.key) || 0;
      if (used >= capacity.limit) return;
      capacityCounts.set(capacity.key, used + 1);
      roamingCount += 1;
      candidate.behavior.destination = candidate.destinationKey.split(":")[0];
      candidate.behavior.isRoaming = true;
      if (!destinationGroups.has(candidate.destinationKey)) destinationGroups.set(candidate.destinationKey, []);
      destinationGroups.get(candidate.destinationKey).push(candidate);
    });

    destinationGroups.forEach((items, destinationKey) => {
      items.sort((left, right) => {
        const leftOrder = hashString(`${destinationKey}|${numericSeed(left.session)}|${left.session.id}`);
        const rightOrder = hashString(`${destinationKey}|${numericSeed(right.session)}|${right.session.id}`);
        return leftOrder - rightOrder || left.session.id.localeCompare(right.session.id);
      });
      items.forEach((item, index) => {
        const point = destinationPoint(destinationKey, index);
        item.behavior.x = point.x;
        item.behavior.y = point.y;
        item.behavior.destinationSlot = index;
      });
    });
    return layout;
  }

  function behaviorLabel(behavior) {
    if (!behavior) return "—";
    const actionLabel = ACTIONS[behavior.action] ? ACTIONS[behavior.action].label : behavior.action;
    const reactionLabel = behavior.reaction && REACTIONS[behavior.reaction] ? REACTIONS[behavior.reaction].label : "";
    return reactionLabel ? `${reactionLabel} · ${actionLabel}` : actionLabel;
  }

  function updateSceneSize() {
    const maxSlot = state.sessions.reduce((max, session) => Math.max(max, state.stations.get(session.id) || 0), 0);
    const lastPosition = stationPosition(maxSlot);
    const nextHeight = Math.max(BASE_SCENE_HEIGHT, lastPosition.y + 190);
    const changed = nextHeight !== state.sceneHeight;
    state.sceneHeight = nextHeight;
    elements.scene.style.height = `${nextHeight}px`;
    elements.scene.style.setProperty("--scene-h", `${nextHeight}px`);
    if (changed && !state.view.userMoved) requestAnimationFrame(fitView);
  }

  function isVisible(session) {
    if (state.filter === "main") return !session.is_subagent;
    if (state.filter === "subagent") return session.is_subagent;
    return true;
  }

  function displayName(session) {
    if (session.is_subagent && session.agent_nickname.trim()) return session.agent_nickname.trim();
    const title = session.title.trim();
    if (title) return title;
    if (session.cwd) return session.cwd.split(/[\\/]/).filter(Boolean).pop() || session.short_id;
    return session.short_id;
  }

  function paletteFor(session) {
    return PALETTES[numericSeed(session) % PALETTES.length];
  }

  function createDeskNode(session) {
    const node = elements.workstationTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.sessionId = session.id;
    elements.workstationLayer.appendChild(node);
    state.deskNodes.set(session.id, node);
    return node;
  }

  function createAgentNode(session) {
    const node = elements.agentTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.sessionId = session.id;
    node.addEventListener("click", () => selectSession(session.id));
    const sprite = $(".worker-sprite", node);
    sprite.addEventListener("load", () => {
      sprite.classList.remove("is-missing");
      node.classList.add("has-sprite");
    });
    sprite.addEventListener("error", () => {
      sprite.classList.add("is-missing");
      node.classList.remove("has-sprite");
    });
    elements.agentsLayer.appendChild(node);
    state.agentNodes.set(session.id, node);
    return node;
  }

  function clearAgentTravel(sessionId, agent) {
    if (state.travelTimers.has(sessionId)) {
      window.clearTimeout(state.travelTimers.get(sessionId));
      state.travelTimers.delete(sessionId);
    }
    if (agent) agent.classList.remove("is-traveling");
  }

  function startAgentTravel(sessionId, agent, duration) {
    clearAgentTravel(sessionId, agent);
    void agent.offsetWidth;
    agent.classList.add("is-traveling");
    const timer = window.setTimeout(() => {
      if (state.travelTimers.get(sessionId) !== timer) return;
      if (state.agentNodes.get(sessionId) === agent) agent.classList.remove("is-traveling");
      state.travelTimers.delete(sessionId);
    }, duration);
    state.travelTimers.set(sessionId, timer);
  }

  function travelDurationFor(session, fromX, fromY, toX, toY) {
    const seed = numericSeed(session);
    const speed = 105 + hashString(`${seed}|travel-speed`) % 21;
    const minimum = 1800 + hashString(`${seed}|travel-minimum`) % 401;
    const maximum = 6200 + hashString(`${seed}|travel-maximum`) % 801;
    if (![fromX, fromY, toX, toY].every(Number.isFinite)) return minimum;
    const distance = Math.hypot(toX - fromX, toY - fromY);
    return Math.round(Math.max(minimum, Math.min(maximum, distance / speed * 1000)));
  }

  function freezeAgentAtRenderedPosition(agent) {
    if (typeof window.getComputedStyle !== "function") return null;
    const computed = window.getComputedStyle(agent);
    const x = Number.parseFloat(computed.left);
    const y = Number.parseFloat(computed.top);
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    const inlineTransition = agent.style.transition;
    agent.style.transition = "none";
    agent.style.left = `${x}px`;
    agent.style.top = `${y}px`;
    agent.style.zIndex = String(20 + Math.floor(y / 115) * 2);
    void agent.offsetWidth;
    if (inlineTransition) agent.style.transition = inlineTransition;
    else agent.style.removeProperty("transition");
    return { x, y };
  }

  function setInitialAgentPosition(agent, behavior) {
    const inlineTransition = agent.style.transition;
    agent.style.transition = "none";
    agent.style.left = `${behavior.x}px`;
    agent.style.top = `${behavior.y}px`;
    agent.style.zIndex = String(20 + Math.floor(behavior.y / 115) * 2);
    void agent.offsetWidth;
    if (inlineTransition) agent.style.transition = inlineTransition;
    else agent.style.removeProperty("transition");
    agent.dataset.positionReady = "true";
  }

  function applyAgentBehavior(session, agent, behavior) {
    if (!behavior) return;
    const actionInfo = ACTIONS[behavior.action] || ACTIONS.wander;
    const reactionInfo = behavior.reaction ? REACTIONS[behavior.reaction] : null;
    const statusInfo = STATUS[session.status];
    const seed = numericSeed(session);
    const actionDelay = -(seed % 1800);
    const actionDuration = 900 + seed % 850;
    const hadPosition = agent.dataset.positionReady === "true";
    let previousLeft = Number.parseFloat(agent.style.left);
    let previousTop = Number.parseFloat(agent.style.top);
    let interruptedTravel = false;
    const targetChanged = hadPosition
      && Number.isFinite(previousLeft)
      && Number.isFinite(previousTop)
      && (Math.abs(previousLeft - behavior.x) > 1 || Math.abs(previousTop - behavior.y) > 1);
    if (targetChanged && state.travelTimers.has(session.id) && agent.classList.contains("is-traveling")) {
      const renderedPosition = freezeAgentAtRenderedPosition(agent);
      if (renderedPosition) {
        previousLeft = renderedPosition.x;
        previousTop = renderedPosition.y;
        interruptedTravel = true;
      }
    }
    const roamDuration = travelDurationFor(session, previousLeft, previousTop, behavior.x, behavior.y);
    const positionChanged = hadPosition
      && Number.isFinite(previousLeft)
      && Number.isFinite(previousTop)
      && (Math.abs(previousLeft - behavior.x) > 1 || Math.abs(previousTop - behavior.y) > 1);

    agent.dataset.action = behavior.action;
    agent.dataset.destination = behavior.destination;
    agent.dataset.destinationSlot = String(behavior.destinationSlot);
    agent.classList.remove(...ACTION_CLASS_NAMES, ...REACTION_CLASS_NAMES);
    agent.classList.add(`action-${behavior.action}`);
    if (behavior.reaction) agent.classList.add(`reaction-${behavior.reaction}`);
    agent.style.setProperty("--home-x", `${behavior.homeX}px`);
    agent.style.setProperty("--home-y", `${behavior.homeY}px`);
    agent.style.setProperty("--roam-x", `${behavior.x}px`);
    agent.style.setProperty("--roam-y", `${behavior.y}px`);
    agent.style.setProperty("--action-delay", `${actionDelay}ms`);
    agent.style.setProperty("--action-duration", `${actionDuration}ms`);
    agent.style.setProperty("--roam-duration", `${roamDuration}ms`);

    if (!hadPosition) {
      clearAgentTravel(session.id, agent);
      agent.classList.toggle("is-roaming", behavior.isRoaming);
      setInitialAgentPosition(agent, behavior);
    } else {
      if (positionChanged) startAgentTravel(session.id, agent, roamDuration);
      else if (interruptedTravel) clearAgentTravel(session.id, agent);
      else if (!state.travelTimers.has(session.id)) agent.classList.remove("is-traveling");
      agent.classList.toggle("is-roaming", behavior.isRoaming);
      agent.style.left = `${behavior.x}px`;
      agent.style.top = `${behavior.y}px`;
      agent.style.zIndex = String(20 + Math.floor(behavior.y / 115) * 2);
    }

    const status = $(".agent-state", agent);
    const bubble = $(".agent-bubble", agent);
    status.textContent = actionInfo.label;
    bubble.textContent = reactionInfo ? reactionInfo.bubble : (actionInfo.bubble || statusInfo.bubble);
    const roleText = session.is_subagent && session.agent_role ? `，角色 ${session.agent_role}` : "";
    agent.setAttribute("aria-label", `${displayName(session)}${roleText}，${statusInfo.label}，当前动作 ${behaviorLabel(behavior)}，点击查看详情`);
    agent.title = [displayName(session), session.agent_role, session.title, statusInfo.label, behaviorLabel(behavior)].filter(Boolean).join(" · ");
  }

  function updateSessionNode(session, behavior) {
    const slot = state.stations.get(session.id);
    const position = stationPosition(slot);
    const visible = isVisible(session);
    const palette = paletteFor(session);
    const desk = state.deskNodes.get(session.id) || createDeskNode(session);
    const agent = state.agentNodes.get(session.id) || createAgentNode(session);

    desk.style.left = `${position.x}px`;
    desk.style.top = `${position.y}px`;
    desk.dataset.slotIndex = String(slot);
    desk.style.display = visible ? "block" : "none";
    const workstationRole = session.is_subagent ? "is-subagent" : "is-main";
    desk.className = `workstation status-${session.status} ${workstationRole}`;
    desk.dataset.role = session.is_subagent ? "subagent" : "main";
    if (slot < BACKGROUND_DESK_COUNT) desk.classList.add("uses-background-desk");

    agent.style.display = visible ? "block" : "none";
    agent.style.setProperty("--agent-color", palette[0]);
    agent.style.setProperty("--agent-color-dark", palette[1]);
    agent.style.setProperty("--agent-hair", palette[2]);
    agent.style.setProperty("--agent-skin", palette[3]);
    agent.classList.remove("status-working", "status-thinking", "status-tool", "status-waiting", "status-idle", "is-subagent", "is-selected");
    agent.classList.add(`status-${session.status}`);
    if (session.is_subagent) agent.classList.add("is-subagent");
    if (state.selectedId === session.id) agent.classList.add("is-selected");

    const name = $(".agent-name", agent);
    name.textContent = displayName(session);
    applyAgentBehavior(session, agent, behavior);

    const spriteIndex = String(numericSeed(session) % 12).padStart(2, "0");
    const sprite = $(".worker-sprite", agent);
    const src = `/assets/worker-${spriteIndex}.png`;
    if (sprite.getAttribute("src") !== src) {
      agent.classList.remove("has-sprite");
      sprite.classList.remove("is-missing");
      sprite.src = src;
    }
  }

  function removeStaleNodes(activeIds) {
    state.agentNodes.forEach((node, id) => {
      if (activeIds.has(id)) return;
      clearAgentTravel(id, node);
      node.remove();
      state.agentNodes.delete(id);
    });
    state.deskNodes.forEach((node, id) => {
      if (activeIds.has(id)) return;
      node.remove();
      state.deskNodes.delete(id);
    });
    Array.from(state.travelTimers.keys()).forEach((id) => {
      if (!activeIds.has(id) || !state.agentNodes.has(id)) clearAgentTravel(id, state.agentNodes.get(id));
    });
  }

  function updateCounts() {
    const visible = state.sessions.filter(isVisible);
    const counts = { working: 0, thinking: 0, tool: 0, waiting: 0, idle: 0 };
    visible.forEach((session) => { counts[session.status] += 1; });
    $("#statTotal").textContent = String(visible.length);
    Object.keys(counts).forEach((status) => {
      const target = $(`#stat${status[0].toUpperCase()}${status.slice(1)}`);
      if (target) target.textContent = String(counts[status]);
    });
    $("#filterAllCount").textContent = String(state.sessions.length);
    $("#filterMainCount").textContent = String(state.sessions.filter((session) => !session.is_subagent).length);
    $("#filterSubCount").textContent = String(state.sessions.filter((session) => session.is_subagent).length);
  }

  function updateEmptyState(databaseAvailable = true) {
    const visible = state.sessions.filter(isVisible);
    elements.emptyOffice.hidden = visible.length > 0;
    if (visible.length > 0) return;
    const heading = $("h2", elements.emptyOffice);
    const copy = $(".empty-copy > p", elements.emptyOffice);
    const kicker = $(".empty-kicker", elements.emptyOffice);
    if (!databaseAvailable) {
      kicker.textContent = "SESSION DATABASE OFFLINE";
      heading.textContent = "暂时读不到 Codex 会话";
      copy.textContent = "办公室本身已经就绪，但本机会话数据库当前不可用。恢复连接后，像素同事会自动入场。";
    } else if (state.sessions.length > 0) {
      kicker.textContent = "NO MATCHING WORKERS";
      heading.textContent = "这个筛选里还没有同事";
      copy.textContent = "换一个会话类型看看；现有同事仍在原来的固定工位工作。";
    } else {
      kicker.textContent = "OFFICE IS READY";
      heading.textContent = "等第一位 Codex 同事来上班";
      copy.textContent = "新建或继续一个 Codex 会话，它会自动出现在工位上。页面每 2 秒刷新一次，无需手动操作。";
    }
  }

  function renderSessions(databaseAvailable = state.databaseAvailable) {
    state.databaseAvailable = databaseAvailable;
    ensureStationAssignments(state.sessions);
    updateSceneSize();
    const now = Date.now();
    syncBehaviorRecords(state.sessions, now);
    state.currentBehaviors = computeBehaviorLayout(now);
    const activeIds = new Set(state.sessions.map((session) => session.id));
    state.sessions.forEach((session) => updateSessionNode(session, state.currentBehaviors.get(session.id)));
    removeStaleNodes(activeIds);
    updateCounts();
    updateEmptyState(databaseAvailable);

    if (state.selectedId) {
      const selected = state.sessions.find((session) => session.id === state.selectedId);
      if (selected && isVisible(selected)) renderDetails(selected);
      else clearSelection();
    }
  }

  function refreshBehaviors() {
    const now = Date.now();
    state.currentBehaviors = computeBehaviorLayout(now);
    state.sessions.forEach((session) => {
      const agent = state.agentNodes.get(session.id);
      if (agent) applyAgentBehavior(session, agent, state.currentBehaviors.get(session.id));
    });
    if (state.selectedId) {
      const selected = state.sessions.find((session) => session.id === state.selectedId);
      if (selected && isVisible(selected)) renderDetails(selected);
    }
  }

  function startBehaviorClock() {
    window.clearTimeout(state.behaviorTimer);
    const delay = ACTION_REFRESH_MS - Date.now() % ACTION_REFRESH_MS;
    state.behaviorTimer = window.setTimeout(() => {
      refreshBehaviors();
      state.behaviorTimer = window.setInterval(refreshBehaviors, ACTION_REFRESH_MS);
    }, delay);
  }

  function showBossMessage(message, duration = 2800) {
    if (!elements.bossNpc || !elements.bossBubble) return;
    elements.bossBubble.textContent = message;
    elements.bossNpc.classList.add("is-speaking");
    window.clearTimeout(state.bossSpeechTimer);
    state.bossSpeechTimer = window.setTimeout(() => {
      elements.bossNpc.classList.remove("is-speaking");
      state.bossSpeechTimer = 0;
    }, duration);
  }

  function renderBossBehavior(speak = false) {
    if (!elements.bossNpc) return;
    const behavior = BOSS_BEHAVIORS[state.bossStep % BOSS_BEHAVIORS.length];
    elements.bossNpc.dataset.action = behavior.action;
    elements.bossNpc.setAttribute("aria-label", `老板正在会议厅巡视：${behavior.message} 点击和他打招呼`);
    if (speak) showBossMessage(behavior.message);
    else if (elements.bossBubble) elements.bossBubble.textContent = behavior.message;
  }

  function scheduleBossBehavior() {
    window.clearTimeout(state.bossTimer);
    state.bossTimer = 0;
    if (document.hidden || !elements.bossNpc) return;
    const delay = 9000 + state.bossStep % 4 * 1100;
    state.bossTimer = window.setTimeout(() => {
      state.bossStep = (state.bossStep + 1) % BOSS_BEHAVIORS.length;
      renderBossBehavior(true);
      scheduleBossBehavior();
    }, delay);
  }

  function bossPrefersReducedMotion() {
    return typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function readBossPosition() {
    const fallback = BOSS_DESTINATIONS[state.bossDestination] || BOSS_DESTINATIONS[0];
    if (!elements.bossNpc) return fallback;
    const computed = window.getComputedStyle(elements.bossNpc);
    const x = Number.parseFloat(computed.left);
    const y = Number.parseFloat(computed.top);
    return {
      x: Number.isFinite(x) ? x : fallback.x,
      y: Number.isFinite(y) ? y : fallback.y,
    };
  }

  function nearestBossDestination(position) {
    let nearestIndex = 0;
    let nearestDistance = Number.POSITIVE_INFINITY;
    BOSS_DESTINATIONS.forEach((destination, index) => {
      const distance = Math.hypot(destination.x - position.x, destination.y - position.y);
      if (distance < nearestDistance) {
        nearestIndex = index;
        nearestDistance = distance;
      }
    });
    return nearestIndex;
  }

  function bossIdleDelay() {
    return BOSS_IDLE_MIN_MS + Math.floor(Math.random() * BOSS_IDLE_VARIANCE_MS);
  }

  function clearBossRoamTimer() {
    window.clearTimeout(state.bossRoamTimer);
    state.bossRoamTimer = 0;
    state.bossRoamDeadline = 0;
  }

  function scheduleBossRoam(delay = bossIdleDelay()) {
    clearBossRoamTimer();
    state.bossRoamRemaining = Math.max(0, delay);
    if (document.hidden || bossPrefersReducedMotion() || !elements.bossNpc) return;
    state.bossRoamDeadline = Date.now() + state.bossRoamRemaining;
    state.bossRoamTimer = window.setTimeout(() => {
      state.bossRoamTimer = 0;
      state.bossRoamDeadline = 0;
      state.bossRoamRemaining = 0;
      beginBossTravel();
    }, state.bossRoamRemaining);
  }

  function chooseNextBossDestination() {
    const lastIndex = BOSS_DESTINATIONS.length - 1;
    if (state.bossDestination <= 0) state.bossDirection = 1;
    else if (state.bossDestination >= lastIndex) state.bossDirection = -1;
    else if (Math.random() < 0.16) state.bossDirection *= -1;
    return state.bossDestination + state.bossDirection;
  }

  function armBossTravel(targetIndex, duration) {
    const target = BOSS_DESTINATIONS[targetIndex];
    const position = readBossPosition();
    const travelMs = Math.max(1, Math.round(duration));
    state.bossTravel = {
      targetIndex,
      target,
      duration: travelMs,
      startedAt: Date.now(),
      remaining: travelMs,
    };
    if (target.x < position.x - 1) elements.bossNpc.dataset.facing = "left";
    else if (target.x > position.x + 1) elements.bossNpc.dataset.facing = "right";
    elements.bossNpc.style.setProperty("--boss-travel-ms", `${travelMs}ms`);
    elements.bossNpc.classList.add("is-walking");
    void elements.bossNpc.offsetWidth;
    elements.bossNpc.style.left = `${target.x}px`;
    elements.bossNpc.style.top = `${target.y}px`;
    state.bossRoamDeadline = Date.now() + travelMs;
    state.bossRoamTimer = window.setTimeout(finishBossTravel, travelMs + 80);
  }

  function beginBossTravel() {
    if (!elements.bossNpc || document.hidden || bossPrefersReducedMotion()) {
      scheduleBossRoam(state.bossRoamRemaining || bossIdleDelay());
      return;
    }
    const targetIndex = chooseNextBossDestination();
    const position = readBossPosition();
    const target = BOSS_DESTINATIONS[targetIndex];
    const distance = Math.hypot(target.x - position.x, target.y - position.y);
    const duration = Math.max(
      BOSS_TRAVEL_MIN_MS,
      Math.min(BOSS_TRAVEL_MAX_MS, distance * BOSS_TRAVEL_MS_PER_PIXEL),
    );
    armBossTravel(targetIndex, duration);
  }

  function finishBossTravel() {
    clearBossRoamTimer();
    if (!state.bossTravel || !elements.bossNpc) return;
    if (document.hidden || bossPrefersReducedMotion()) {
      pauseBossRoaming();
      return;
    }
    const { target, targetIndex } = state.bossTravel;
    elements.bossNpc.classList.remove("is-walking");
    elements.bossNpc.style.left = `${target.x}px`;
    elements.bossNpc.style.top = `${target.y}px`;
    elements.bossNpc.style.removeProperty("--boss-travel-ms");
    state.bossDestination = targetIndex;
    state.bossTravel = null;
    state.bossStep = (state.bossStep + 1) % BOSS_BEHAVIORS.length;
    renderBossBehavior(false);
    scheduleBossRoam();
  }

  function pauseBossRoaming() {
    if (!elements.bossNpc) return;
    if (state.bossTravel) {
      const position = readBossPosition();
      const elapsed = Math.max(0, Date.now() - state.bossTravel.startedAt);
      state.bossTravel.remaining = Math.max(0, state.bossTravel.duration - elapsed);
      clearBossRoamTimer();
      elements.bossNpc.classList.remove("is-walking");
      elements.bossNpc.style.left = `${position.x}px`;
      elements.bossNpc.style.top = `${position.y}px`;
      elements.bossNpc.style.removeProperty("--boss-travel-ms");
      return;
    }
    if (state.bossRoamTimer && state.bossRoamDeadline) {
      state.bossRoamRemaining = Math.max(0, state.bossRoamDeadline - Date.now());
    }
    clearBossRoamTimer();
  }

  function resumeBossRoaming() {
    if (!elements.bossNpc || document.hidden || bossPrefersReducedMotion()) return;
    if (state.bossTravel) {
      const position = readBossPosition();
      const target = state.bossTravel.target;
      const distance = Math.hypot(target.x - position.x, target.y - position.y);
      if (distance < 1 || state.bossTravel.remaining < 32) {
        finishBossTravel();
        return;
      }
      armBossTravel(state.bossTravel.targetIndex, state.bossTravel.remaining);
      return;
    }
    scheduleBossRoam(state.bossRoamRemaining || bossIdleDelay());
  }

  function initializeBossNpc() {
    if (!elements.bossNpc) return;
    state.bossStep = Math.floor(Date.now() / 12000) % BOSS_BEHAVIORS.length;
    state.bossDestination = nearestBossDestination(readBossPosition());
    renderBossBehavior(false);
    elements.bossNpc.addEventListener("click", (event) => {
      event.stopPropagation();
      state.bossStep = (state.bossStep + 1) % BOSS_BEHAVIORS.length;
      renderBossBehavior(true);
      scheduleBossBehavior();
    });
    if (elements.bossSprite) {
      elements.bossSprite.addEventListener("load", () => elements.bossNpc.classList.remove("is-missing"));
      elements.bossSprite.addEventListener("error", () => elements.bossNpc.classList.add("is-missing"));
      if (elements.bossSprite.complete && !elements.bossSprite.naturalWidth) elements.bossNpc.classList.add("is-missing");
    }
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        window.clearTimeout(state.bossTimer);
        state.bossTimer = 0;
        window.clearTimeout(state.bossSpeechTimer);
        state.bossSpeechTimer = 0;
        elements.bossNpc.classList.remove("is-speaking");
        pauseBossRoaming();
      } else {
        renderBossBehavior(false);
        scheduleBossBehavior();
        resumeBossRoaming();
      }
    });
    if (typeof window.matchMedia === "function") {
      const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
      const handleMotionPreference = () => {
        if (motionQuery.matches) pauseBossRoaming();
        else resumeBossRoaming();
      };
      if (typeof motionQuery.addEventListener === "function") motionQuery.addEventListener("change", handleMotionPreference);
      else if (typeof motionQuery.addListener === "function") motionQuery.addListener(handleMotionPreference);
    }
    scheduleBossBehavior();
    scheduleBossRoam();
  }

  function formatAge(seconds) {
    const value = Math.max(0, Math.round(Number(seconds) || 0));
    if (value < 5) return "刚刚";
    if (value < 60) return `${value} 秒前`;
    if (value < 3600) return `${Math.floor(value / 60)} 分钟前`;
    if (value < 86400) return `${Math.floor(value / 3600)} 小时前`;
    return `${Math.floor(value / 86400)} 天前`;
  }

  function formatDate(value) {
    if (!value) return "未知时间";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit",
    }).format(date);
  }

  function normalizeModelsPayload(payload) {
    const source = payload && Array.isArray(payload.models) ? payload.models : [];
    const seen = new Set();
    const models = [];
    source.forEach((item) => {
      if (!item || typeof item !== "object") return;
      const id = typeof item.id === "string" ? item.id.trim().slice(0, 256) : "";
      if (!id || seen.has(id)) return;
      const label = typeof item.label === "string" && item.label.trim()
        ? item.label.trim().slice(0, 160)
        : id;
      seen.add(id);
      models.push({ id, label });
    });
    const defaultModel = payload && typeof payload.default_model === "string"
      ? payload.default_model.trim().slice(0, 256)
      : "";
    if (defaultModel && !seen.has(defaultModel)) models.unshift({ id: defaultModel, label: defaultModel });
    return { models, defaultModel };
  }

  function modelSelectionFor(sessionId) {
    if (!state.models.length) return "";
    const validIds = new Set(state.models.map((model) => model.id));
    const stored = state.modelSelections.get(sessionId);
    if (stored && validIds.has(stored)) return stored;
    const session = state.sessions.find((item) => item.id === sessionId);
    const sessionModel = session && typeof session.model === "string" ? session.model : "";
    const selected = validIds.has(sessionModel)
      ? sessionModel
      : validIds.has(state.defaultModel)
        ? state.defaultModel
        : state.models[0].id;
    state.modelSelections.set(sessionId, selected);
    return selected;
  }

  function renderModelSelector(sessionId, forceOptions) {
    if (!elements.chatModelSelect || !elements.chatModelStatus) return;
    const chat = chatStateFor(sessionId);
    const version = String(state.modelsVersion);
    const switching = elements.chatModelSelect.dataset.sessionId !== sessionId;
    const staleOptions = elements.chatModelSelect.dataset.modelsVersion !== version;

    if (switching || staleOptions || forceOptions) {
      const fragment = document.createDocumentFragment();
      if (state.models.length) {
        state.models.forEach((model) => {
          const option = document.createElement("option");
          option.value = model.id;
          option.textContent = model.id === state.defaultModel ? `${model.label}（默认）` : model.label;
          fragment.append(option);
        });
      } else {
        const option = document.createElement("option");
        option.value = "";
        option.textContent = state.modelsLoading ? "正在读取可用模型…" : "沿用会话模型";
        fragment.append(option);
      }
      elements.chatModelSelect.replaceChildren(fragment);
      elements.chatModelSelect.dataset.sessionId = sessionId;
      elements.chatModelSelect.dataset.modelsVersion = version;
    }

    const selected = modelSelectionFor(sessionId);
    if (elements.chatModelSelect.value !== selected) elements.chatModelSelect.value = selected;
    const chatBusy = chat.sending || chat.interrupting;
    elements.chatModelSelect.disabled = chatBusy || state.modelsLoading || !state.models.length;
    elements.chatModelSelect.setAttribute("aria-busy", String(state.modelsLoading));

    let statusText = "按会话记忆，仅影响后续发送";
    if (chat.interrupting) statusText = "正在打断，暂不可切换";
    else if (chat.sending) statusText = "发送中，暂不可切换";
    else if (state.modelsLoading) statusText = "正在读取可用模型…";
    else if (state.modelsError || !state.models.length) statusText = "模型列表不可用，沿用会话配置";
    if (elements.chatModelStatus.textContent !== statusText) elements.chatModelStatus.textContent = statusText;

    const selectedModel = state.models.find((model) => model.id === selected);
    elements.chatModelSelect.title = selectedModel ? selectedModel.label : "沿用会话模型";
  }

  async function fetchModels() {
    state.modelsLoading = true;
    state.modelsError = "";
    if (state.selectedId) renderModelSelector(state.selectedId, false);
    if (state.overtime.open) renderOvertimeModelSelector();
    try {
      const response = await fetch(MODELS_API_URL, { cache: "no-store", credentials: "same-origin" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const normalized = normalizeModelsPayload(await response.json());
      if (!normalized.models.length) throw new Error("empty model list");
      state.models = normalized.models;
      state.defaultModel = normalized.defaultModel;
      const validIds = new Set(state.models.map((model) => model.id));
      state.modelSelections.forEach((modelId, sessionId) => {
        if (!validIds.has(modelId)) state.modelSelections.delete(sessionId);
      });
    } catch (error) {
      state.models = [];
      state.defaultModel = "";
      state.modelsError = compactPublicText(error && error.message, 120) || "models unavailable";
    } finally {
      state.modelsLoading = false;
      state.modelsVersion += 1;
      if (state.selectedId) renderModelSelector(state.selectedId, true);
      if (state.overtime.open) renderOvertimeModelSelector();
    }
  }

  function createChatState() {
    return {
      messages: [],
      draft: "",
      sending: false,
      statusText: "就绪",
      statusKind: "idle",
      assistantIndex: -1,
      controller: null,
      requestId: "",
      interrupting: false,
      interrupted: false,
      doneSeen: false,
      hadError: false,
    };
  }

  function chatStateFor(sessionId) {
    let chat = state.chats.get(sessionId);
    if (!chat) {
      chat = createChatState();
      state.chats.set(sessionId, chat);
    }
    return chat;
  }

  function firstString(object, keys) {
    if (!object || typeof object !== "object") return "";
    for (const key of keys) {
      if (typeof object[key] === "string" && object[key].trim()) return object[key];
    }
    return "";
  }

  function stripInternalSections(value) {
    let text = String(value || "");
    text = text.replace(/<(?:analysis|reasoning|think|thinking)\b[^>]*>[\s\S]*?<\/(?:analysis|reasoning|think|thinking)>/gi, "");
    text = text.replace(/<(?:analysis|reasoning|think|thinking)\b[^>]*>[\s\S]*$/gi, "");
    return text;
  }

  function assistantEventText(event) {
    const metadata = [event && event.channel, event && event.kind, event && event.phase, event && event.role]
      .filter((value) => typeof value === "string")
      .join(" ")
      .toLowerCase();
    if (/analysis|reasoning|thinking|tool[_ -]?(?:call|result|args?|input)/.test(metadata)) return "";
    const text = firstString(event, ["text", "message", "content", "delta"]);
    return stripInternalSections(text).slice(0, 200000);
  }

  function compactPublicText(value, maximum) {
    return String(value || "").replace(/\s+/g, " ").trim().slice(0, maximum);
  }

  function statusEventText(event) {
    const text = compactPublicText(firstString(event, ["message", "text", "summary", "status"]), 320);
    if (!text) return "Codex CLI 正在处理…";
    if (/^\s*[\[{]/.test(text) || /(?:raw[_ -]?tool|tool[_ -]?(?:arguments?|args?|input)|"(?:arguments|parameters)"\s*:|chain[_ -]?of[_ -]?thought|reasoning)/i.test(text)) {
      return "Codex CLI 正在执行会话允许的操作…";
    }
    return text;
  }

  function errorEventText(event) {
    let text = firstString(event, ["message", "text", "summary", "error"]);
    if (!text && event && event.error && typeof event.error === "object") {
      text = firstString(event.error, ["message", "text", "detail"]);
    }
    text = compactPublicText(text, 600);
    if (!text) return "Codex CLI 返回了一个未说明的错误。";
    if (/^\s*[\[{]/.test(text) || /"(?:arguments|parameters)"\s*:/i.test(text)) return "Codex CLI 执行失败，请稍后重试。";
    return text;
  }

  function appendChatItem(chat, role, content) {
    const text = role === "assistant"
      ? String(content || "").slice(0, 200000)
      : role === "user"
        ? String(content || "").slice(0, 12000)
        : compactPublicText(content, role === "error" ? 600 : 360);
    if (!text) return -1;
    const last = chat.messages[chat.messages.length - 1];
    if ((role === "status" || role === "error") && last && last.role === role && last.content === text) {
      return chat.messages.length - 1;
    }
    chat.messages.push({ role, content: text, createdAt: Date.now() });
    return chat.messages.length - 1;
  }

  function mergeAssistantContent(current, incoming, event) {
    if (!current) return incoming;
    if (!incoming) return current;
    if (event && (event.replace === true || event.cumulative === true)) return incoming;
    if (incoming.startsWith(current)) return incoming;
    if (current.endsWith(incoming) || current === incoming) return current;
    return `${current}${incoming}`;
  }

  function formatChatTime(timestamp) {
    const date = new Date(timestamp || Date.now());
    return new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
  }

  function createChatMessageNode(message) {
    if (message.role === "status" || message.role === "error") {
      const event = document.createElement("div");
      event.className = `chat-event chat-event-${message.role}`;
      if (message.role === "error") event.setAttribute("role", "alert");
      const marker = document.createElement("i");
      marker.setAttribute("aria-hidden", "true");
      const copy = document.createElement("span");
      copy.textContent = message.content;
      event.append(marker, copy);
      return event;
    }

    const article = document.createElement("article");
    article.className = `chat-message chat-message-${message.role}`;
    const metadata = document.createElement("div");
    metadata.className = "chat-message-meta";
    const author = document.createElement("strong");
    author.textContent = message.role === "user" ? "你" : "Codex";
    const time = document.createElement("time");
    time.dateTime = new Date(message.createdAt || Date.now()).toISOString();
    time.textContent = formatChatTime(message.createdAt);
    const body = document.createElement("p");
    body.className = "chat-message-body";
    body.textContent = message.content;
    metadata.append(author, time);
    article.append(metadata, body);
    return article;
  }

  function createChatPendingNode(statusText) {
    const pending = document.createElement("div");
    pending.className = "chat-pending";
    pending.setAttribute("aria-label", statusText || "Codex CLI 正在回复");
    const dots = document.createElement("span");
    dots.className = "chat-pending-dots";
    dots.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 3; index += 1) dots.append(document.createElement("i"));
    const copy = document.createElement("span");
    copy.textContent = statusText || "Codex CLI 正在处理…";
    pending.append(dots, copy);
    return pending;
  }

  function resizeChatInput() {
    if (!elements.chatInput) return;
    elements.chatInput.style.height = "auto";
    elements.chatInput.style.height = `${Math.min(150, Math.max(58, elements.chatInput.scrollHeight))}px`;
  }

  function updateChatComposer(sessionId) {
    const chat = chatStateFor(sessionId);
    const selected = state.selectedId === sessionId;
    const text = selected ? elements.chatInput.value : chat.draft;
    const busy = chat.sending || chat.interrupting;
    elements.chatSend.disabled = busy || !String(text || "").trim();
    elements.chatSend.hidden = busy;
    elements.chatInterrupt.hidden = !busy;
    elements.chatInterrupt.disabled = !chat.sending || chat.interrupting;
    const sendLabel = $("span", elements.chatSend);
    if (sendLabel) sendLabel.textContent = "发送";
    const interruptLabel = $("span", elements.chatInterrupt);
    if (interruptLabel) interruptLabel.textContent = chat.interrupting ? "打断中" : "打断";
    elements.chatForm.classList.toggle("is-sending", chat.sending);
    elements.chatForm.classList.toggle("is-interrupting", chat.interrupting);
    elements.chatForm.setAttribute("aria-busy", String(busy));
    elements.chatInput.placeholder = chat.interrupting
      ? "正在打断当前回复…"
      : chat.sending
        ? "正在回复，可先输入下一条消息…"
        : "给这位同事安排工作…";
    elements.chatStatus.textContent = chat.statusText || (busy ? "发送中" : "就绪");
    elements.chatStatus.classList.toggle("is-sending", chat.sending && !chat.interrupting);
    elements.chatStatus.classList.toggle("is-interrupting", chat.interrupting);
    elements.chatStatus.classList.toggle("is-interrupted", !busy && chat.statusKind === "interrupted");
    elements.chatStatus.classList.toggle("is-error", !busy && chat.statusKind === "error");
    elements.chatLog.setAttribute("aria-busy", String(busy));
    renderModelSelector(sessionId, false);
  }

  function renderChat(sessionId, forceLog) {
    const chat = chatStateFor(sessionId);
    const switching = elements.chatSection.dataset.sessionId !== sessionId;
    if (switching) elements.chatSection.dataset.sessionId = sessionId;

    if (switching || document.activeElement !== elements.chatInput) {
      if (elements.chatInput.value !== chat.draft) elements.chatInput.value = chat.draft;
      resizeChatInput();
    }

    if (switching || forceLog) {
      const distanceFromBottom = elements.chatLog.scrollHeight - elements.chatLog.scrollTop - elements.chatLog.clientHeight;
      const busy = chat.sending || chat.interrupting;
      const shouldStick = switching || busy || distanceFromBottom < 48;
      const fragment = document.createDocumentFragment();
      if (!chat.messages.length && !busy) {
        const empty = document.createElement("p");
        empty.className = "chat-empty";
        empty.textContent = "这里会显示本次软件内的对话。发送消息后，Codex CLI 的公开活动摘要也会出现在这里。";
        fragment.append(empty);
      } else {
        chat.messages.forEach((message) => fragment.append(createChatMessageNode(message)));
        if (busy) fragment.append(createChatPendingNode(chat.statusText));
      }
      elements.chatLog.replaceChildren(fragment);
      if (shouldStick) requestAnimationFrame(() => { elements.chatLog.scrollTop = elements.chatLog.scrollHeight; });
    }
    updateChatComposer(sessionId);
  }

  function scheduleChatRender(sessionId) {
    if (state.selectedId !== sessionId) return;
    cancelAnimationFrame(state.chatRenderFrame);
    state.chatRenderFrame = requestAnimationFrame(() => {
      state.chatRenderFrame = 0;
      if (state.selectedId === sessionId) renderChat(sessionId, true);
    });
  }

  function announceChat(message) {
    elements.chatAnnouncer.textContent = "";
    requestAnimationFrame(() => { elements.chatAnnouncer.textContent = message; });
  }

  function focusChatInput(sessionId, preventScroll) {
    requestAnimationFrame(() => {
      if (state.selectedId !== sessionId) return;
      try { elements.chatInput.focus({ preventScroll: Boolean(preventScroll) }); }
      catch (_) { elements.chatInput.focus(); }
      const end = elements.chatInput.value.length;
      try { elements.chatInput.setSelectionRange(end, end); } catch (_) { /* non-critical */ }
    });
  }

  function markChatInterrupted(chat, message) {
    const text = compactPublicText(message, 360) || "已打断本次回复。";
    if (!chat.interrupted) appendChatItem(chat, "status", text);
    chat.interrupted = true;
    chat.doneSeen = true;
    chat.hadError = false;
    chat.statusText = "已打断";
    chat.statusKind = "interrupted";
  }

  function processChatEvent(sessionId, chat, event) {
    if (!event || typeof event !== "object") return false;
    const requestId = typeof event.request_id === "string" ? event.request_id : "";
    if (/^[0-9a-f]{32}$/.test(requestId)) chat.requestId = requestId;
    const type = String(event.type || "").toLowerCase();
    if (type === "status") {
      const text = statusEventText(event);
      if (String(event.status || "").toLowerCase() === "interrupted" || event.interrupted === true) {
        markChatInterrupted(chat, text);
        scheduleChatRender(sessionId);
        return true;
      }
      appendChatItem(chat, "status", text);
      chat.statusText = text;
      chat.statusKind = "sending";
      scheduleChatRender(sessionId);
      return true;
    }
    if (type === "assistant") {
      const text = assistantEventText(event);
      if (!text) return true;
      if (chat.assistantIndex < 0 || !chat.messages[chat.assistantIndex] || chat.messages[chat.assistantIndex].role !== "assistant") {
        chat.assistantIndex = appendChatItem(chat, "assistant", text);
      } else {
        const item = chat.messages[chat.assistantIndex];
        item.content = mergeAssistantContent(item.content, text, event);
      }
      chat.statusText = "正在接收回复…";
      scheduleChatRender(sessionId);
      return true;
    }
    if (type === "error") {
      const text = errorEventText(event);
      appendChatItem(chat, "error", text);
      chat.hadError = true;
      chat.statusText = "发送失败";
      chat.statusKind = "error";
      scheduleChatRender(sessionId);
      return true;
    }
    if (type === "done") {
      chat.doneSeen = true;
      if (event.interrupted === true) {
        markChatInterrupted(chat, "已打断本次回复。");
      } else if (event.ok === false) {
        if (!chat.hadError) appendChatItem(chat, "error", errorEventText(event) || "Codex CLI 未能完成这次请求。");
        chat.hadError = true;
        chat.statusText = "执行未完成";
        chat.statusKind = "error";
      } else {
        const duration = Number(event.duration_ms);
        const suffix = Number.isFinite(duration) && duration >= 0 ? ` · ${(duration / 1000).toFixed(duration >= 10000 ? 0 : 1)} 秒` : "";
        chat.statusText = `回复完成${suffix}`;
        chat.statusKind = "done";
      }
      scheduleChatRender(sessionId);
      return true;
    }
    return false;
  }

  function parseChatPayload(sessionId, chat, payload, onEvent) {
    if (Array.isArray(payload)) {
      let handled = false;
      payload.forEach((event) => {
        if (typeof onEvent === "function") onEvent(event);
        handled = processChatEvent(sessionId, chat, event) || handled;
      });
      return handled;
    }
    if (payload && Array.isArray(payload.events)) return parseChatPayload(sessionId, chat, payload.events, onEvent);
    if (typeof onEvent === "function") onEvent(payload);
    return processChatEvent(sessionId, chat, payload);
  }

  async function consumeChatResponse(sessionId, chat, response, onEvent) {
    let buffer = "";
    let handled = false;
    let malformed = 0;
    const consumeLine = (rawLine) => {
      let line = String(rawLine || "").trim();
      if (!line || line.startsWith(":")) return;
      if (line.startsWith("data:")) line = line.slice(5).trim();
      if (!line || line === "[DONE]") return;
      try {
        handled = parseChatPayload(sessionId, chat, JSON.parse(line), onEvent) || handled;
      } catch (_) {
        malformed += 1;
      }
    };
    const consumeChunk = (chunk, flush) => {
      buffer += chunk;
      const lines = buffer.split(/\r?\n/);
      buffer = flush ? "" : lines.pop();
      lines.forEach(consumeLine);
      if (flush && buffer.trim()) consumeLine(buffer);
    };

    const canStream = response.body
      && typeof response.body.getReader === "function"
      && typeof TextDecoder === "function";
    if (!canStream) {
      const complete = await response.text();
      try {
        handled = parseChatPayload(sessionId, chat, JSON.parse(complete), onEvent) || handled;
      } catch (_) {
        consumeChunk(complete, true);
      }
    } else {
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        consumeChunk(decoder.decode(part.value, { stream: true }), false);
      }
      consumeChunk(decoder.decode(), true);
    }
    if (!handled && malformed) throw new Error("Codex CLI 返回了无法解析的响应。请稍后重试。");
    if (!handled) throw new Error("Codex CLI 没有返回可显示的回复。请稍后重试。");
  }

  async function httpChatError(response) {
    let raw = "";
    try { raw = await response.text(); } catch (_) { /* response may already be closed */ }
    if (raw) {
      try {
        const payload = JSON.parse(raw);
        const code = String(payload && payload.code || "");
        const knownErrors = {
          session_busy: "这个会话仍在回复，请稍后再发送。",
          global_busy: "同时进行的 Codex 对话太多，请稍后再试。",
          invalid_cwd: "工作目录不存在或无法访问，请检查后重试。",
          invalid_model: "所选模型标识无效，请重新选择。",
          model_not_allowed: "服务器不允许使用所选模型。",
        };
        if (knownErrors[code]) return knownErrors[code];
        if (response.status === 404) return "这个 Codex 会话已不存在或已经归档。";
        if (response.status === 503) return "无法启动 Codex CLI，请确认它已经安装并完成登录。";
        const message = errorEventText(payload);
        if (message) return message;
      } catch (_) {
        const text = compactPublicText(raw, 400);
        if (text && !/^\s*[\[{]/.test(text)) return text;
      }
    }
    return `聊天请求失败（HTTP ${response.status}）。`;
  }

  async function requestChatInterrupt(requestId) {
    const response = await fetch(INTERRUPT_CHAT_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ request_id: requestId }),
    });
    if (!response.ok) throw new Error(await httpChatError(response));
    const payload = await response.json();
    return Boolean(payload && payload.interrupted);
  }

  async function interruptChatMessage(sessionId) {
    const chat = chatStateFor(sessionId);
    if (!chat.sending || chat.interrupting) return;
    const requestId = chat.requestId;
    const controller = chat.controller;
    chat.interrupting = true;
    chat.statusText = "正在打断当前回复…";
    chat.statusKind = "interrupting";
    if (state.selectedId === sessionId) {
      renderChat(sessionId, true);
      announceChat("正在打断 Codex 回复。");
    }

    let interrupted = false;
    try {
      if (!/^[0-9a-f]{32}$/.test(requestId)) throw new Error("request id is not ready");
      interrupted = await requestChatInterrupt(requestId);
    } catch (_) {
      // Aborting the original stream remains a fallback if the interrupt API is unavailable.
      interrupted = true;
    }

    if (interrupted) {
      markChatInterrupted(chat, "已打断本次回复。");
      if (controller) controller.abort();
    } else {
      chat.interrupting = false;
    }
    if (!chat.sending) chat.interrupting = false;
    if (state.selectedId === sessionId) {
      renderChat(sessionId, true);
      announceChat(interrupted ? "已打断 Codex 回复。" : "回复已经结束，无需打断。");
      if (!chat.sending) focusChatInput(sessionId, true);
    }
  }

  async function sendChatMessage(sessionId, message) {
    const chat = chatStateFor(sessionId);
    const content = String(message || "").trim().slice(0, 12000);
    if (!content || chat.sending || chat.interrupting) {
      if (chat.sending || chat.interrupting) announceChat("当前会话仍在处理，请稍候再发送。");
      return;
    }
    const selectedModel = modelSelectionFor(sessionId);

    appendChatItem(chat, "user", content);
    chat.draft = "";
    chat.sending = true;
    chat.statusText = "正在发送到 Codex CLI…";
    chat.statusKind = "sending";
    chat.assistantIndex = -1;
    chat.doneSeen = false;
    chat.hadError = false;
    chat.requestId = "";
    chat.interrupting = false;
    chat.interrupted = false;
    chat.controller = typeof AbortController === "function" ? new AbortController() : null;
    if (state.selectedId === sessionId) {
      elements.chatInput.value = "";
      resizeChatInput();
      renderChat(sessionId, true);
      focusChatInput(sessionId, true);
    }

    try {
      const payload = { session_id: sessionId, message: content };
      if (selectedModel) payload.model = selectedModel;
      const response = await fetch(CHAT_API_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/x-ndjson" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
        signal: chat.controller ? chat.controller.signal : undefined,
      });
      if (!response.ok) throw new Error(await httpChatError(response));
      await consumeChatResponse(sessionId, chat, response);
      if (!chat.interrupted && !chat.hadError && chat.assistantIndex < 0) throw new Error("Codex CLI 没有返回可显示的回复。请稍后重试。");
      if (!chat.interrupted && !chat.doneSeen && !chat.hadError) {
        chat.statusText = "回复完成";
        chat.statusKind = "done";
      }
    } catch (error) {
      const rawError = compactPublicText(error && error.message, 600);
      if (chat.interrupted || (error && error.name === "AbortError" && chat.interrupting)) {
        markChatInterrupted(chat, "已打断本次回复。");
      } else {
        const messageText = error && error.name === "AbortError"
          ? "聊天请求已取消。"
          : error instanceof TypeError && /fetch|network|load/i.test(rawError)
            ? "无法连接 Codex CLI，请稍后重试。"
            : rawError || "无法连接 Codex CLI，请稍后重试。";
        appendChatItem(chat, "error", messageText);
        chat.hadError = true;
        chat.statusText = "发送失败";
        chat.statusKind = "error";
      }
    } finally {
      chat.sending = false;
      if (chat.interrupted) chat.interrupting = false;
      chat.controller = null;
      chat.assistantIndex = -1;
      if (state.selectedId === sessionId) {
        renderChat(sessionId, true);
        announceChat(chat.interrupted ? "已打断 Codex 回复。" : chat.hadError ? "消息发送失败。" : "Codex 回复完成。" );
        focusChatInput(sessionId, true);
      }
    }
  }

  function selectedOvertimeHistorySession() {
    return state.overtime.history.find(
      (session) => session.id === state.overtime.historySelectedId,
    ) || null;
  }

  function overtimeDefaultCwd() {
    const selected = state.sessions.find((session) => session.id === state.selectedId);
    if (selected && selected.cwd) return selected.cwd;
    const active = state.sessions.find((session) => session.cwd);
    return active ? active.cwd : "";
  }

  function renderOvertimeModelSelector() {
    if (!elements.overtimeModel) return;
    const fragment = document.createDocumentFragment();
    const inherited = document.createElement("option");
    inherited.value = "";
    inherited.textContent = state.overtime.mode === "history"
      ? "沿用旧会话模型"
      : "使用 Codex 默认模型";
    fragment.append(inherited);
    state.models.forEach((model) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = model.id === state.defaultModel
        ? `${model.label}（默认）`
        : model.label;
      fragment.append(option);
    });
    elements.overtimeModel.replaceChildren(fragment);
    const desired = state.overtime.modelSelection;
    elements.overtimeModel.value = state.models.some((model) => model.id === desired)
      ? desired
      : "";
    elements.overtimeModel.disabled = state.overtime.sending
      || state.modelsLoading
      || !state.models.length;
    elements.overtimeModel.setAttribute("aria-busy", String(state.modelsLoading));
    if (state.modelsLoading) {
      elements.overtimeModelHint.textContent = "正在读取本机 Codex 可用模型…";
    } else if (state.modelsError || !state.models.length) {
      elements.overtimeModelHint.textContent = state.overtime.mode === "history"
        ? "模型列表不可用，将沿用旧会话配置。"
        : "模型列表不可用，将使用 Codex 默认配置。";
    } else {
      elements.overtimeModelHint.textContent = state.overtime.mode === "history"
        ? "不选择时沿用旧会话模型；也可以为这次回复指定其他模型。"
        : "不选择时使用 Codex 默认模型。";
    }
  }

  function setOvertimeError(message) {
    const text = compactPublicText(message, 600);
    elements.overtimeError.hidden = !text;
    elements.overtimeError.textContent = text;
  }

  function announceOvertime(message) {
    elements.overtimeAnnouncer.textContent = "";
    requestAnimationFrame(() => { elements.overtimeAnnouncer.textContent = message; });
  }

  function renderOvertimeProgress() {
    const chat = state.overtime.chat;
    if (!chat) {
      elements.overtimeProgress.hidden = true;
      elements.overtimeProgressLog.replaceChildren();
      return;
    }
    elements.overtimeProgress.hidden = false;
    elements.overtimeProgressLog.setAttribute("aria-busy", String(state.overtime.sending));
    elements.overtimeProgressTitle.textContent = state.overtime.mode === "history"
      ? "正在叫回这位同事…"
      : "正在安排新同事入场…";
    elements.overtimeProgressState.textContent = chat.statusText || "处理中";
    elements.overtimeProgressState.classList.toggle("is-error", chat.statusKind === "error");
    elements.overtimeProgressState.classList.toggle("is-done", chat.statusKind === "done");
    elements.overtimeProgressState.classList.toggle("is-interrupted", chat.statusKind === "interrupted");
    const fragment = document.createDocumentFragment();
    chat.messages.forEach((message) => fragment.append(createChatMessageNode(message)));
    if (state.overtime.sending) fragment.append(createChatPendingNode(chat.statusText));
    elements.overtimeProgressLog.replaceChildren(fragment);
    requestAnimationFrame(() => {
      elements.overtimeProgressLog.scrollTop = elements.overtimeProgressLog.scrollHeight;
    });
  }

  function updateOvertimeForm() {
    const selectedHistory = selectedOvertimeHistorySession();
    const message = String(elements.overtimeMessage.value || "").trim();
    const hasTarget = state.overtime.mode === "new"
      ? Boolean(String(elements.overtimeCwd.value || "").trim())
      : Boolean(selectedHistory) && !state.overtime.historyLoading;
    elements.overtimeSubmit.disabled = state.overtime.sending || !message || !hasTarget;
    const submitLabel = $("span", elements.overtimeSubmit);
    if (submitLabel) {
      submitLabel.textContent = state.overtime.sending
        ? "联系中"
        : state.overtime.mode === "history"
          ? "叫回来继续聊"
          : "创建并开工";
    }
    elements.overtimeCancel.textContent = state.overtime.sending ? "停止" : "取消";
    [
      elements.overtimeCwd,
      elements.overtimeSearch,
      elements.overtimeMessage,
      ...$$(".overtime-tab", elements.overtimeDialog),
      ...$$("input[type='radio']", elements.overtimeHistoryList),
    ].forEach((control) => {
      if (control) control.disabled = state.overtime.sending;
    });
    renderOvertimeModelSelector();
  }

  function renderOvertimeHistory() {
    elements.overtimeHistoryList.setAttribute("aria-busy", String(state.overtime.historyLoading));
    elements.overtimeHistoryStatus.classList.toggle("is-error", Boolean(state.overtime.historyError));
    if (state.overtime.historyLoading) {
      elements.overtimeHistoryStatus.textContent = "正在读取本机历史会话…";
    } else if (state.overtime.historyError) {
      elements.overtimeHistoryStatus.textContent = state.overtime.historyError;
    } else {
      const count = state.overtime.history.length;
      elements.overtimeHistoryStatus.textContent = count
        ? `找到 ${count} 个未归档会话，选择一位继续对话。`
        : "没有找到匹配的未归档会话。";
    }

    const fragment = document.createDocumentFragment();
    if (!state.overtime.history.length) {
      const empty = document.createElement("p");
      empty.className = "overtime-history-empty";
      empty.textContent = state.overtime.historyLoading
        ? "正在翻阅会话记录…"
        : state.overtime.historyError
          ? "暂时无法读取历史会话，请稍后重试。"
          : "换个关键词试试，或创建一个新会话。";
      fragment.append(empty);
    } else {
      state.overtime.history.forEach((session) => {
        const label = document.createElement("label");
        label.className = "overtime-history-item";
        const selected = session.id === state.overtime.historySelectedId;
        label.classList.toggle("is-selected", selected);
        label.title = session.cwd || session.title;

        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "overtime_history_session";
        radio.value = session.id;
        radio.checked = selected;
        radio.disabled = state.overtime.sending;

        const copy = document.createElement("span");
        copy.className = "overtime-history-copy";
        const title = document.createElement("strong");
        title.textContent = session.agent_nickname
          ? `${session.agent_nickname} · ${session.title}`
          : session.title;
        const detail = document.createElement("small");
        detail.textContent = `${session.cwd || "工作目录未知"} · #${session.short_id}`;
        copy.append(title, detail);

        const metadata = document.createElement("span");
        metadata.className = "overtime-history-meta";
        const presence = document.createElement("b");
        presence.classList.toggle("is-away", !session.is_active);
        presence.textContent = session.is_active ? "在岗" : "已下班";
        const age = document.createElement("span");
        age.textContent = formatAge(session.age_seconds);
        metadata.append(presence, age);
        label.append(radio, copy, metadata);
        radio.addEventListener("change", () => {
          if (!radio.checked || state.overtime.sending) return;
          state.overtime.historySelectedId = session.id;
          state.overtime.modelSelection = "";
          setOvertimeError("");
          renderOvertimeHistory();
          updateOvertimeForm();
        });
        fragment.append(label);
      });
    }
    elements.overtimeHistoryList.replaceChildren(fragment);
    updateOvertimeForm();
  }

  async function fetchOvertimeHistory() {
    if (!state.overtime.open || state.overtime.mode !== "history") return;
    if (state.overtime.historyController) state.overtime.historyController.abort();
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    state.overtime.historyController = controller;
    state.overtime.historyLoading = true;
    state.overtime.historyError = "";
    renderOvertimeHistory();
    const query = String(elements.overtimeSearch.value || "").trim().slice(0, 200);
    try {
      const response = await fetch(
        `${HISTORY_API_URL}?q=${encodeURIComponent(query)}&limit=50`,
        {
          cache: "no-store",
          credentials: "same-origin",
          signal: controller ? controller.signal : undefined,
        },
      );
      if (!response.ok) throw new Error(`历史会话请求失败（HTTP ${response.status}）。`);
      const payload = await response.json();
      if (payload && payload.database_available === false) {
        throw new Error(payload.warning || "Codex 会话数据库暂时不可用。");
      }
      const rawSessions = payload && Array.isArray(payload.sessions) ? payload.sessions : [];
      state.overtime.history = rawSessions.map((raw, index) => {
        const normalized = normalizeSession(
          {
            ...raw,
            status: raw && raw.is_active ? "waiting" : "idle",
            activity: "Waiting for input",
          },
          index,
        );
        normalized.is_active = Boolean(raw && raw.is_active);
        return normalized;
      });
      const preferred = state.overtime.historySelectedId || state.selectedId;
      state.overtime.historySelectedId = state.overtime.history.some(
        (session) => session.id === preferred,
      )
        ? preferred
        : state.overtime.history[0] ? state.overtime.history[0].id : "";
    } catch (error) {
      if (error && error.name === "AbortError") return;
      state.overtime.history = [];
      state.overtime.historySelectedId = "";
      state.overtime.historyError = compactPublicText(
        error && error.message,
        320,
      ) || "无法读取历史会话。";
    } finally {
      if (state.overtime.historyController === controller) {
        state.overtime.historyController = null;
        state.overtime.historyLoading = false;
        if (state.overtime.open && state.overtime.mode === "history") renderOvertimeHistory();
      }
    }
  }

  function resetOvertimeRun() {
    state.overtime.chat = null;
    state.overtime.sessionId = "";
    setOvertimeError("");
    renderOvertimeProgress();
  }

  function setOvertimeMode(mode, focusTarget = true) {
    if (state.overtime.sending) return;
    state.overtime.mode = mode === "history" ? "history" : "new";
    $$(".overtime-tab", elements.overtimeDialog).forEach((tab) => {
      const active = tab.dataset.overtimeMode === state.overtime.mode;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
    });
    elements.overtimeNewPanel.hidden = state.overtime.mode !== "new";
    elements.overtimeHistoryPanel.hidden = state.overtime.mode !== "history";
    elements.overtimeMessageLabel.textContent = state.overtime.mode === "history"
      ? "继续说点什么"
      : "第一项加班任务";
    elements.overtimeMessage.placeholder = state.overtime.mode === "history"
      ? "接着上次的上下文继续安排任务…"
      : "告诉新同事要处理什么…";
    elements.overtimeFootnote.textContent = state.overtime.mode === "history"
      ? "发送后，这位同事会重新出现在办公室。"
      : "完成后，新同事会自动出现在办公室。";
    state.overtime.modelSelection = state.overtime.mode === "new"
      ? (state.defaultModel || "")
      : "";
    resetOvertimeRun();
    updateOvertimeForm();
    if (state.overtime.mode === "history") fetchOvertimeHistory();
    if (focusTarget) {
      requestAnimationFrame(() => {
        const target = state.overtime.mode === "history"
          ? elements.overtimeSearch
          : elements.overtimeCwd;
        try { target.focus({ preventScroll: true }); }
        catch (_) { target.focus(); }
      });
    }
  }

  function openOvertime() {
    if (state.overtime.open) return;
    state.overtime.open = true;
    state.overtime.returnFocus = document.activeElement;
    elements.overtimeModal.hidden = false;
    elements.overtimeModal.setAttribute("aria-hidden", "false");
    $(".app-shell").inert = true;
    document.body.classList.add("is-modal-open");
    if (!elements.overtimeCwd.value) elements.overtimeCwd.value = overtimeDefaultCwd();
    setOvertimeMode(state.overtime.mode, false);
    if (!state.modelsLoading && !state.models.length) fetchModels();
    requestAnimationFrame(() => {
      const target = state.overtime.mode === "history"
        ? elements.overtimeSearch
        : elements.overtimeCwd;
      try { target.focus({ preventScroll: true }); }
      catch (_) { elements.overtimeDialog.focus(); }
    });
  }

  function closeOvertime(abortRequest = true) {
    if (!state.overtime.open) return;
    if (abortRequest && state.overtime.controller) {
      const controller = state.overtime.controller;
      const chat = state.overtime.chat;
      const requestId = chat && chat.requestId;
      if (chat) {
        chat.interrupting = true;
        markChatInterrupted(chat, "已停止这次加班呼叫。");
      }
      if (/^[0-9a-f]{32}$/.test(String(requestId || ""))) {
        requestChatInterrupt(requestId).catch(() => false);
      }
      controller.abort();
    }
    if (state.overtime.historyController) state.overtime.historyController.abort();
    window.clearTimeout(state.overtime.historyTimer);
    state.overtime.historyTimer = 0;
    state.overtime.open = false;
    elements.overtimeModal.hidden = true;
    elements.overtimeModal.setAttribute("aria-hidden", "true");
    $(".app-shell").inert = false;
    document.body.classList.remove("is-modal-open");
    const target = state.overtime.returnFocus;
    state.overtime.returnFocus = null;
    if (target && typeof target.focus === "function") {
      requestAnimationFrame(() => {
        try { target.focus({ preventScroll: true }); }
        catch (_) { target.focus(); }
      });
    }
  }

  function requestSessionRefresh() {
    if (state.pollInFlight) state.pollRefreshRequested = true;
    else fetchSessions();
  }

  async function submitOvertime() {
    if (state.overtime.sending) return;
    const mode = state.overtime.mode;
    const message = String(elements.overtimeMessage.value || "").trim().slice(0, 12000);
    const selectedHistory = selectedOvertimeHistorySession();
    const cwd = String(elements.overtimeCwd.value || "").trim();
    if (!message) {
      setOvertimeError("请先写下要交代的加班任务。");
      elements.overtimeMessage.focus();
      return;
    }
    if (mode === "new" && !cwd) {
      setOvertimeError("请输入新会话要使用的工作目录。");
      elements.overtimeCwd.focus();
      return;
    }
    if (mode === "history" && !selectedHistory) {
      setOvertimeError("请先选择一个以前的会话。");
      elements.overtimeSearch.focus();
      return;
    }

    const targetId = mode === "history" ? selectedHistory.id : "";
    const chat = mode === "history" ? chatStateFor(targetId) : createChatState();
    if (chat.sending) {
      setOvertimeError("这个会话仍在回复，请稍后再叫它回来。");
      return;
    }
    appendChatItem(chat, "user", message);
    chat.draft = "";
    chat.sending = true;
    chat.statusText = mode === "history" ? "正在叫回旧会话…" : "正在创建新会话…";
    chat.statusKind = "sending";
    chat.assistantIndex = -1;
    chat.doneSeen = false;
    chat.hadError = false;
    chat.requestId = "";
    chat.interrupting = false;
    chat.interrupted = false;
    state.overtime.chat = chat;
    state.overtime.sessionId = targetId;
    state.overtime.sending = true;
    state.overtime.controller = typeof AbortController === "function" ? new AbortController() : null;
    setOvertimeError("");
    updateOvertimeForm();
    renderOvertimeProgress();
    announceOvertime(mode === "history" ? "正在叫回旧会话。" : "正在创建新会话。");

    let succeeded = false;
    try {
      const payload = { message };
      let endpoint = CHAT_API_URL;
      if (mode === "history") payload.session_id = targetId;
      else {
        endpoint = NEW_CHAT_API_URL;
        payload.cwd = cwd;
      }
      const selectedModel = state.overtime.modelSelection;
      if (selectedModel) payload.model = selectedModel;
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/x-ndjson" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
        signal: state.overtime.controller ? state.overtime.controller.signal : undefined,
      });
      if (!response.ok) throw new Error(await httpChatError(response));
      const streamKey = targetId || `overtime-new-${Date.now()}`;
      await consumeChatResponse(streamKey, chat, response, (event) => {
        const sessionId = event && typeof event.session_id === "string"
          ? event.session_id
          : "";
        if (/^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/.test(sessionId)) {
          state.overtime.sessionId = sessionId;
        }
        requestAnimationFrame(() => {
          if (state.overtime.open) renderOvertimeProgress();
        });
      });
      if (!chat.hadError && chat.assistantIndex < 0) {
        throw new Error("Codex CLI 没有返回可显示的回复。请稍后重试。");
      }
      if (chat.hadError) {
        const lastError = [...chat.messages].reverse().find((item) => item.role === "error");
        setOvertimeError(lastError ? lastError.content : "Codex 未能完成这次请求。");
      } else {
        const resolvedId = targetId || state.overtime.sessionId;
        if (!resolvedId) throw new Error("Codex 已回复，但没有返回新会话 ID。");
        if (!chat.doneSeen) {
          chat.statusText = "回复完成";
          chat.statusKind = "done";
        }
        if (mode === "new") state.chats.set(resolvedId, chat);
        if (selectedModel) state.modelSelections.set(resolvedId, selectedModel);
        state.pendingSelectionId = resolvedId;
        state.overtime.sessionId = resolvedId;
        succeeded = true;
        elements.overtimeMessage.value = "";
        requestSessionRefresh();
      }
    } catch (error) {
      const rawError = compactPublicText(error && error.message, 600);
      const cancelled = chat.interrupted || (error && error.name === "AbortError");
      if (cancelled) {
        markChatInterrupted(chat, "已停止这次加班呼叫。");
        if (state.overtime.open) setOvertimeError("");
      } else {
        const messageText = error instanceof TypeError && /fetch|network|load/i.test(rawError)
          ? "无法连接 Codex CLI，请稍后重试。"
          : rawError || "无法连接 Codex CLI，请稍后重试。";
        if (!chat.hadError) appendChatItem(chat, "error", messageText);
        chat.hadError = true;
        chat.statusText = "呼叫失败";
        chat.statusKind = "error";
        if (state.overtime.open) setOvertimeError(messageText);
      }
    } finally {
      chat.sending = false;
      if (chat.interrupted) chat.interrupting = false;
      chat.controller = null;
      chat.assistantIndex = -1;
      state.overtime.sending = false;
      state.overtime.controller = null;
      const resolvedId = state.overtime.sessionId || targetId;
      if (resolvedId && state.selectedId === resolvedId) renderChat(resolvedId, true);
      if (state.overtime.open) {
        updateOvertimeForm();
        renderOvertimeProgress();
        announceOvertime(succeeded ? "会话已就绪，正在进入办公室。" : chat.interrupted ? "已停止这次加班呼叫。" : "加班呼叫未完成。");
      }
    }

    if (succeeded && state.overtime.open) {
      window.setTimeout(() => {
        if (state.overtime.open && !state.overtime.sending) closeOvertime(false);
      }, 650);
    }
  }

  function handleOvertimeKeydown(event) {
    if (!state.overtime.open) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeOvertime(true);
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = $$(`button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])`, elements.overtimeDialog)
      .filter((node) => !node.hidden && node.offsetParent !== null);
    if (!focusable.length) {
      event.preventDefault();
      elements.overtimeDialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function renderDetails(session) {
    const info = STATUS[session.status];
    const palette = paletteFor(session);
    const behavior = state.currentBehaviors.get(session.id);
    elements.detailPlaceholder.hidden = true;
    elements.sessionDetail.hidden = false;
    elements.detailPanel.classList.add("is-open");
    $("#detailAvatar").style.setProperty("--avatar-color", palette[0]);
    const kind = $("#detailKind");
    kind.textContent = session.is_subagent ? "子代理" : "主会话";
    kind.classList.toggle("is-subagent", session.is_subagent);
    const status = $("#detailStatus");
    status.style.color = info.color;
    $("span", status).textContent = info.detail;
    $("#detailTitle").textContent = displayName(session);
    $("#detailId").textContent = `#${session.short_id}`;
    $("#detailActivity").textContent = session.activity || info.detail;
    $("#detailAction").textContent = behaviorLabel(behavior);
    const meter = $("#activityMeter");
    meter.style.width = `${info.meter}%`;
    meter.style.background = `repeating-linear-gradient(90deg, ${info.color} 0 8px, color-mix(in srgb, ${info.color} 72%, white) 8px 12px)`;
    $("#detailModel").textContent = session.model || "—";
    const cwd = $("#detailCwd");
    cwd.textContent = session.cwd || "—";
    cwd.title = session.cwd || "";
    $("#detailSource").textContent = session.source || "—";
    const roleRow = $("#roleRow");
    roleRow.hidden = !session.agent_role;
    $("#detailRole").textContent = session.agent_role || "—";
    $("#detailAge").textContent = formatAge(session.age_seconds);
    $("#detailUpdated").textContent = formatDate(session.updated_at);
    const parentRow = $("#parentRow");
    parentRow.hidden = !session.parent_id;
    $("#detailParent").textContent = session.parent_id ? `#${session.parent_id.slice(0, 12)}` : "—";
    renderChat(session.id, false);
  }

  function selectSession(id) {
    state.selectedId = id;
    state.agentNodes.forEach((node, nodeId) => node.classList.toggle("is-selected", nodeId === id));
    const session = state.sessions.find((item) => item.id === id);
    if (session) {
      renderDetails(session);
      focusChatInput(id, false);
    }
  }

  function clearSelection() {
    state.selectedId = null;
    state.agentNodes.forEach((node) => node.classList.remove("is-selected"));
    elements.sessionDetail.hidden = true;
    elements.detailPlaceholder.hidden = false;
    elements.detailPanel.classList.remove("is-open");
  }

  function setConnection(mode, message) {
    elements.liveIndicator.classList.toggle("is-error", mode === "error");
    elements.liveIndicator.classList.toggle("is-loading", mode === "loading");
    if (elements.connectionText.textContent !== message) elements.connectionText.textContent = message;
  }

  function clearSessionPollTimer() {
    window.clearTimeout(state.pollTimer);
    state.pollTimer = 0;
  }

  function scheduleSessionPoll(delay = POLL_MS) {
    clearSessionPollTimer();
    if (document.hidden) return;
    state.pollTimer = window.setTimeout(() => {
      state.pollTimer = 0;
      fetchSessions();
    }, delay);
  }

  function initializeSessionPolling() {
    document.addEventListener("visibilitychange", () => {
      clearSessionPollTimer();
      if (document.hidden) {
        state.pollRefreshRequested = false;
        return;
      }
      if (state.pollInFlight) {
        state.pollRefreshRequested = true;
        return;
      }
      fetchSessions();
    });
  }

  async function fetchSessions() {
    if (state.pollInFlight) return;
    clearSessionPollTimer();
    if (document.hidden) return;
    state.pollRefreshRequested = false;
    state.pollInFlight = true;
    if (!state.hasLoaded) setConnection("loading", "正在连接办公室…");
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(API_URL, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const rawSessions = Array.isArray(payload) ? payload : (Array.isArray(payload.sessions) ? payload.sessions : []);
      state.sessions = rawSessions.map(normalizeSession);
      let selectedPendingSession = false;
      if (
        state.pendingSelectionId
        && state.sessions.some((session) => session.id === state.pendingSelectionId)
      ) {
        state.selectedId = state.pendingSelectionId;
        state.pendingSelectionId = null;
        state.filter = "all";
        $$(".filter-button").forEach((button) => {
          const active = button.dataset.filter === "all";
          button.classList.toggle("is-active", active);
          button.setAttribute("aria-pressed", String(active));
        });
        selectedPendingSession = true;
      }
      state.hasLoaded = true;
      const databaseAvailable = Array.isArray(payload) ? true : payload.database_available !== false;
      state.databaseAvailable = databaseAvailable;
      renderSessions(databaseAvailable);
      if (selectedPendingSession && state.selectedId) focusChatInput(state.selectedId, true);
      const count = state.sessions.length;
      const warning = !Array.isArray(payload) && payload.warning ? String(payload.warning) : "";
      if (!databaseAvailable) setConnection("error", "会话数据库不可用");
      else setConnection("ok", `${count} 位同事在办公室`);
      elements.liveIndicator.title = warning;
      const generatedAt = Array.isArray(payload) ? new Date() : (payload.generated_at || new Date());
      elements.updatedTime.textContent = `同步于 ${formatDate(generatedAt)}`;
      const activeMinutes = !Array.isArray(payload) && Number(payload.active_minutes);
      $("#sessionWindow").textContent = Number.isFinite(activeMinutes) ? `活跃窗口 ${activeMinutes} 分钟` : "活跃窗口 —";
    } catch (error) {
      state.databaseAvailable = false;
      setConnection("error", error && error.name === "AbortError" ? "连接超时，正在重试" : "连接中断，正在重试");
      if (!state.hasLoaded) {
        state.sessions = [];
        renderSessions(false);
      } else if (state.sessions.length === 0) {
        renderSessions(false);
      }
      elements.updatedTime.textContent = state.sessions.length ? "连接中断 · 显示上次状态" : "连接中断 · 等待重试";
    } finally {
      window.clearTimeout(timeout);
      state.pollInFlight = false;
      if (state.pollRefreshRequested && !document.hidden) {
        state.pollRefreshRequested = false;
        fetchSessions();
      } else {
        scheduleSessionPoll();
      }
    }
  }

  function applyView() {
    const view = state.view;
    elements.scene.style.transform = `translate3d(${Math.round(view.x)}px, ${Math.round(view.y)}px, 0) scale(${view.scale})`;
    elements.zoomOutput.textContent = `${Math.round(view.scale * 100)}%`;
  }

  function clampView() {
    const viewportWidth = elements.viewport.clientWidth;
    const viewportHeight = elements.viewport.clientHeight;
    const scaledWidth = state.sceneWidth * state.view.scale;
    const scaledHeight = state.sceneHeight * state.view.scale;
    const margin = 70;
    if (scaledWidth <= viewportWidth) state.view.x = (viewportWidth - scaledWidth) / 2;
    else state.view.x = Math.min(margin, Math.max(viewportWidth - scaledWidth - margin, state.view.x));
    if (scaledHeight <= viewportHeight) state.view.y = (viewportHeight - scaledHeight) / 2;
    else state.view.y = Math.min(margin, Math.max(viewportHeight - scaledHeight - margin, state.view.y));
  }

  function syncDashboardColumns() {
    const dashboard = $(".dashboard");
    const officeColumn = $(".office-column");
    if (!dashboard || !officeColumn || !elements.viewport) return;
    if (window.matchMedia("(max-width: 900px)").matches) {
      dashboard.style.removeProperty("--office-column-width");
      return;
    }

    const dashboardWidth = dashboard.clientWidth;
    if (!dashboardWidth) return;

    const columnChromeWidth = Math.max(0, officeColumn.offsetWidth - elements.viewport.clientWidth);
    const naturalOfficeWidth = state.sceneWidth * DEFAULT_SCENE_SCALE + FIT_PADDING * 2 + columnChromeWidth;
    const styles = window.getComputedStyle(dashboard);
    const detailPanelMinWidth = Number.parseFloat(styles.getPropertyValue("--detail-panel-min-width")) || 440;
    const maximumOfficeWidth = Math.max(0, dashboardWidth - detailPanelMinWidth);
    const nextOfficeWidth = Math.min(naturalOfficeWidth, maximumOfficeWidth);
    dashboard.style.setProperty("--office-column-width", `${Math.round(nextOfficeWidth)}px`);
  }

  function fitView() {
    syncDashboardColumns();
    const width = elements.viewport.clientWidth;
    const height = elements.viewport.clientHeight;
    if (!width || !height) return;
    state.view.scale = Math.max(
      MIN_ZOOM,
      Math.min(DEFAULT_SCENE_SCALE, (width - FIT_PADDING * 2) / state.sceneWidth),
    );
    state.view.x = (width - state.sceneWidth * state.view.scale) / 2;
    state.view.y = (height - state.sceneHeight * state.view.scale) / 2;
    state.view.fitted = true;
    state.view.userMoved = false;
    applyView();
  }

  function zoomAt(nextScale, clientX, clientY) {
    const rect = elements.viewport.getBoundingClientRect();
    const pointX = clientX == null ? rect.left + rect.width / 2 : clientX;
    const pointY = clientY == null ? rect.top + rect.height / 2 : clientY;
    const localX = pointX - rect.left;
    const localY = pointY - rect.top;
    const sceneX = (localX - state.view.x) / state.view.scale;
    const sceneY = (localY - state.view.y) / state.view.scale;
    state.view.scale = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, nextScale));
    state.view.x = localX - sceneX * state.view.scale;
    state.view.y = localY - sceneY * state.view.scale;
    state.view.userMoved = true;
    clampView();
    applyView();
  }

  function updateRoamToggle() {
    const roamToggle = $("#roamToggle");
    if (!roamToggle) return;
    roamToggle.classList.toggle("is-active", state.roamingEnabled);
    roamToggle.setAttribute("aria-pressed", String(state.roamingEnabled));
    roamToggle.setAttribute("aria-label", state.roamingEnabled ? "关闭像素同事自由活动" : "开启像素同事自由活动");
    const icon = $(".roam-icon", roamToggle);
    const label = $(".button-label", roamToggle);
    if (icon) icon.textContent = state.roamingEnabled ? "✥" : "•";
    if (label) label.textContent = state.roamingEnabled ? "自由活动：开" : "自由活动：关";
  }

  function initializeRoamingPreference() {
    const motionQuery = typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)")
      : null;
    let saved = null;
    try { saved = localStorage.getItem(ROAM_STORAGE_KEY); } catch (_) { /* optional */ }
    state.roamingPreferenceExplicit = saved === "true" || saved === "false";
    state.roamingEnabled = state.roamingPreferenceExplicit ? saved === "true" : !(motionQuery && motionQuery.matches);
    updateRoamToggle();

    if (motionQuery) {
      const followSystemPreference = (event) => {
        if (state.roamingPreferenceExplicit) return;
        state.roamingEnabled = !event.matches;
        updateRoamToggle();
        refreshBehaviors();
      };
      if (typeof motionQuery.addEventListener === "function") motionQuery.addEventListener("change", followSystemPreference);
      else if (typeof motionQuery.addListener === "function") motionQuery.addListener(followSystemPreference);
    }
  }

  function bindControls() {
    elements.overtimeButton.addEventListener("click", openOvertime);
    elements.overtimeClose.addEventListener("click", () => closeOvertime(true));
    elements.overtimeCancel.addEventListener("click", () => closeOvertime(true));
    $("[data-overtime-close]", elements.overtimeModal).addEventListener("click", () => closeOvertime(true));
    $$(".overtime-tab", elements.overtimeDialog).forEach((tab) => {
      tab.addEventListener("click", () => setOvertimeMode(tab.dataset.overtimeMode));
      tab.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        setOvertimeMode(tab.dataset.overtimeMode === "new" ? "history" : "new");
      });
    });
    elements.overtimeForm.addEventListener("submit", (event) => {
      event.preventDefault();
      submitOvertime();
    });
    elements.overtimeCwd.addEventListener("input", () => {
      setOvertimeError("");
      updateOvertimeForm();
    });
    elements.overtimeMessage.addEventListener("input", () => {
      setOvertimeError("");
      updateOvertimeForm();
    });
    elements.overtimeMessage.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || (!event.ctrlKey && !event.metaKey) || event.isComposing) return;
      event.preventDefault();
      if (typeof elements.overtimeForm.requestSubmit === "function") elements.overtimeForm.requestSubmit();
      else elements.overtimeForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    elements.overtimeModel.addEventListener("change", () => {
      state.overtime.modelSelection = elements.overtimeModel.value;
      updateOvertimeForm();
    });
    elements.overtimeSearch.addEventListener("input", () => {
      window.clearTimeout(state.overtime.historyTimer);
      state.overtime.historyTimer = window.setTimeout(() => {
        state.overtime.historyTimer = 0;
        fetchOvertimeHistory();
      }, 280);
    });
    document.addEventListener("keydown", handleOvertimeKeydown);

    $$(".filter-button").forEach((button) => {
      button.addEventListener("click", () => {
        state.filter = button.dataset.filter;
        $$(".filter-button").forEach((item) => {
          const active = item === button;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", String(active));
        });
        renderSessions(state.databaseAvailable);
      });
    });

    $("#zoomIn").addEventListener("click", () => zoomAt(state.view.scale * 1.2));
    $("#zoomOut").addEventListener("click", () => zoomAt(state.view.scale / 1.2));
    $("#fitView").addEventListener("click", fitView);
    $("#detailClose").addEventListener("click", clearSelection);

    elements.chatForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const sessionId = state.selectedId;
      if (!sessionId) return;
      const chat = chatStateFor(sessionId);
      chat.draft = elements.chatInput.value;
      sendChatMessage(sessionId, elements.chatInput.value);
    });

    elements.chatInterrupt.addEventListener("click", () => {
      const sessionId = state.selectedId;
      if (!sessionId) return;
      interruptChatMessage(sessionId);
    });

    elements.chatInput.addEventListener("input", () => {
      const sessionId = state.selectedId;
      if (!sessionId) return;
      const chat = chatStateFor(sessionId);
      chat.draft = elements.chatInput.value;
      resizeChatInput();
      updateChatComposer(sessionId);
    });

    elements.chatInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      if (typeof elements.chatForm.requestSubmit === "function") elements.chatForm.requestSubmit();
      else elements.chatForm.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    elements.chatModelSelect.addEventListener("change", () => {
      const sessionId = state.selectedId;
      if (!sessionId) return;
      const chat = chatStateFor(sessionId);
      const modelId = elements.chatModelSelect.value;
      if (chat.sending || chat.interrupting) {
        renderModelSelector(sessionId, false);
        return;
      }
      if (state.models.some((model) => model.id === modelId)) state.modelSelections.set(sessionId, modelId);
      renderModelSelector(sessionId, false);
    });

    const roamToggle = $("#roamToggle");
    roamToggle.addEventListener("click", () => {
      state.roamingEnabled = !state.roamingEnabled;
      state.roamingPreferenceExplicit = true;
      try { localStorage.setItem(ROAM_STORAGE_KEY, String(state.roamingEnabled)); } catch (_) { /* optional */ }
      updateRoamToggle();
      refreshBehaviors();
    });

    const themeToggle = $("#themeToggle");
    themeToggle.addEventListener("click", () => {
      const next = document.body.dataset.theme === "night" ? "day" : "night";
      document.body.dataset.theme = next;
      themeToggle.setAttribute("aria-pressed", String(next === "night"));
      $(".button-label", themeToggle).textContent = next === "night" ? "日班模式" : "夜班模式";
      try { localStorage.setItem("codex-pixel-office.theme", next); } catch (_) { /* optional */ }
    });

    elements.viewport.addEventListener("wheel", (event) => {
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0012);
      zoomAt(state.view.scale * factor, event.clientX, event.clientY);
      elements.dragHint.classList.add("is-hidden");
    }, { passive: false });

    elements.viewport.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || event.target.closest(".agent, .boss-npc")) return;
      state.drag = { id: event.pointerId, startX: event.clientX, startY: event.clientY, originX: state.view.x, originY: state.view.y, moved: false };
      elements.viewport.setPointerCapture(event.pointerId);
      elements.viewport.classList.add("is-dragging");
    });

    elements.viewport.addEventListener("pointermove", (event) => {
      if (!state.drag || state.drag.id !== event.pointerId) return;
      const dx = event.clientX - state.drag.startX;
      const dy = event.clientY - state.drag.startY;
      if (Math.abs(dx) + Math.abs(dy) > 3) state.drag.moved = true;
      state.view.x = state.drag.originX + dx;
      state.view.y = state.drag.originY + dy;
      state.view.userMoved = true;
      clampView();
      applyView();
    });

    const endDrag = (event) => {
      if (!state.drag || state.drag.id !== event.pointerId) return;
      if (state.drag.moved) elements.dragHint.classList.add("is-hidden");
      state.drag = null;
      elements.viewport.classList.remove("is-dragging");
    };
    elements.viewport.addEventListener("pointerup", endDrag);
    elements.viewport.addEventListener("pointercancel", endDrag);
    elements.viewport.addEventListener("dblclick", (event) => {
      if (!event.target.closest(".agent, .boss-npc")) fitView();
    });
    elements.viewport.addEventListener("keydown", (event) => {
      if (event.key === "+" || event.key === "=") zoomAt(state.view.scale * 1.2);
      else if (event.key === "-") zoomAt(state.view.scale / 1.2);
      else if (event.key === "0" || event.key === "Home") fitView();
      else return;
      event.preventDefault();
    });

    let resizeFrame = 0;
    const refreshViewAfterResize = () => {
      cancelAnimationFrame(resizeFrame);
      resizeFrame = requestAnimationFrame(() => {
        syncDashboardColumns();
        if (!state.view.userMoved) fitView();
        else { clampView(); applyView(); }
      });
    };
    window.addEventListener("resize", refreshViewAfterResize);
    if (typeof ResizeObserver === "function") {
      state.viewportObserver = new ResizeObserver(refreshViewAfterResize);
      state.viewportObserver.observe(elements.viewport);
    }
  }

  function initializeThemeAndClock() {
    let savedTheme = "";
    try { savedTheme = localStorage.getItem("codex-pixel-office.theme") || ""; } catch (_) { /* optional */ }
    const theme = savedTheme === "night" || savedTheme === "day"
      ? savedTheme
      : (new Date().getHours() >= 19 || new Date().getHours() < 7 ? "night" : "day");
    document.body.dataset.theme = theme;
    $("#themeToggle").setAttribute("aria-pressed", String(theme === "night"));
    $(".button-label", $("#themeToggle")).textContent = theme === "night" ? "日班模式" : "夜班模式";
    const updateClock = () => {
      $("#officeClock").textContent = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date());
    };
    updateClock();
    window.setInterval(updateClock, 30000);
  }

  function initializeAssets() {
    const background = $(".office-bg-asset");
    if (!background) return;
    const markLoaded = () => {
      background.classList.remove("is-missing");
      elements.scene.classList.add("has-office-bg");
    };
    const markMissing = () => {
      background.classList.add("is-missing");
      elements.scene.classList.remove("has-office-bg");
    };
    background.addEventListener("load", markLoaded);
    background.addEventListener("error", markMissing);
    if (background.complete) {
      if (background.naturalWidth > 0) markLoaded();
      else markMissing();
    }
  }

  initializeThemeAndClock();
  initializeAssets();
  initializeRoamingPreference();
  initializeBossNpc();
  initializeSessionPolling();
  bindControls();
  fetchModels();
  requestAnimationFrame(fitView);
  startBehaviorClock();
  fetchSessions();
})();
