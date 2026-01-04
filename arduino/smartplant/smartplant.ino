#include <DHT.h>
#include <SPI.h>
#include <SD.h>  

// --- Analogowe czujniki wilgotności gleby ---
#define SOIL_MAIN_PIN      A0     // roślinka 2
#define SOIL_OPT1_PIN      A1     // roślinka 1
#define SOIL_OPT2_PIN      A2     // roślinka 3
#define SOIL_OPT3_PIN      A3     // roślinka 4

// --- Czujnik poziomu wody (pływak) --- 
#define WATER_LEVEL_PIN    2      // 0 = mało wody, 1 = woda OK

// --- Fotorezystor (czujnik jasności) ---
#define LDR_PIN            A4  

// --- Czujnik temperatury i wilgotności powietrza ---
#define DHT_PIN            6
#define DHT_TYPE           DHT22
DHT dht(DHT_PIN, DHT_TYPE);

// --- Przekaźniki (pompy / wyjścia) ---
#define RELAY_MAIN_PIN     7      //  roślinka 3
#define RELAY_OPT1_PIN     8      //  roślinka 4
#define RELAY_OPT2_PIN     9      //  roślinka 2
#define RELAY_OPT3_PIN     10     // roślinka 1

// --- Dioda RGB ---
#define LED_R_PIN          11
#define LED_G_PIN          12
#define LED_B_PIN          13

// --- Bluetooth ---
#define BT_STATE_PIN       4
bool btConnected = false;

// --- SD karta ---
#define SD_CS_PIN          3 
bool sdOk                 = false; // czy SD działa

// --- Kalibracja czujnika gleby dla SOIL_OPT3_PIN - ROŚLINKA 1 (A1) ---
const int SOIL1_DRY       = 552;
const int SOIL1_WET       = 213;
const int SOIL1_THRESHOLD = 20;

// --- Kalibracja czujnika gleby dla SOIL_MAIN_PIN - ROŚLINKA 2 (A0)---
const int SOILM_DRY       = 558;
const int SOILM_WET       = 230;
const int SOILM_THRESHOLD = 10;

// --- Kalibracja czujnika gleby dla SOIL_OPT2_PIN - ROŚLINKA 3 (A2) ---
const int SOIL2_DRY       = 551;  // odczyt dla suchej ziemi
const int SOIL2_WET       = 220;  // odczyt dla wody
const int SOIL2_THRESHOLD = 10;   // próg wilgotności (%) poniżej którego podlewamy

// --- Kalibracja czujnika gleby dla SOIL_OPT3_PIN - ROŚLINKA 4 (A3) ---
const int SOIL3_DRY       = 556;
const int SOIL3_WET       = 215;
const int SOIL3_THRESHOLD = 30;

// --- Czasy działania systemu ---
const unsigned long WATERING_TIME_MS       = 4000;   // jak długo podlewać (ms)
const unsigned long GREEN_BLINK_DELAY      = 250;   // czas mignięcia zielonej diody
const unsigned long IDLE_DELAY_MS          = 60UL * 60UL * 1000UL;   // czas czuwania między cyklami  [1 h]
//const unsigned long IDLE_DELAY_MS        = 1UL * 60UL * 1000UL; // czas czuwania między cyklami  1 min TESTOWE POKAZOWE

// ==================== Funkcje pomocnicze LED ====================

// Wyłącza wszystkie kolory diody RGB - niezależnie od zapalonej diody
void ledsOff() {
  digitalWrite(LED_R_PIN, HIGH);
  digitalWrite(LED_G_PIN, HIGH);
  digitalWrite(LED_B_PIN, HIGH);
}

// Włącza czerwony (błąd / mało wody)
void ledRed() {
  ledsOff();
  digitalWrite(LED_R_PIN, LOW);
}

// Włącza żółty (podlewanie w toku)
void ledYellow() {
  ledsOff();
  digitalWrite(LED_R_PIN, LOW);
  digitalWrite(LED_G_PIN, LOW);
}

// Włącza zielony (OK)
void ledGreen() {
  ledsOff();
  digitalWrite(LED_G_PIN, LOW);
}

// Trzykrotne mignięcie zieloną diodą (potwierdzenie podlania)
void blinkGreen3x() {
  for (int i = 0; i < 3; i++) {
    ledGreen();
    delay(GREEN_BLINK_DELAY);
    ledsOff();
    delay(GREEN_BLINK_DELAY);
  }
}


// ==================== SD + Bluetooth – buforowanie ramek  ====================

// Wysyła zawartość /buffer.txt po BT i usuwa plik
void flushBufferToBt() {
  if (!sdOk) return;

  File f = SD.open("/buffer.txt", FILE_READ);
  if (!f) return;

  Serial.println("Wysyłam zbuforowane dane z SD...");

  while (f.available()) {
    String line = f.readStringUntil('\n');
    line.trim();
    if (line.length() > 0) {
      Serial1.println(line);
      Serial.print("BUF->BT: ");
      Serial.println(line);
    }
  }

  f.close();
  SD.remove("/buffer.txt");
  Serial.println("Bufor SD opróżniony.");
}

// Główna funkcja wysyłająca ramkę:
// - jeśli BT połączony -> wyślij + opróżnij bufor z SD
// - jeśli BT niepołączony -> dopisz do /buffer.txt
void sendOrBufferLine(const String &line) {
  if (btConnected) {
    // Najpierw starsze rzeczy z bufora, potem aktualna ramka
    if (sdOk) {
      flushBufferToBt();
    }
    Serial1.println(line);
    Serial.print("LIVE -> BT: ");
    Serial.println(line);
  } else if (sdOk) {
    File f = SD.open("/buffer.txt", FILE_WRITE);
    if (f) {
      f.println(line);
      f.close();
      Serial.print("LIVE -> SD BUF += ");
      Serial.println(line);
    } else {
      Serial.println("Błąd zapisu do /buffer.txt");
    }
  } else {
    // Awaryjnie – nie ma SD, ale próba wysłania po BT
    Serial1.println(line);
    Serial.print("AWARYJNIE -> BT (bez SD): ");
    Serial.println(line);
  }
}


// ==================== Odczyt warunków otoczenia ====================

// Czyta temperaturę, wilgotność powietrza i jasność (LDR)
void readEnvironment(int &lightRaw) {
  float airHumidity = dht.readHumidity();
  float airTemp = dht.readTemperature();

  bool envOk = true;  // zakładamy, że jest ok, dopóki nie wykryjemy błędu

  if (isnan(airHumidity) || isnan(airTemp)) {
    envOk = false;
    Serial.println("Błąd odczytu z czujnika DHT22.");
  } else {
    Serial.print("Temperatura: ");
    Serial.print(airTemp);
    Serial.print(" °C   Wilgotność powietrza: ");
    Serial.print(airHumidity);
    Serial.println(" %");
  }

  lightRaw = analogRead(LDR_PIN);
  Serial.print("Jasność (LDR): ");
  Serial.println(lightRaw);

// *** RAMKA DLA PY + buforowanie na SD ***
  String frame = "@ENV;";
  frame += "ok=";
  frame += envOk ? "1" : "0";

  frame += ";temp=";
  if (envOk) frame += String(airTemp);
  else       frame += "NaN";

  frame += ";hum=";
  if (envOk) frame += String(airHumidity);
  else       frame += "NaN";

  frame += ";light=";
  frame += String(lightRaw);

  // timestamp z millis()
  frame += ";t=";
  frame += String(millis());

  sendOrBufferLine(frame);
}


// ==================== Logika dla pojedynczej roślinki ====================

void sendPlantFrame(const char* plantName,
                    int soilRaw,
                    int soilMoisture,
                    int thresholdPercent,
                    int waterState,
                    bool needWater,
                    bool watered) {
  //  budujemy String i wysyłamy/buforujemy ***
  String frame = "@PLANT;";
  frame += "name=";
  frame += plantName;

  frame += ";soilRaw=";
  frame += String(soilRaw);

  frame += ";soil=";
  frame += String(soilMoisture);

  frame += ";threshold=";
  frame += String(thresholdPercent);

  frame += ";needWater=";
  frame += needWater ? "1" : "0";

  frame += ";waterState=";
  frame += String(waterState);

  frame += ";watered=";
  frame += watered ? "1" : "0";

  frame += ";t=";
  frame += String(millis());

  sendOrBufferLine(frame);
}

// Obsługuje proces podlewania dla jednej rośliny:
// - odczyt gleby
// - decyzja czy podlewać
// - sprawdzenie poziomu wody
// - sterowanie przekaźnikiem i LED
void processPlant(
  int soilPin,
  int relayPin,
  const char* plantName,
  int dryValue,
  int wetValue,
  int thresholdPercent
) {
  Serial.print("-------[");
  Serial.print(plantName);
  Serial.println("]-------");

  // Zmienne do logiki i do ramki
  int soilRaw = analogRead(soilPin);
  int soilMoisture = map(soilRaw, dryValue, wetValue, 0, 100);
  soilMoisture = constrain(soilMoisture, 0, 100);

  int waterState = -1;        // -1 = nie sprawdzono
  bool needWater = false;     // czy gleba jest poniżej progu
  bool watered   = false;     // czy pompka była faktycznie włączona

  Serial.print("[");
  Serial.print(plantName);
  Serial.print("] Surowy odczyt gleby: ");
  Serial.print(soilRaw);
  Serial.print("   Wilgotność gleby: ");
  Serial.print(soilMoisture);
  Serial.println(" %");

  // Decyzja, czy w ogóle rozważać podlewanie
  if (soilMoisture < thresholdPercent) {
    needWater = true;
    Serial.print("[");
    Serial.print(plantName);
    Serial.println("] Gleba sucha – sprawdzam poziom wody.");
  } else {
    needWater = false; // !!! Można usunąć?
    Serial.print("[");
    Serial.print(plantName);
    Serial.println("] Gleba jest wystarczająco wilgotna. Nie podlewam.");
  }

  // Jeśli nie trzeba podlewać – pomijamy resztę
  if (!needWater) {
    // Ramka ok: waterState = -1, watered = 0
    sendPlantFrame(plantName, soilRaw, soilMoisture, thresholdPercent,
                   waterState, needWater, watered);
    return;
  }

  // Wiemy, że jest sucho -> sprawdzamy pływak
  waterState = digitalRead(WATER_LEVEL_PIN);   // 0 = mało wody, 1 = woda OK
  Serial.print("Poziom wody (pływak): ");
  Serial.println(waterState == 1 ? "Woda OK" : "Mało wody");

  // Jeśli za mało wody w zbiorniku
  if (waterState == 0) {
    Serial.print("[");
    Serial.print(plantName);
    Serial.println("] ZA MAŁO WODY W ZBIORNIKU! Podlewanie zatrzymane.");
    ledRed();
    delay(2000);
    ledsOff();

    // Ramka brak wody: needWater=1, waterState=0, watered=0
    sendPlantFrame(plantName, soilRaw, soilMoisture, thresholdPercent,
                   waterState, needWater, watered);
    return;
  }

  // Jest sucho i woda w zbiorniku -> podlewamy
  Serial.print("[");
  Serial.print(plantName);
  Serial.println("] Poziom wody OK – rozpoczynam podlewanie.");

  ledYellow();
  digitalWrite(relayPin, LOW);     // włącz pompę
  delay(WATERING_TIME_MS);
  digitalWrite(relayPin, HIGH);    // wyłącz pompę
  ledsOff();

  Serial.print("[");
  Serial.print(plantName);
  Serial.println("] Podlewanie zakończone.");

  Serial.print("[");
  Serial.print(plantName);
  Serial.println("] Sygnał potwierdzenia (zielone 3x).");
  blinkGreen3x();

  watered = true;

  // Ramka podlane: needWater=1, waterState=1, watered=1
  sendPlantFrame(plantName, soilRaw, soilMoisture, thresholdPercent,
                 waterState, needWater, watered);
}


// ==================== SETUP ====================

void setup() {
  delay(500);
  Serial.begin(9600); // USB -> Serial Monitor
  Serial1.begin(9600); // HC-05 (bluetooth)

   // --- SD karta
  Serial.println("Inicjalizacja karty SD...");
  if (SD.begin(SD_CS_PIN)) {
    sdOk = true;
    Serial.println("Karta SD OK.");
  } else {
    sdOk = false;
    Serial.println("KARTA SD NIE DZIAŁA – logi tylko po BT.");
  }

  // Ustawienie pinów przekaźników jako wyjścia i wyłączenie ich na start
  pinMode(RELAY_MAIN_PIN, OUTPUT);
  pinMode(RELAY_OPT1_PIN, OUTPUT);
  pinMode(RELAY_OPT2_PIN, OUTPUT);
  pinMode(RELAY_OPT3_PIN, OUTPUT);

  digitalWrite(RELAY_MAIN_PIN, HIGH);
  digitalWrite(RELAY_OPT1_PIN, HIGH);
  digitalWrite(RELAY_OPT2_PIN, HIGH);
  digitalWrite(RELAY_OPT3_PIN, HIGH);

  // Ustawienie pinów diody RGB jako wyjścia
  pinMode(LED_R_PIN, OUTPUT);
  pinMode(LED_G_PIN, OUTPUT);
  pinMode(LED_B_PIN, OUTPUT);
  ledsOff();

  // Ustawienie pływaka
  pinMode(WATER_LEVEL_PIN, INPUT_PULLUP);

  // Start czujnika DHT
  dht.begin();

  // Ustawienie pinu dla stanu bluetooth
  pinMode(BT_STATE_PIN, INPUT);

}

// ==================== LOOP ====================

void loop() {
  btConnected = digitalRead(BT_STATE_PIN) == HIGH;
  int lightRaw = 0;

  Serial.println("--------------------------------------");
  Serial.println("NOWY CYKL – odczyt warunków otoczenia:");

  // Odczyt temperatury, wilgotności powietrza i jasności
  readEnvironment(lightRaw);

  // Roślinka 1
  processPlant(
    SOIL_OPT1_PIN,
    RELAY_OPT3_PIN,
    "Roślinka 1",
    SOIL1_DRY,
    SOIL1_WET,
    SOIL1_THRESHOLD
  );

  // Roślinka 2
  processPlant(
    SOIL_MAIN_PIN,
    RELAY_OPT2_PIN,
    "Roślinka 2",
    SOILM_DRY,
    SOILM_WET,
    SOILM_THRESHOLD
  );
 // Roślinka 3
  processPlant(
    SOIL_OPT2_PIN,
    RELAY_MAIN_PIN,
    "Roślinka 3",
    SOIL2_DRY,
    SOIL2_WET,
    SOIL2_THRESHOLD
  );

  // Roślinka 4
  processPlant(
    SOIL_OPT3_PIN,
    RELAY_OPT1_PIN,
    "Roślinka 4",
    SOIL3_DRY,
    SOIL3_WET,
    SOIL3_THRESHOLD
  );

  // Roślinka testowa do pokazu
  // processPlant(
  //   SOIL_OPT2_PIN,
  //   RELAY_MAIN_PIN,
  //   "Roślinka Testowa",
  //   SOIL2_DRY,
  //   SOIL2_WET,
  //   SOIL2_THRESHOLD
  // );


  Serial.println("Czuwanie...");
  delay(IDLE_DELAY_MS);
}
