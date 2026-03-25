import { useEffect, useMemo, useState } from "react";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse } from "../../types/api";

type ConfigGroup = "system" | "eth" | "tdengine" | "mqtt";
type ConfigInputType = "text" | "password" | "number" | "boolean" | "timezone";

interface ConfigItem {
  key: string;
  label: string;
  group: ConfigGroup;
  input_type: ConfigInputType;
  value: string;
  is_sensitive: boolean;
  is_set: boolean;
}

const GROUP_TITLES: Record<ConfigGroup, string> = {
  system: "系统运行配置",
  eth: "以太坊配置",
  tdengine: "TDengine 配置",
  mqtt: "MQTT 配置",
};

const GROUP_ORDER: ConfigGroup[] = ["system", "eth", "tdengine", "mqtt"];

const TIMEZONE_SUGGESTIONS = [
  "Asia/Shanghai",
  "UTC",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Europe/London",
  "America/New_York",
];

function groupItemsByCategory(items: ConfigItem[]): Record<ConfigGroup, ConfigItem[]> {
  return {
    system: items.filter((item) => item.group === "system"),
    eth: items.filter((item) => item.group === "eth"),
    tdengine: items.filter((item) => item.group === "tdengine"),
    mqtt: items.filter((item) => item.group === "mqtt"),
  };
}

export function ConfigPage() {
  const [items, setItems] = useState<ConfigItem[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);

  const groupedItems = useMemo(() => groupItemsByCategory(items), [items]);

  const loadData = async () => {
    setError("");
    try {
      const data = await unwrap(api.get<ApiResponse<ConfigItem[]>>("/config"));
      setItems(data);
      const mapped: Record<string, string> = {};
      data.forEach((item) => {
        mapped[item.key] = item.is_sensitive ? "" : item.value || "";
      });
      setDraft(mapped);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  useEffect(() => {
    void loadData();
  }, []);

  const saveConfig = async () => {
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const payload: Record<string, string> = {};
      items.forEach((item) => {
        const value = draft[item.key] ?? "";
        if (item.is_sensitive) {
          if (value.trim()) {
            payload[item.key] = value;
          }
          return;
        }
        payload[item.key] = value;
      });
      await api.put<ApiResponse<ConfigItem[]>>("/config", payload);
      await loadData();
      setSuccess("配置已保存");
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async (type: "mqtt" | "tdengine" | "eth") => {
    setError("");
    setSuccess("");
    try {
      await api.post(`/config/test-${type}`);
      setSuccess(`${type.toUpperCase()} 连接测试通过`);
    } catch (requestError) {
      setError(getErrorMessage(requestError));
    }
  };

  const updateDraftValue = (key: string, value: string) => {
    setDraft((prev) => ({
      ...prev,
      [key]: value,
    }));
  };

  const renderInput = (item: ConfigItem) => {
    const value = draft[item.key] || "";
    const placeholder =
      item.is_sensitive ? (item.is_set ? "已设置（输入新值覆盖）" : "未设置") : "";

    if (item.input_type === "boolean") {
      return (
        <select
          onChange={(event) => updateDraftValue(item.key, event.target.value)}
          value={value || "true"}
        >
          <option value="true">启用</option>
          <option value="false">停用</option>
        </select>
      );
    }

    if (item.input_type === "number") {
      return (
        <input
          min={0}
          onChange={(event) => updateDraftValue(item.key, event.target.value)}
          type="number"
          value={value}
        />
      );
    }

    if (item.input_type === "timezone") {
      return (
        <>
          <input
            list="timezone-suggestions"
            onChange={(event) => updateDraftValue(item.key, event.target.value)}
            placeholder="例如：Asia/Shanghai"
            type="text"
            value={value}
          />
          <datalist id="timezone-suggestions">
            {TIMEZONE_SUGGESTIONS.map((option) => (
              <option key={option} value={option} />
            ))}
          </datalist>
        </>
      );
    }

    return (
      <input
        onChange={(event) => updateDraftValue(item.key, event.target.value)}
        placeholder={placeholder}
        type={item.is_sensitive ? "password" : "text"}
        value={value}
      />
    );
  };

  const renderGroup = (group: ConfigGroup) => {
    const groupItems = groupedItems[group];
    if (!groupItems.length) {
      return null;
    }

    return (
      <div className="config-group" key={group}>
        <h3>{GROUP_TITLES[group]}</h3>
        {group === "system" && (
          <p className="muted">
            这些参数会影响后台定时任务与时间处理逻辑，保存后按新配置生效。
          </p>
        )}
        <div className="form-grid dual">
          {groupItems.map((item) => (
            <label key={item.key}>
              {item.label}
              {renderInput(item)}
            </label>
          ))}
        </div>
      </div>
    );
  };

  return (
    <Panel
      extra={
        <div className="inline-actions">
          <button className="ghost-btn" onClick={() => void testConnection("mqtt")} type="button">
            测试 MQTT
          </button>
          <button className="ghost-btn" onClick={() => void testConnection("tdengine")} type="button">
            测试 TDengine
          </button>
          <button className="ghost-btn" onClick={() => void testConnection("eth")} type="button">
            测试 ETH
          </button>
          <button className="primary-btn inline" disabled={saving} onClick={() => void saveConfig()} type="button">
            {saving ? "保存中..." : "保存配置"}
          </button>
        </div>
      }
      title="系统配置"
    >
      {error && <p className="error-text">{error}</p>}
      {success && <p className="success-text">{success}</p>}

      {GROUP_ORDER.map((group) => renderGroup(group))}
    </Panel>
  );
}
