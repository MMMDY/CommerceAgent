import { useState } from "react";

import { resolveRoute } from "./routes";
import styles from "./styles/App.module.css";

const routeLabels = {
  chat: "对话工作台",
  run: "执行详情",
  evals: "评测面板"
} as const;

export function App() {
  const route = resolveRoute(window.location.pathname);
  const [drawer, setDrawer] = useState<"navigation" | "trace" | null>(null);

  const closeDrawer = () => setDrawer(null);

  return (
    <main className={styles.shell} aria-label="CommerceAgent 演示工作台">
      <button
        className={`${styles.drawerToggle} ${styles.navigationToggle}`}
        type="button"
        onClick={() => setDrawer("navigation")}
      >
        导航
      </button>
      <aside
        className={`${styles.sidePanel} ${styles.leftPanel} ${drawer === "navigation" ? styles.drawerOpen : ""}`}
        aria-label="会话与预置场景"
      >
        <button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button>
        <p className={styles.eyebrow}>CommerceAgent</p>
        <h1>客服 Agent</h1>
        <nav aria-label="主要页面">
          <a href="/">对话</a>
          <a href="/runs/demo">Run Trace</a>
          <a href="/evals">评测</a>
        </nav>
      </aside>
      <section className={styles.workspace} aria-live="polite">
        <p className={styles.eyebrow}>Phase 0</p>
        <h2>{routeLabels[route]}</h2>
        <p>工程骨架已准备就绪。后续阶段将在这里接入会话、工具调用、确认卡和评测结果。</p>
      </section>
      <button
        className={`${styles.drawerToggle} ${styles.traceToggle}`}
        type="button"
        onClick={() => setDrawer("trace")}
      >
        Trace
      </button>
      <aside
        className={`${styles.sidePanel} ${styles.rightPanel} ${drawer === "trace" ? styles.drawerOpen : ""}`}
        aria-label="Trace 摘要"
      >
        <button className={styles.drawerClose} type="button" onClick={closeDrawer}>关闭</button>
        <p className={styles.eyebrow}>Trace</p>
        <p>尚无执行事件</p>
      </aside>
      {drawer ? <button className={styles.backdrop} aria-label="关闭抽屉" type="button" onClick={closeDrawer} /> : null}
    </main>
  );
}
