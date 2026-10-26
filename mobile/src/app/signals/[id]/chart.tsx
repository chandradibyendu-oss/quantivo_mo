import { router, useLocalSearchParams } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  PanResponder,
  Platform,
  Pressable,
  ScrollView,
  Text,
  View,
  type GestureResponderEvent,
} from "react-native";

import { api, ApiRequestError } from "@/api";
import { useAuth } from "@/auth";
import { quoteTone } from "@/quote";
import { shownTargets } from "@/targets";
import { AppShell } from "@/shell";
import type { ChartCandle, SignalChart, SignalDetail } from "@/types";
import { colors, ui } from "@/ui";

const PLOT_H = 280;
const TIME_H = 26;
const PAD_X = 4;
const AXIS_PAD = 4;

type Level = { label: string; price: number; color: string };
type Range = { low: number; high: number };
type SpanLimits = { min: number; max: number };
type Viewport = {
  count: number;
  end: number;
  pinned: boolean;
  manual: Range | null;
  cross: { index: number; price: number } | null;
};
type Region = "plot" | "price" | "time";
type Grant = {
  x: number;
  y: number;
  count: number;
  end: number;
  pinned: boolean;
  low: number;
  high: number;
  manual: Range | null;
  region: Region;
  moved: boolean;
  lockY: boolean;
};

export default function SignalChartScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { ready, userId } = useAuth();
  const [interval, setInterval] = useState<"1m" | "5m">("5m");
  const [chart, setChart] = useState<SignalChart | null>(null);
  const [signal, setSignal] = useState<SignalDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scrollable, setScrollable] = useState(true);

  const load = useCallback(async () => {
    if (!id) {
      return;
    }
    const [detail, candles] = await Promise.all([
      api<SignalDetail>(`/api/v1/signals/${id}`),
      api<SignalChart>(`/api/v1/signals/${id}/chart?interval=${interval}`),
    ]);
    setSignal(detail);
    setChart(candles);
  }, [id, interval]);

  useEffect(() => {
    if (!ready) {
      return;
    }
    if (!userId) {
      router.replace("/");
      return;
    }
    let cancelled = false;
    setChart(null);
    setError(null);
    load().catch((caught: unknown) => {
      if (!cancelled) {
        setError(caught instanceof ApiRequestError ? caught.message : "The chart is not available.");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [load, ready, userId]);

  const traded = chart?.quote_state === "ready" && chart.last_price ? chart.last_price : "—";
  const tone = quoteTone(chart?.quote_state === "ready" ? chart.change_percent : null);

  return (
    <AppShell
      title={chart?.symbol ?? signal?.symbol ?? "Chart"}
      onBack={() => router.replace(id ? `/signals/${id}` : "/signals")}
    >
      <ScrollView scrollEnabled={scrollable} contentContainerStyle={{ paddingLeft: 16, paddingBottom: 28 }}>
        <View style={{ paddingRight: 16 }}>
        <View style={ui.viewBar}>
          <Pressable
            style={[ui.viewSegment, interval === "5m" && ui.viewSegmentOn]}
            onPress={() => setInterval("5m")}
          >
            <Text style={[ui.viewText, interval === "5m" && ui.viewTextOn]}>5m</Text>
          </Pressable>
          <Pressable
            style={[ui.viewSegment, ui.viewDivider, interval === "1m" && ui.viewSegmentOn]}
            onPress={() => setInterval("1m")}
          >
            <Text style={[ui.viewText, interval === "1m" && ui.viewTextOn]}>1m</Text>
          </Pressable>
        </View>
        {chart ? (
          <Text style={ui.meta}>
            {chart.session_date} · {chart.quote_label}{" "}
            <Text style={{ fontWeight: "700", color: tone.color }}>
              {traded}
              {chart.last_price ? tone.text : ""}
            </Text>
          </Text>
        ) : null}
        {!chart && !error ? <ActivityIndicator style={{ marginTop: 24 }} /> : null}
        {error ? <Text style={ui.error}>{error}</Text> : null}
        {chart?.quote_state === "unconfigured" ? (
          <Text style={ui.meta}>The chart needs a Fyers app. The lines are the scanner's prices.</Text>
        ) : null}
        {chart?.quote_state === "checking" ? <Text style={ui.meta}>Reading the session candles.</Text> : null}
        {chart?.quote_state === "unavailable" ? (
          <Text style={ui.meta}>The session candles could not be read.</Text>
        ) : null}
        </View>
        {chart ? <CandleChart chart={chart} onGesture={(active) => setScrollable(!active)} /> : null}
        <View style={{ paddingRight: 16 }}>
        {signal?.executable && signal.suggested_quantity != null ? (
          <Pressable
            style={[ui.primary, { marginTop: 16 }]}
            onPress={() => router.push(`/signals/${id}`)}
          >
            <Text style={ui.primaryText}>Review order</Text>
          </Pressable>
        ) : null}
        </View>
      </ScrollView>
    </AppShell>
  );
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value) || max < min) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function fittedCount(plot: number, total: number): number {
  if (total <= 1) {
    return Math.max(total, 1);
  }
  const fitted = Math.round(Math.max(plot - PAD_X * 2, 40) / 8);
  return clamp(fitted, Math.min(16, total), total);
}

function clampCount(count: number, total: number): number {
  if (total <= 0) {
    return 1;
  }
  return clamp(Math.round(count), Math.min(5, total), total);
}

function windowOf(view: Viewport, total: number): { start: number; end: number; count: number } {
  if (total <= 0) {
    return { start: 0, end: 0, count: 0 };
  }
  const count = clamp(Math.round(view.count), 1, total);
  const end = clamp(Math.round(view.pinned ? total : view.end), count, total);
  return { start: end - count, end, count };
}

function candleSpan(candles: ChartCandle[], start: number, end: number): Range | null {
  let low = Infinity;
  let high = -Infinity;
  for (let index = start; index < end; index += 1) {
    const bar = candles[index];
    const barHigh = Number(bar?.high);
    const barLow = Number(bar?.low);
    if (Number.isFinite(barHigh)) {
      high = Math.max(high, barHigh);
    }
    if (Number.isFinite(barLow)) {
      low = Math.min(low, barLow);
    }
  }
  if (!Number.isFinite(low) || !Number.isFinite(high)) {
    return null;
  }
  if (high === low) {
    const pad = Math.max(Math.abs(high) * 0.002, 0.05);
    return { low: low - pad, high: high + pad };
  }
  const pad = (high - low) * 0.12;
  return { low: low - pad, high: high + pad };
}

function spanLimits(candles: ChartCandle[], levels: Level[]): SpanLimits {
  let low = Infinity;
  let high = -Infinity;
  candles.forEach((bar) => {
    const barHigh = Number(bar.high);
    const barLow = Number(bar.low);
    if (Number.isFinite(barHigh)) {
      high = Math.max(high, barHigh);
    }
    if (Number.isFinite(barLow)) {
      low = Math.min(low, barLow);
    }
  });
  levels.forEach((level) => {
    low = Math.min(low, level.price);
    high = Math.max(high, level.price);
  });
  const full = Number.isFinite(low) && Number.isFinite(high) ? high - low : 1;
  return { min: Math.max(full * 0.02, 0.2), max: Math.max(full * 1.8, 1) };
}

function zoomAround(low: number, high: number, factor: number, fromTop: number, limits: SpanLimits): Range {
  const span = Math.max(high - low, limits.min);
  const next = clamp(span * factor, limits.min, limits.max);
  const anchor = high - clamp(fromTop, 0, 1) * span;
  const nextHigh = anchor + clamp(fromTop, 0, 1) * next;
  return { low: nextHigh - next, high: nextHigh };
}

function niceStep(span: number): number {
  const rough = span / 5;
  const power = 10 ** Math.floor(Math.log10(Math.max(rough, 1e-9)));
  const error = rough / power;
  const nice = error >= 7.5 ? 10 : error >= 3.5 ? 5 : error >= 1.5 ? 2 : 1;
  return nice * power;
}

function priceTicks(low: number, high: number): number[] {
  const span = high - low;
  if (!(span > 0)) {
    return [low];
  }
  const step = niceStep(span);
  const first = Math.ceil((low + step * 0.001) / step) * step;
  const ticks: number[] = [];
  for (let value = first; value <= high - step * 0.05 && ticks.length < 8; value += step) {
    ticks.push(Number(value.toFixed(8)));
  }
  return ticks;
}

function money(value: number): string {
  return value.toFixed(2);
}

function widestPrice(ticks: number[], levels: Level[], crossPrice: number | null): string {
  const labels = [...ticks.map(money), ...levels.map((level) => money(level.price))];
  if (crossPrice != null) {
    labels.push(money(crossPrice));
  }
  return labels.reduce((best, label) => (label.length > best.length ? label : best), "00.00");
}

function levelsOf(chart: SignalChart): Level[] {
  return [
    { label: "Trigger", price: Number(chart.trigger_price), color: colors.accent },
    { label: "Stop", price: Number(chart.stop_loss), color: colors.sell },
    ...shownTargets(chart.targets).map((target) => ({
      label: target.label,
      price: Number(target.price),
      color: colors.buy,
    })),
  ].filter((level) => Number.isFinite(level.price));
}

function CandleChart({ chart, onGesture }: { chart: SignalChart; onGesture: (active: boolean) => void }) {
  const candles = chart.candles;
  const levels = levelsOf(chart);
  const host = useRef<HTMLElement | null>(null);
  const [hostNode, setHostNode] = useState<HTMLElement | null>(null);
  const setHost = useCallback((node: unknown) => {
    const next = (node as HTMLElement | null) ?? null;
    host.current = next;
    setHostNode((current) => (current === next ? current : next));
  }, []);
  const layout = useRef({ width: 0, plot: 0 });
  const candlesRef = useRef(candles);
  const levelsRef = useRef(levels);
  const onGestureRef = useRef(onGesture);
  const adjusted = useRef(false);
  const grant = useRef<Grant | null>(null);
  const dragging = useRef(false);
  const lastTap = useRef(0);
  const [plotWidth, setPlotWidth] = useState(0);
  const [view, setView] = useState<Viewport>({
    count: 40,
    end: candles.length,
    pinned: true,
    manual: null,
    cross: null,
  });
  const viewRef = useRef(view);
  candlesRef.current = candles;
  levelsRef.current = levels;
  onGestureRef.current = onGesture;

  const commit = useCallback((next: Viewport) => {
    viewRef.current = next;
    setView(next);
  }, []);

  const resetView = useCallback(
    (plot: number) => {
      adjusted.current = false;
      const total = candlesRef.current.length;
      commit({
        count: fittedCount(plot || 320, total),
        end: total,
        pinned: true,
        manual: null,
        cross: null,
      });
    },
    [commit],
  );

  const seriesKey = `${chart.interval}:${chart.session_date}:${candles.length}`;
  useEffect(() => {
    resetView(layout.current.plot);
  }, [resetView, seriesKey]);

  const limits = spanLimits(candles, levels);
  const shown = windowOf(view, candles.length);
  const auto = candleSpan(candles, shown.start, shown.end);
  const range = view.manual ?? auto ?? candleSpan(levels.map((level) => ({
    time: "",
    open: String(level.price),
    high: String(level.price),
    low: String(level.price),
    close: String(level.price),
  })), 0, levels.length) ?? { low: 0, high: 1 };
  const span = range.high - range.low || 1;
  const yOf = (price: number) => ((range.high - price) / span) * PLOT_H;
  const bar = shown.count > 0 ? Math.max((plotWidth - PAD_X * 2) / shown.count, 1) : 1;

  const hitRegion = useCallback((x: number, y: number): Region => {
    if (y >= PLOT_H) {
      return "time";
    }
    if (x >= layout.current.plot) {
      return "price";
    }
    return "plot";
  }, []);

  const rangeNow = useCallback((): Range => {
    const current = viewRef.current;
    const bars = candlesRef.current;
    const frame = windowOf(current, bars.length);
    if (current.manual) {
      return current.manual;
    }
    return candleSpan(bars, frame.start, frame.end) ?? { low: 0, high: 1 };
  }, []);

  const crossFrom = useCallback(
    (x: number, y: number) => {
      const bars = candlesRef.current;
      const current = viewRef.current;
      const frame = windowOf(current, bars.length);
      if (frame.count === 0 || hitRegion(x, y) !== "plot") {
        if (current.cross) {
          commit({ ...current, cross: null });
        }
        return;
      }
      const width = Math.max(layout.current.plot - PAD_X * 2, 1);
      const slot = width / frame.count;
      const index = clamp(frame.start + Math.floor((x - PAD_X) / slot), frame.start, frame.end - 1);
      const scale = current.manual ?? candleSpan(bars, frame.start, frame.end) ?? { low: 0, high: 1 };
      const height = scale.high - scale.low || 1;
      const price = scale.high - clamp(y, 0, PLOT_H) / PLOT_H * height;
      const previous = current.cross;
      if (previous && previous.index === index && Math.abs(previous.price - price) < 0.005) {
        return;
      }
      commit({ ...current, cross: { index, price } });
    },
    [commit, hitRegion],
  );

  const begin = useCallback(
    (x: number, y: number) => {
      const region = hitRegion(x, y);
      const now = Date.now();
      if (now - lastTap.current < 300) {
        lastTap.current = 0;
        if (region === "price") {
          commit({ ...viewRef.current, manual: null, cross: null });
          return;
        }
        if (region === "plot") {
          resetView(layout.current.plot);
          return;
        }
      }
      lastTap.current = now;
      const scale = rangeNow();
      const current = viewRef.current;
      const total = candlesRef.current.length;
      grant.current = {
        x,
        y,
        count: current.count,
        end: current.pinned ? total : current.end,
        pinned: current.pinned,
        low: scale.low,
        high: scale.high,
        manual: current.manual,
        region,
        moved: false,
        lockY: false,
      };
      dragging.current = true;
      onGestureRef.current(true);
    },
    [commit, hitRegion, rangeNow, resetView],
  );

  const move = useCallback(
    (x: number, y: number) => {
      const held = grant.current;
      if (!held || !dragging.current) {
        crossFrom(x, y);
        return;
      }
      const dx = x - held.x;
      const dy = y - held.y;
      if (!held.moved && Math.hypot(dx, dy) < 5) {
        return;
      }
      held.moved = true;
      adjusted.current = true;
      const total = candlesRef.current.length;
      const bounds = spanLimits(candlesRef.current, levelsRef.current);
      if (held.region === "price") {
        const next = zoomAround(held.low, held.high, Math.exp(dy / 140), 0.5, bounds);
        commit({ ...viewRef.current, manual: next, cross: null });
        return;
      }
      if (held.region === "time") {
        const nextCount = clampCount(held.count * Math.exp(dx / 140), total);
        const end = clamp(held.pinned ? total : held.end, Math.min(nextCount, total), total);
        commit({
          ...viewRef.current,
          count: nextCount,
          end,
          pinned: end >= total,
          cross: null,
        });
        return;
      }
      const slot = Math.max((layout.current.plot - PAD_X * 2) / Math.max(held.count, 1), 1);
      const end = clamp(held.end - dx / slot, Math.min(held.count, total), total);
      if (Math.abs(dy) > 8) {
        held.lockY = true;
      }
      const shift = (dy / PLOT_H) * (held.high - held.low);
      const manual = held.lockY
        ? zoomAround(held.low + shift, held.high + shift, 1, 0.5, bounds)
        : held.manual;
      commit({
        ...viewRef.current,
        count: held.count,
        end,
        pinned: end >= total - 0.5,
        manual,
        cross: null,
      });
    },
    [commit, crossFrom],
  );

  const finish = useCallback(
    (x: number, y: number) => {
      const held = grant.current;
      dragging.current = false;
      onGestureRef.current(false);
      if (held && !held.moved && held.region === "plot") {
        crossFrom(x, y);
      }
      grant.current = null;
    },
    [crossFrom],
  );

  const wheelZoom = useCallback(
    (delta: number, x: number, y: number) => {
      if (delta === 0) {
        return;
      }
      adjusted.current = true;
      const region = hitRegion(x, y);
      const current = viewRef.current;
      const total = candlesRef.current.length;
      if (region === "price") {
        const scale = rangeNow();
        const bounds = spanLimits(candlesRef.current, levelsRef.current);
        commit({
          ...current,
          manual: zoomAround(scale.low, scale.high, Math.exp(delta / 240), y / PLOT_H, bounds),
        });
        return;
      }
      const factor = Math.exp(delta / 240);
      const frame = windowOf(current, total);
      const nextCount = clampCount(frame.count * factor, total);
      if (current.pinned) {
        commit({ ...current, count: nextCount, end: total, pinned: true, cross: null });
        return;
      }
      const ratio = clamp((x - PAD_X) / Math.max(layout.current.plot - PAD_X * 2, 1), 0, 1);
      const anchor = frame.start + ratio * frame.count;
      let end = anchor + (1 - ratio) * nextCount;
      if (end > total) {
        end = total;
      }
      if (end < nextCount) {
        end = nextCount;
      }
      commit({ ...current, count: nextCount, end, pinned: end >= total - 0.01, cross: null });
    },
    [commit, hitRegion, rangeNow],
  );

  useEffect(() => {
    if (Platform.OS !== "web" || !hostNode?.addEventListener) {
      return;
    }
    const node = hostNode;
    node.style.touchAction = "none";
    node.style.userSelect = "none";
    const point = (event: PointerEvent) => {
      const rect = node.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const down = (event: PointerEvent) => {
      if (event.button !== 0) {
        return;
      }
      event.preventDefault();
      node.setPointerCapture?.(event.pointerId);
      const at = point(event);
      begin(at.x, at.y);
    };
    const moved = (event: PointerEvent) => {
      const at = point(event);
      const region = at.y >= PLOT_H ? "time" : at.x >= layout.current.plot ? "price" : "plot";
      node.style.cursor = region === "price" ? "ns-resize" : region === "time" ? "ew-resize" : "crosshair";
      move(at.x, at.y);
    };
    const up = (event: PointerEvent) => {
      const at = point(event);
      if (node.hasPointerCapture?.(event.pointerId)) {
        node.releasePointerCapture(event.pointerId);
      }
      finish(at.x, at.y);
    };
    const left = (event: PointerEvent) => {
      if (!dragging.current && event.pointerType === "mouse") {
        const current = viewRef.current;
        if (current.cross) {
          commit({ ...current, cross: null });
        }
      }
    };
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey) {
        return;
      }
      event.preventDefault();
      const rect = node.getBoundingClientRect();
      const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
      wheelZoom(delta, event.clientX - rect.left, event.clientY - rect.top);
    };
    node.addEventListener("pointerdown", down);
    node.addEventListener("pointermove", moved);
    node.addEventListener("pointerup", up);
    node.addEventListener("pointercancel", up);
    node.addEventListener("pointerleave", left);
    node.addEventListener("wheel", wheel, { passive: false });
    return () => {
      node.removeEventListener("pointerdown", down);
      node.removeEventListener("pointermove", moved);
      node.removeEventListener("pointerup", up);
      node.removeEventListener("pointercancel", up);
      node.removeEventListener("pointerleave", left);
      node.removeEventListener("wheel", wheel);
    };
  }, [begin, commit, finish, hostNode, move, wheelZoom]);

  const pan = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderTerminationRequest: () => false,
      onShouldBlockNativeResponder: () => true,
      onPanResponderGrant: (event: GestureResponderEvent) => {
        begin(event.nativeEvent.locationX, event.nativeEvent.locationY);
      },
      onPanResponderMove: (event: GestureResponderEvent) => {
        move(event.nativeEvent.locationX, event.nativeEvent.locationY);
      },
      onPanResponderRelease: (event: GestureResponderEvent) => {
        finish(event.nativeEvent.locationX, event.nativeEvent.locationY);
      },
      onPanResponderTerminate: () => {
        finish(0, 0);
      },
    }),
  ).current;

  const ticks = priceTicks(range.low, range.high);
  const times = timeMarks(candles, shown.start, shown.end, bar, plotWidth);
  const cross = view.cross;
  const crossBar = cross && candles[cross.index] ? candles[cross.index] : null;
  const widest = widestPrice(ticks, levels, cross?.price ?? null);

  return (
    <View accessibilityLabel="Candle chart. The latest candle is at the right. The price scale is on the right." style={{ marginTop: 8 }}>
      <Text style={[readout, { paddingRight: 16 }]}>
        {crossBar
          ? `${crossBar.time}  ${money(cross?.price ?? Number(crossBar.close))}   O ${crossBar.open}  H ${crossBar.high}  L ${crossBar.low}  C ${crossBar.close}`
          : " "}
      </Text>
      <View
        ref={setHost}
        {...(Platform.OS === "web" ? {} : pan.panHandlers)}
      >
      <View style={{ flexDirection: "row" }}>
        <View
          style={{ flex: 1 }}
          onLayout={(event) => {
            const plot = event.nativeEvent.layout.width;
            const changed = Math.abs(plot - layout.current.plot) > 1;
            layout.current = { width: plot, plot };
            setPlotWidth(plot);
            if (changed && !adjusted.current) {
              resetView(plot);
            }
          }}
        >
        <View style={{ height: PLOT_H, overflow: "hidden" }}>
          {ticks.map((tick) => (
            <View
              key={`grid-${tick}`}
              style={{
                position: "absolute",
                top: yOf(tick),
                left: 0,
                right: 0,
                height: 1,
                backgroundColor: colors.line,
              }}
            />
          ))}
          {shown.count > 0
            ? candles.slice(shown.start, shown.end).map((candle, offset) => {
                const index = shown.start + offset;
                const open = Number(candle.open);
                const close = Number(candle.close);
                const up = close >= open;
                const color = up ? colors.buy : colors.sell;
                const bodyTop = yOf(Math.max(open, close));
                const bodyHeight = Math.max(Math.abs(yOf(open) - yOf(close)), 1);
                const bodyWidth = Math.max(bar * 0.62, 1);
                const left = PAD_X + offset * bar + (bar - bodyWidth) / 2;
                return (
                  <View key={`${candle.time}-${index}`} style={{ position: "absolute", left, width: bodyWidth, height: PLOT_H }}>
                    <View
                      style={{
                        position: "absolute",
                        left: bodyWidth / 2 - 0.5,
                        top: yOf(Number(candle.high)),
                        width: 1,
                        height: Math.max(yOf(Number(candle.low)) - yOf(Number(candle.high)), 1),
                        backgroundColor: color,
                      }}
                    />
                    <View
                      style={{
                        position: "absolute",
                        left: 0,
                        width: bodyWidth,
                        top: bodyTop,
                        height: bodyHeight,
                        backgroundColor: color,
                      }}
                    />
                  </View>
                );
              })
            : null}
          {levels.map((level) => {
            const top = yOf(level.price);
            if (top < 0 || top > PLOT_H) {
              return null;
            }
            return (
              <View key={level.label} pointerEvents="none" style={{ position: "absolute", top, left: 0, right: 0, height: 1, backgroundColor: level.color }} />
            );
          })}
          {cross && crossBar ? (
            <View
              pointerEvents="none"
              style={{
                position: "absolute",
                left: PAD_X + (cross.index - shown.start) * bar + bar / 2,
                top: 0,
                width: 1,
                height: PLOT_H,
                backgroundColor: "rgba(28,36,48,0.45)",
              }}
            />
          ) : null}
          {cross ? (
            <View
              pointerEvents="none"
              style={{
                position: "absolute",
                left: 0,
                right: 0,
                top: clamp(yOf(cross.price), 0, PLOT_H - 1),
                height: 1,
                backgroundColor: "rgba(28,36,48,0.45)",
              }}
            />
          ) : null}
        </View>
        <View style={{ height: TIME_H, borderTopWidth: 1, borderTopColor: colors.line }}>
          {times.map((mark) => {
            const crossX = cross && crossBar ? PAD_X + (cross.index - shown.start) * bar + bar / 2 : null;
            if (crossX != null && Math.abs(mark.x - crossX) < 42) {
              return null;
            }
            return (
              <Text
                key={`${mark.index}-${mark.time}`}
                style={{
                  position: "absolute",
                  left: clamp(mark.x - 18, 0, Math.max(plotWidth - 36, 0)),
                  top: 4,
                  width: 36,
                  textAlign: "center",
                  fontSize: 10,
                  color: colors.muted,
                  fontVariant: ["tabular-nums"],
                }}
              >
                {mark.time}
              </Text>
            );
          })}
          {cross && crossBar ? (
            <View
              style={{
                position: "absolute",
                left: clamp(PAD_X + (cross.index - shown.start) * bar + bar / 2 - 18, 0, Math.max(plotWidth - 36, 0)),
                top: 3,
                width: 36,
                backgroundColor: colors.ink,
                borderRadius: 2,
              }}
            >
              <Text style={{ color: colors.paper, fontSize: 10, textAlign: "center", fontVariant: ["tabular-nums"] }}>{crossBar.time}</Text>
            </View>
          ) : null}
        </View>
        </View>
        <View style={{ borderLeftWidth: 1, borderLeftColor: colors.line, paddingLeft: AXIS_PAD, paddingRight: AXIS_PAD }}>
          <View style={{ height: PLOT_H }}>
            <Text style={{ opacity: 0, fontSize: 11, fontVariant: ["tabular-nums"] }}>{widest}</Text>
            {ticks.map((tick) => {
              const top = yOf(tick);
              const nearLevel = levels.some((level) => Math.abs(yOf(level.price) - top) < 14 && yOf(level.price) >= 0 && yOf(level.price) <= PLOT_H);
              const nearCross = cross != null && Math.abs(yOf(cross.price) - top) < 16;
              if (nearLevel || nearCross || top < 2 || top > PLOT_H - 12) {
                return null;
              }
              return (
                <Text key={`tick-${tick}`} style={[axisText, { top: top - 7 }]}>
                  {money(tick)}
                </Text>
              );
            })}
            {levels.map((level) => {
              const top = yOf(level.price);
              if (top < 2 || top > PLOT_H - 12 || (cross != null && Math.abs(yOf(cross.price) - top) < 16)) {
                return null;
              }
              return (
                <Text key={level.label} style={[axisText, { top: top - 7, color: level.color, fontWeight: "700" }]}>
                  {money(level.price)}
                </Text>
              );
            })}
            {cross ? (
              <View style={{ position: "absolute", top: clamp(yOf(cross.price) - 8, 0, PLOT_H - 16), left: 0, backgroundColor: colors.ink, borderRadius: 2, paddingHorizontal: 3 }}>
                <Text style={{ color: colors.paper, fontSize: 10, fontVariant: ["tabular-nums"] }}>{money(cross.price)}</Text>
              </View>
            ) : null}
          </View>
          <View style={{ height: TIME_H }} />
        </View>
      </View>
      </View>
      <Text style={[ui.meta, { paddingRight: 16 }]}>
        Trigger {chart.trigger_price} · Stop {chart.stop_loss}
        {shownTargets(chart.targets).map((target) => ` · ${target.label} ${target.price}`).join("")}
      </Text>
      <Text style={[ui.meta, { paddingRight: 16 }]}>Drag the right scale for height. Drag the times to fit more candles.</Text>
    </View>
  );
}

function timeMarks(
  candles: ChartCandle[],
  start: number,
  end: number,
  slot: number,
  plotWidth: number,
): { index: number; time: string; x: number }[] {
  if (end <= start || plotWidth <= 0) {
    return [];
  }
  const wanted = new Set<number>([start, end - 1]);
  for (let index = start; index < end; index += 1) {
    if (candles[index]?.time?.endsWith(":00")) {
      wanted.add(index);
    }
  }
  const kept: number[] = [];
  for (const index of [...wanted].sort((left, right) => left - right)) {
    if (!candles[index]) {
      continue;
    }
    const previous = kept[kept.length - 1];
    const gap = previous == null ? 44 : (index - previous) * slot;
    if (previous == null || gap >= 44) {
      kept.push(index);
    } else if (index === end - 1) {
      kept[kept.length - 1] = index;
    }
  }
  return kept.flatMap((index) => {
    const candle = candles[index];
    if (!candle) {
      return [];
    }
    return [{ index, time: candle.time, x: PAD_X + (index - start) * slot + slot / 2 }];
  });
}

const readout = {
  minHeight: 18,
  fontSize: 12,
  color: colors.ink,
  fontVariant: ["tabular-nums"] as const,
};

const axisText = {
  position: "absolute" as const,
  left: 0,
  fontSize: 11,
  color: colors.muted,
  fontVariant: ["tabular-nums"] as const,
};
