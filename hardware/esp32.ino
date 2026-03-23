
// =================================================================
// ESP32 传感器数据采集终端 v4.2 - 多设备模拟版
// 功能：WiFi自动重连、NTP时间同步、GPS/温湿度/气压数据采集、多设备MQTT发布
// =================================================================

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_SHT4x.h>
#include <Adafruit_BMP280.h>
#include <TinyGPS++.h>
#include <time.h>

// =================================================================
// 配置区
// =================================================================

// 提交到仓库时只保留占位配置，真实凭据请在本地开发副本中填写。
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

const char* MQTT_SERVER = "YOUR_MQTT_BROKER_HOST";
const int MQTT_PORT = 1883;
const char* MQTT_USER = "YOUR_MQTT_USERNAME";
const char* MQTT_PASSWORD = "YOUR_MQTT_PASSWORD";
const char* MQTT_CLIENT_ID = "esp32-client-demo";

const char* TOPIC_PUBLISH = "esp32/data";

// =================================================================
// 多设备模拟配置
// =================================================================
const int DEVICE_COUNT = 3;  // 模拟设备数量
const char* DEVICE_IDS[DEVICE_COUNT] = {
  "device-001",
  "device-002",
  "device-003"
};

// NTP时间服务器配置
const char* NTP_SERVER1 = "ntp.aliyun.com";
const char* NTP_SERVER2 = "pool.ntp.org";
const long GMT_OFFSET_SEC = 8 * 3600;  // UTC+8 北京时间
const int DAYLIGHT_OFFSET_SEC = 0;     // 无夏令时

#define GPS_RX_PIN 16
#define GPS_TX_PIN 17

#define STATUS_INTERVAL 2000
#define SENSOR_READ_INTERVAL 2000
#define BMP280_ADDRESS 0x76

// =================================================================
// 全局对象
// =================================================================
WiFiClient espClient;
PubSubClient mqttClient(espClient);
Adafruit_SHT4x sht4 = Adafruit_SHT4x();
Adafruit_BMP280 bmp;
TinyGPSPlus gps;
HardwareSerial gpsSerial(2);

// =================================================================
// 数据结构体
// =================================================================

struct SensorData {
  float temperature = 0.0;
  float humidity = 0.0;
  float pressure = 0.0;
  float altitude = 0.0;
  bool valid = false;
  bool bmpValid = false;
  unsigned long lastRead = 0;
} sensorData;

struct GPSData {
  bool valid = false;
  double lat = 0.0;
  double lng = 0.0;
  float altitude = 0.0;
  int satellites = 0;
} gpsData;

unsigned long lastStatusPublish = 0;
bool ntpSynced = false;  // NTP时间同步状态

// =================================================================
// WiFi 连接管理
// =================================================================

#define WIFI_RECONNECT_INTERVAL 5000
#define MQTT_RECONNECT_INTERVAL 5000
#define MQTT_MAX_RETRIES 5

unsigned long lastWifiReconnectAttempt = 0;
unsigned long lastMqttReconnectAttempt = 0;
int mqttRetryCount = 0;
bool wasWifiConnected = false;

void connectWiFi() {
  Serial.print("🔗 连接 WiFi: ");
  Serial.println(WIFI_SSID);
  
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  int timeout = 20;
  while (WiFi.status() != WL_CONNECTED && timeout > 0) {
    delay(500);
    Serial.print(".");
    timeout--;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✓ WiFi 已连接: " + WiFi.localIP().toString());
    wasWifiConnected = true;
    // WiFi连接成功后同步NTP时间
    syncNTPTime();
  } else {
    Serial.println("\n✗ WiFi 连接超时，将在后台继续尝试");
  }
}

bool checkWiFiConnection() {
  if (WiFi.status() == WL_CONNECTED) {
    if (!wasWifiConnected) {
      Serial.println("✓ WiFi 重新连接成功: " + WiFi.localIP().toString());
      wasWifiConnected = true;
      mqttRetryCount = 0;
      // WiFi重连成功后重新同步NTP时间
      syncNTPTime();
    }
    return true;
  }
  
  if (wasWifiConnected) {
    Serial.println("⚠️  WiFi 连接已断开");
    wasWifiConnected = false;
  }
  
  unsigned long now = millis();
  if (now - lastWifiReconnectAttempt >= WIFI_RECONNECT_INTERVAL) {
    lastWifiReconnectAttempt = now;
    Serial.println("🔄 尝试重新连接 WiFi...");
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }
  
  return false;
}

// =================================================================
// NTP 时间同步
// =================================================================

void syncNTPTime() {
  Serial.print("🕐 同步NTP时间...");
  configTime(GMT_OFFSET_SEC, DAYLIGHT_OFFSET_SEC, NTP_SERVER1, NTP_SERVER2);
  
  // 等待时间同步（最多5秒）
  int retry = 0;
  while (time(nullptr) < 1000000000 && retry < 10) {
    delay(500);
    Serial.print(".");
    retry++;
  }
  
  if (time(nullptr) > 1000000000) {
    ntpSynced = true;
    struct tm timeinfo;
    getLocalTime(&timeinfo);
    Serial.printf("\n✓ NTP时间同步成功: %04d-%02d-%02d %02d:%02d:%02d\n",
                  timeinfo.tm_year + 1900, timeinfo.tm_mon + 1, timeinfo.tm_mday,
                  timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
  } else {
    ntpSynced = false;
    Serial.println("\n✗ NTP时间同步失败");
  }
}

String getCurrentTimeString() {
  if (!ntpSynced) {
    return "未同步";
  }
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) {
    return "获取失败";
  }
  char buffer[25];
  sprintf(buffer, "%04d-%02d-%02d %02d:%02d:%02d",
          timeinfo.tm_year + 1900, timeinfo.tm_mon + 1, timeinfo.tm_mday,
          timeinfo.tm_hour, timeinfo.tm_min, timeinfo.tm_sec);
  return String(buffer);
}

// =================================================================
// MQTT 连接管理
// =================================================================

bool mqttConnect() {
  Serial.print("🔗 连接 MQTT...");
  
  if (mqttClient.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASSWORD)) {
    Serial.println("成功!");
    
    // 发布所有设备的上线消息
    for (int i = 0; i < DEVICE_COUNT; i++) {
      StaticJsonDocument<128> doc;
      doc["device_id"] = DEVICE_IDS[i];
      doc["status"] = "online";
      doc["version"] = "v4.2-multi";
      char buffer[128];
      serializeJson(doc, buffer);
      mqttClient.publish(TOPIC_PUBLISH, buffer);
      delay(50);  // 短暂延迟避免消息堆积
    }
    
    mqttRetryCount = 0;
    return true;
  } else {
    Serial.printf("失败 (rc=%d)\n", mqttClient.state());
    return false;
  }
}

void checkMqttConnection() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }
  
  if (mqttClient.connected()) {
    return;
  }
  
  unsigned long now = millis();
  if (now - lastMqttReconnectAttempt >= MQTT_RECONNECT_INTERVAL) {
    lastMqttReconnectAttempt = now;
    
    if (mqttRetryCount < MQTT_MAX_RETRIES) {
      mqttRetryCount++;
      Serial.printf("🔄 MQTT重连尝试 %d/%d\n", mqttRetryCount, MQTT_MAX_RETRIES);
      
      if (!mqttConnect()) {
        if (mqttRetryCount >= MQTT_MAX_RETRIES) {
          Serial.println("⚠️  MQTT重连次数已达上限，30秒后重试");
        }
      }
    } else {
      static unsigned long lastMaxRetryReset = 0;
      if (now - lastMaxRetryReset >= 30000) {
        lastMaxRetryReset = now;
        mqttRetryCount = 0;
        Serial.println("🔄 重置MQTT重试计数，继续尝试连接");
      }
    }
  }
}

// =================================================================
// I2C 总线检查
// =================================================================

bool checkI2CBus(uint8_t address) {
  Wire.beginTransmission(address);
  byte error = Wire.endTransmission();
  return (error == 0);
}

// =================================================================
// 传感器更新
// =================================================================

void updateSensors() {
  unsigned long now = millis();
  if (now - sensorData.lastRead < SENSOR_READ_INTERVAL) { return; }
  sensorData.lastRead = now;

  sensors_event_t humidity, temp;
  if (sht4.getEvent(&humidity, &temp) && 
      !isnan(humidity.relative_humidity) && !isnan(temp.temperature) &&
      temp.temperature > -40 && temp.temperature < 85 && 
      humidity.relative_humidity >= 0 && humidity.relative_humidity <= 100) {
    sensorData.temperature = temp.temperature;
    sensorData.humidity = humidity.relative_humidity;
    sensorData.valid = true;
  } else {
    sensorData.valid = false;
  }

  if (checkI2CBus(BMP280_ADDRESS)) {
    float pressure = bmp.readPressure();
    if (pressure > 30000 && pressure < 110000) {
      sensorData.pressure = pressure / 100.0F;
      sensorData.altitude = bmp.readAltitude(1013.25);
      sensorData.bmpValid = true;
    } else {
      sensorData.bmpValid = false;
    }
  } else {
    sensorData.bmpValid = false;
  }
}

void updateGPS() {
  unsigned long startTime = millis();
  while (gpsSerial.available() > 0 && (millis() - startTime) < 100) {
    if (gps.encode(gpsSerial.read())) {
      gpsData.valid = gps.location.isValid();
      if (gpsData.valid) {
        gpsData.lat = gps.location.lat();
        gpsData.lng = gps.location.lng();
      }
      if (gps.altitude.isValid()) { 
        gpsData.altitude = gps.altitude.meters(); 
      }
      if (gps.satellites.isValid()) { 
        gpsData.satellites = gps.satellites.value(); 
      }
    }
  }
}

// =================================================================
// 状态发布
// =================================================================

void publishStatus() {
  // 为每个设备发布相同的传感器数据
  for (int i = 0; i < DEVICE_COUNT; i++) {
    StaticJsonDocument<768> doc;
    doc["device_id"] = DEVICE_IDS[i];
    doc["uptime"] = millis() / 1000;
    doc["version"] = "v4.2-multi";
    doc["timestamp"] = getCurrentTimeString();
    doc["ntp_synced"] = ntpSynced;
    
    JsonObject connection = doc.createNestedObject("connection");
    connection["wifi"] = (WiFi.status() == WL_CONNECTED);
    connection["mqtt"] = mqttClient.connected();
    
    JsonObject sensors = doc.createNestedObject("sensors");
    sensors["temperature"] = serialized(String(sensorData.temperature, 2));
    sensors["humidity"] = serialized(String(sensorData.humidity, 2));
    sensors["pressure"] = serialized(String(sensorData.pressure, 2));
    sensors["altitude"] = serialized(String(sensorData.altitude, 2));
    sensors["valid"] = sensorData.valid;
    sensors["bmp_valid"] = sensorData.bmpValid;
    
    JsonObject gps_obj = doc.createNestedObject("gps");
    gps_obj["valid"] = gpsData.valid;
    gps_obj["lat"] = serialized(String(gpsData.lat, 6));
    gps_obj["lng"] = serialized(String(gpsData.lng, 6));
    gps_obj["altitude"] = serialized(String(gpsData.altitude, 2));
    gps_obj["satellites"] = gpsData.satellites;
    
    char jsonBuffer[768];
    size_t len = serializeJson(doc, jsonBuffer);
    
    if (mqttClient.connected()) {
      mqttClient.publish(TOPIC_PUBLISH, jsonBuffer, len);
    }
    
    // 串口输出状态（用于调试）
    Serial.print("📤 ");
    Serial.println(jsonBuffer);
    
    delay(50);  // 短暂延迟避免消息堆积
  }
}

// =================================================================
// Setup
// =================================================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("\n============================================================");
  Serial.println("ESP32 传感器数据采集终端 v4.2 - 多设备模拟版");
  Serial.println("功能：WiFi自动重连、NTP时间同步、GPS/温湿度/气压数据采集、多设备MQTT发布");
  Serial.printf("模拟设备数量: %d\n", DEVICE_COUNT);
  Serial.println("============================================================\n");
  
  // 传感器初始化
  Wire.begin();
  if (sht4.begin()) {
    Serial.println("✓ SHT4x 温湿度传感器初始化成功");
  } else {
    Serial.println("✗ SHT4x 初始化失败");
  }
  
  if (bmp.begin(BMP280_ADDRESS)) {
    Serial.println("✓ BMP280 气压传感器初始化成功");
  } else {
    Serial.println("✗ BMP280 初始化失败");
  }
  
  // GPS 初始化
  gpsSerial.begin(9600, SERIAL_8N1, GPS_RX_PIN, GPS_TX_PIN);
  Serial.println("✓ GPS 模块初始化完成");
  
  // MQTT 客户端设置
  mqttClient.setServer(MQTT_SERVER, MQTT_PORT);
  mqttClient.setBufferSize(512);
  
  // WiFi 连接
  connectWiFi();
  
  // 如果WiFi已连接，立即尝试MQTT连接
  if (WiFi.status() == WL_CONNECTED) {
    mqttConnect();
  }
  
  Serial.println("\n🚀 系统启动完成\n");
}

// =================================================================
// Loop
// =================================================================

void loop() {
  // WiFi连接检查（非阻塞重连）
  bool wifiConnected = checkWiFiConnection();
  
  if (wifiConnected) {
    // MQTT连接检查（非阻塞重连）
    checkMqttConnection();
    
    // MQTT消息处理
    if (mqttClient.connected()) {
      mqttClient.loop();
    }
  }
  
  // 传感器数据更新
  updateSensors();
  updateGPS();
  
  // 状态发布
  unsigned long now = millis();
  if (now - lastStatusPublish >= STATUS_INTERVAL) {
    lastStatusPublish = now;
    publishStatus();
  }
  
  delay(10);
}
