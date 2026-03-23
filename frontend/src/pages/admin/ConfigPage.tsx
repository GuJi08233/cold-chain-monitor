import { useEffect, useMemo, useState } from "react";

import { Panel } from "../../components/Panel";
import { api, getErrorMessage, unwrap } from "../../lib/http";
import type { ApiResponse } from "../../types/api";

interface ConfigItem {
  key: string;
  value: string;
  is_sensitive: boolean;
  is_set: boolean;
}

export function ConfigPage() {
  const [items, setItems] = useState<ConfigItem[]>([]);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);

  const groupedItems = useMemo(() => {
    const eth = items.filter((item) => item.key.startsWith("eth_"));
    const td = items.filter((item) => item.key.startsWith("tdengine_"));
    const mqtt = items.filter((item) => item.key.startsWith("mqtt_"));
    return { eth, td, mqtt };
  }, [items]);

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

  const renderGroup = (title: string, groupItems: ConfigItem[]) => {
    return (
      <div className="config-group">
        <h3>{title}</h3>
        <div className="form-grid dual">
          {groupItems.map((item) => (
            <label key={item.key}>
              {item.key}
              <input
                onChange={(event) =>
                  setDraft((prev) => ({
                    ...prev,
                    [item.key]: event.target.value,
                  }))
                }
                placeholder={
                  item.is_sensitive ? (item.is_set ? "已设置（输入新值覆盖）" : "未设置") : ""
                }
                type={item.is_sensitive ? "password" : "text"}
                value={draft[item.key] || ""}
              />
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

      {renderGroup("以太坊配置", groupedItems.eth)}
      {renderGroup("TDengine 配置", groupedItems.td)}
      {renderGroup("MQTT 配置", groupedItems.mqtt)}
    </Panel>
  );
}
