import styles from "../styles/App.module.css";

export type PageStateKind = "loading" | "empty" | "partial" | "error" | "forbidden";

type PageStateProps = {
  kind: PageStateKind;
  title: string;
  detail?: string;
  action?: { label: string; onClick: () => void };
};

const labels: Record<PageStateKind, string> = {
  loading: "加载中",
  empty: "暂无数据",
  partial: "部分数据",
  error: "加载失败",
  forbidden: "无权限",
};

/** Shared page state presentation; unknown or incomplete data never looks green. */
export function PageState({ kind, title, detail, action }: PageStateProps) {
  const alert = kind === "error" || kind === "forbidden";
  return (
    <section
      className={`${styles.pageState} ${alert ? styles.pageStateError : ""}`}
      data-state={kind}
      role={alert ? "alert" : undefined}
      aria-busy={kind === "loading" ? true : undefined}
    >
      <span className={`${styles.pageStateBadge} ${styles[`pageState_${kind}`]}`}>{labels[kind]}</span>
      <strong>{title}</strong>
      {detail ? <span>{detail}</span> : null}
      {kind === "loading" ? <span className={styles.loadingDot} aria-hidden="true" /> : null}
      {action ? <button type="button" onClick={action.onClick}>{action.label}</button> : null}
    </section>
  );
}

