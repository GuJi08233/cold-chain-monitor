import { useEffect, useRef } from "react";
import type { EChartsOption } from "echarts";
import { LineChart, ScatterChart } from "echarts/charts";
import {
  DataZoomComponent,
  GraphicComponent,
  GridComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TitleComponent,
  TooltipComponent,
} from "echarts/components";
import { init, use, type EChartsType } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";

use([
  TitleComponent,
  TooltipComponent,
  GridComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  GraphicComponent,
  LineChart,
  ScatterChart,
  CanvasRenderer,
]);

interface EChartProps {
  option: EChartsOption;
  height?: number;
}

export function EChart(props: EChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) {
      return;
    }

    if (!chartRef.current) {
      chartRef.current = init(el);
    }
    const chart = chartRef.current;
    if (typeof ResizeObserver !== "undefined") {
      const observer = new ResizeObserver(() => {
        chart.resize();
      });
      observer.observe(el);
      return () => {
        observer.disconnect();
      };
    }

    const resize = () => {
      chart.resize();
    };
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
    };
  }, []);

  useEffect(() => {
    if (!chartRef.current) {
      return;
    }
    chartRef.current.setOption(props.option, {
      notMerge: true,
      lazyUpdate: true,
    });
  }, [props.option]);

  useEffect(() => {
    return () => {
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  return <div ref={containerRef} style={{ height: props.height || 280, width: "100%" }} />;
}
