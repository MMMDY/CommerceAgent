import styles from "../styles/App.module.css";
import { statusLabel, statusTone } from "../ui/status";

export function StatusTag({ value, label }: { value: unknown; label?: string }) {
  const tone = statusTone(value);
  return <span className={`${styles.statusBadge} ${styles[`status_${tone}`]}`} data-status-tone={tone}>{label ?? statusLabel(value)}</span>;
}
