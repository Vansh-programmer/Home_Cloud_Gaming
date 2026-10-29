#include <ESP8266WiFi.h>
#include <WiFiClientSecure.h>
#include <UniversalTelegramBot.h>
#include <ArduinoJson.h>

// ================= USER CONFIGURATION =================
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

#define BOT_TOKEN "YOUR_BOT_TOKEN_FROM_BOTFATHER"
#define CHAT_ID   "YOUR_NUMERIC_CHAT_ID"

// Pin D1 (GPIO 5) -> Motherboard PWR_SW(+) / SENSE
// ESP8266 GND     -> Motherboard PWR_SW(-) / GND
const int POWER_PIN = 5; 

const unsigned long CHECK_INTERVAL = 1500;
unsigned long lastChecked = 0;

WiFiClientSecure secured_client;
UniversalTelegramBot bot(BOT_TOKEN, secured_client);

// Emulate Open-Drain / High-Impedance switch
void pulsePower(int durationMs) {
  pinMode(POWER_PIN, OUTPUT);
  digitalWrite(POWER_PIN, LOW); // Pulls PWR_SW to GND (button pressed)
  delay(durationMs);
  pinMode(POWER_PIN, INPUT);    // High-Z floating (button released)
}

void handleNewMessages(int numNewMessages) {
  for (int i = 0; i < numNewMessages; i++) {
    String sender = String(bot.messages[i].chat_id);
    if (sender != CHAT_ID) {
      bot.sendMessage(sender, "Unauthorized", "");
      continue;
    }

    String text = bot.messages[i].text;
    text.toLowerCase();

    if (text == "/power" || text == "/on" || text == "power_on") {
      pulsePower(350); // 350ms pulse
      bot.sendMessage(CHAT_ID, "⚡ Power button pulsed. PC is turning ON!", "");
    } 
    else if (text == "/force_off") {
      pulsePower(5200); // 5.2s hold
      bot.sendMessage(CHAT_ID, "⚠️ Force power-off triggered (5s hold).", "");
    } 
    else if (text == "/status") {
      bot.sendMessage(CHAT_ID, "✓ ESP8266 direct switch online.", "");
    }
  }
}

void setup() {
  Serial.begin(115200);

  // Set pin to floating INPUT immediately so PC does not boot on ESP reset
  pinMode(POWER_PIN, INPUT);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");

  secured_client.setInsecure();
  bot.sendMessage(CHAT_ID, "⚡ ESP8266 Direct Switch Online & Ready!", "");
}

void loop() {
  if (millis() - lastChecked > CHECK_INTERVAL) {
    int numNewMessages = bot.getUpdates(bot.last_message_received + 1);
    while (numNewMessages) {
      handleNewMessages(numNewMessages);
      numNewMessages = bot.getUpdates(bot.last_message_received + 1);
    }
    lastChecked = millis();
  }
}

