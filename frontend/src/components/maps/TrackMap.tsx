import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

interface GeoPoint {
  ts: string;
  lat: number;
  lng: number;
}

interface AnomalyGeoPoint extends GeoPoint {
  anomalyId: number;
  metric: string;
  status: string;
}

interface TrackMapProps {
  points: GeoPoint[];
  anomalyPoints: AnomalyGeoPoint[];
  selectedAnomalyId: number | null;
  onSelectAnomaly?: (anomalyId: number) => void;
}

function buildDotIcon(color: string, withRing = false): L.DivIcon {
  const ring = withRing
    ? "box-shadow:0 0 0 4px rgba(255,255,255,0.9),0 0 0 8px rgba(214,64,69,0.2);"
    : "";
  return L.divIcon({
    className: "",
    html: `<span style="display:block;width:12px;height:12px;border-radius:999px;background:${color};border:2px solid #fff;${ring}"></span>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

const startIcon = buildDotIcon("#2f79c9");
const endIcon = buildDotIcon("#0e7c86");

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function buildPopupHtml(
  title: string,
  rows: Array<{ label: string; value: string }>,
): string {
  const body = rows
    .map(
      (row) =>
        `<p><span>${escapeHtml(row.label)}</span><strong>${escapeHtml(row.value)}</strong></p>`,
    )
    .join("");
  return `<div class="map-popup-card"><h4>${escapeHtml(title)}</h4>${body}</div>`;
}

export function TrackMap(props: TrackMapProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<L.LayerGroup | null>(null);
  const lastTrackKeyRef = useRef("");
  const lastSelectedRef = useRef<number | null>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) {
      return;
    }

    if (!mapRef.current) {
      const map = L.map(root, {
        zoomControl: true,
        preferCanvas: true,
      }).setView([31.2304, 121.4737], 6);

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors",
      }).addTo(map);

      mapRef.current = map;
      layersRef.current = L.layerGroup().addTo(map);
    }

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
      layersRef.current = null;
      lastTrackKeyRef.current = "";
      lastSelectedRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layers = layersRef.current;
    if (!map || !layers) {
      return;
    }

    layers.clearLayers();

    if (!props.points.length) {
      lastTrackKeyRef.current = "";
      lastSelectedRef.current = props.selectedAnomalyId;
      return;
    }

    window.requestAnimationFrame(() => {
      map.invalidateSize();
    });

    const latlngs = props.points.map((item) => [item.lat, item.lng] as L.LatLngTuple);
    const trackKey = `${props.points.length}:${props.points[0].ts}:${props.points[props.points.length - 1].ts}`;

    L.polyline(latlngs, {
      color: "rgba(17, 36, 38, 0.16)",
      weight: 10,
      opacity: 0.55,
      lineCap: "round",
      lineJoin: "round",
    }).addTo(layers);
    L.polyline(latlngs, {
      color: "#0e7c86",
      weight: 4,
      opacity: 0.95,
      lineCap: "round",
      lineJoin: "round",
    }).addTo(layers);

    const first = props.points[0];
    const last = props.points[props.points.length - 1];
    L.marker([first.lat, first.lng], { icon: startIcon })
      .bindPopup(
        buildPopupHtml("起点", [
          { label: "时间", value: first.ts },
          { label: "坐标", value: `${first.lat.toFixed(6)}, ${first.lng.toFixed(6)}` },
        ]),
      )
      .addTo(layers);
    L.marker([last.lat, last.lng], { icon: endIcon })
      .bindPopup(
        buildPopupHtml("终点 / 最新点", [
          { label: "时间", value: last.ts },
          { label: "坐标", value: `${last.lat.toFixed(6)}, ${last.lng.toFixed(6)}` },
        ]),
      )
      .addTo(layers);

    const selectedMarkers: L.Marker[] = [];
    props.anomalyPoints.forEach((item) => {
      const selected = item.anomalyId === props.selectedAnomalyId;
      const marker = L.marker([item.lat, item.lng], {
        icon: buildDotIcon("#d64045", selected),
      });
      marker.bindPopup(
        buildPopupHtml(`异常 #${String(item.anomalyId)}`, [
          { label: "指标", value: item.metric },
          { label: "状态", value: item.status },
          { label: "时间", value: item.ts },
          { label: "坐标", value: `${item.lat.toFixed(6)}, ${item.lng.toFixed(6)}` },
        ]),
      );
      marker.on("click", () => {
        props.onSelectAnomaly?.(item.anomalyId);
      });
      marker.addTo(layers);
      if (selected) {
        selectedMarkers.push(marker);
      }
    });

    const selectedPoint = props.anomalyPoints.find(
      (item) => item.anomalyId === props.selectedAnomalyId,
    );
    if (selectedPoint) {
      map.setView([selectedPoint.lat, selectedPoint.lng], Math.max(map.getZoom(), 13), {
        animate: true,
      });
      selectedMarkers[0]?.openPopup();
      lastSelectedRef.current = props.selectedAnomalyId;
      return;
    }

    const selectionCleared =
      lastSelectedRef.current !== null && props.selectedAnomalyId === null;
    if (selectionCleared || lastTrackKeyRef.current !== trackKey) {
      const bounds = L.latLngBounds(latlngs);
      if (latlngs.length === 1) {
        map.setView(latlngs[0], 14, { animate: true });
      } else {
        map.fitBounds(bounds, {
          padding: [32, 32],
          maxZoom: 15,
        });
      }
      lastTrackKeyRef.current = trackKey;
    }
    lastSelectedRef.current = props.selectedAnomalyId;
  }, [props.points, props.anomalyPoints, props.selectedAnomalyId, props.onSelectAnomaly]);

  return <div className="track-map" ref={rootRef} />;
}
