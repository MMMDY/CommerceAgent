import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, type BarSeriesOption } from "echarts/charts";
import { GridComponent, TooltipComponent, type GridComponentOption, type TooltipComponentOption } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ComposeOption } from "echarts/core";

import styles from "../styles/App.module.css";

echarts.use([GridComponent, TooltipComponent, BarChart, CanvasRenderer]);

type EChartOption = ComposeOption<GridComponentOption | TooltipComponentOption | BarSeriesOption>;

export type SafetyCategoryPoint = {
  category: string;
  hit_count: number;
  handoff_count: number;
};

export function SafetyCategoryChart({ points }: { points: SafetyCategoryPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    const chart = echarts.init(container, undefined, { renderer: "canvas" });
    const option: EChartOption = {
      animation: false,
      aria: { enabled: true, decal: { show: true } },
      grid: { left: 52, right: 18, top: 18, bottom: 46 },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        valueFormatter: (value) => `${String(value)} 次`,
      },
      xAxis: { type: "category", data: points.map((item) => item.category), axisLabel: { color: "#60718c", interval: 0, rotate: points.length > 4 ? 18 : 0 } },
      yAxis: { type: "value", minInterval: 1, axisLabel: { color: "#60718c" }, splitLine: { lineStyle: { color: "#e8edf5" } } },
      series: [
        { name: "命中", type: "bar", data: points.map((item) => item.hit_count), itemStyle: { color: "#235bd6" }, barMaxWidth: 28 },
        { name: "人工接管", type: "bar", data: points.map((item) => item.handoff_count), itemStyle: { color: "#a15c00" }, barMaxWidth: 28 },
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

  return <div ref={containerRef} className={styles.echartsFrame} role="img" aria-label="Safety 各高危类别命中与人工接管对比图" />;
}
