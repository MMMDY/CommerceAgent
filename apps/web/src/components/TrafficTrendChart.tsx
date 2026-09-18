import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { GridComponent, TooltipComponent, type GridComponentOption, type TooltipComponentOption } from "echarts/components";
import { LineChart, type LineSeriesOption } from "echarts/charts";
import { CanvasRenderer } from "echarts/renderers";
import type { ComposeOption } from "echarts/core";

import styles from "../styles/App.module.css";

echarts.use([GridComponent, TooltipComponent, LineChart, CanvasRenderer]);

type EChartOption = ComposeOption<GridComponentOption | TooltipComponentOption | LineSeriesOption>;
type TrendPoint = { bucket: string; requests: number; completed: number };

export function TrafficTrendChart({ points }: { points: TrendPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    const labels = points.map((item) => new Date(item.bucket).toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit" }));
    const option: EChartOption = {
      animation: false,
      aria: { enabled: true, decal: { show: true } },
      grid: { left: 44, right: 18, top: 18, bottom: 38 },
      tooltip: {
        trigger: "axis",
        valueFormatter: (value) => `${String(value)} 个 Run`,
      },
      xAxis: { type: "category", data: labels, axisLabel: { color: "#60718c", hideOverlap: true } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: "#60718c" }, splitLine: { lineStyle: { color: "#e8edf5" } } },
      series: [
        { name: "请求", type: "line", data: points.map((item) => item.requests), smooth: false, showSymbol: false, lineStyle: { color: "#235bd6", width: 2 }, areaStyle: { color: "rgba(35,91,214,0.08)" } },
        { name: "完成", type: "line", data: points.map((item) => item.completed), smooth: false, showSymbol: false, lineStyle: { color: "#237a52", width: 2 } },
      ],
    };
    chart.setOption(option);
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [points]);

  return <div ref={containerRef} className={styles.echartsFrame} role="img" aria-label="每小时请求与完成趋势图" />;
}
