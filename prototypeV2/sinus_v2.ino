#include "Wire.h"
#include <ScioSense_ENS16x.h>
#include <Adafruit_SGP41.h>
#include <SparkFun_SCD4x_Arduino_Library.h>

// ------------------ MUX + BOARD ------------------
const byte MUX_ADDR   = 0x70;
const int  ENABLE_PIN = 12; // VP_DRUM
const int TGS2602_PIN = A5;
const int MQ3_PIN     = A4;

// MUX channels
const byte CH_ENS160 = 1;   // found 0x52
const byte CH_SGP41  = 4;   // found 0x59
const byte CH_SCD40  = 6;   // found 0x62

void selectMux(byte ch) {
  Wire.beginTransmission(MUX_ADDR);
  Wire.write(1 << ch);
  Wire.endTransmission();
  delay(5);
}

// ------------------ VARIABLE SET UP ------------------
String python_communication;
String arduino_communication;
String s;
char c;

// ENS160 declarations
ENS160 ens160;
String ens160_measure(void);
String ens160_output;

//SGP41 declarations
Adafruit_SGP41 sgp41;
String sgp41_measure(void);
String sgp41_output;
uint16_t conditioning_s = 10;

// TGS2602 declarations
String tgs2602_measure(void);
String tgs2602_output;

// SCD declarations
SCD4x scd40;
String scd40_measure(void);
String scd40_output;

// MQ3 declarations
String mq3_measure(void);
String mq3_output;

String output;

// ------------------ MEASURE FUNCTIONS ------------------
//ENS160 measure
String ens160_measure() {
  selectMux(CH_ENS160);

  if (ens160.update() == RESULT_OK) {
    if (ens160.hasNewGeneralPurposeData()) {
      ens160_output = String(ens160.getRs0()) + "," +
                String(ens160.getRs1()) + "," +
                String(ens160.getRs2()) + "," +
                String(ens160.getRs3());
    } else {
      ens160_output = "No new data,,,";
    }
  } else {
    ens160_output = "ENS160 update failed,,,";
  }
  return ens160_output;
}

// SGP41 measure
String sgp41_measure() {
  selectMux(CH_SGP41);
  uint16_t srawVoc = 0;
  uint16_t srawNox = 0;

  if (conditioning_s > 0) {
    if (sgp41.executeConditioning(&srawVoc, 50.0, 25.0)) {
      conditioning_s--;
      delay(SGP41_CONDITIONING_DELAY_MS);
      sgp41_output = String(srawVoc) + ",0";
    } else {
      sgp41_output = "SGP41 conditioning failed";
    }
  } else {
    if (sgp41.measureRawSignals(&srawVoc, &srawNox, 50.0, 25.0)) {
      sgp41_output = String(srawVoc) + "," + String(srawNox);
    } else {
      sgp41_output = "SGP41 measure failed";
    }
  }
  return sgp41_output;
}

// TGS2602 measure
String tgs2602_measure() {
  int sensorValue = analogRead(TGS2602_PIN);
  float voltage = (sensorValue / 1023.0) * 5; // ADC to voltage
  if (sensorValue <= 0) {
    tgs2602_output = "-";
  } else {
    float sensorResistance = ((5 - voltage) / voltage) * 10000;  // Calculate sensor resistance
    tgs2602_output = String(sensorResistance);
  }  
  return tgs2602_output;
}

// SCD40 measure
String scd40_measure() {
  selectMux(CH_SCD40);
  
  if (scd40.readMeasurement()) {
    uint16_t co2 = scd40.getCO2();
    float temperature = scd40.getTemperature();
    float humidity = scd40.getHumidity();

    if (co2 == 0) {
      scd40_output = "Invalid sample detected, skipping,,";
    } else {
      scd40_output = String(co2) + "," +
                     String(temperature) + "," +
                     String(humidity);
    }
  } else {
    scd40_output = "SCD40 no new data,,";
  }

  return scd40_output;
}

// MQ3 measure
String mq3_measure() {
  int sensorValue = analogRead(MQ3_PIN);
  float voltage = (sensorValue / 1023.0) * 5; // ADC to voltage
  if (sensorValue <= 0) {
    mq3_output = "-";
  } else {
    float sensorResistance = ((5 - voltage) / voltage) * 10000;  // Calculate sensor resistance
    mq3_output = String(sensorResistance);
  }  
  return mq3_output;
}

// ------------------ SETUP ------------------
void setup() {

  Wire.begin();
  Wire.setWireTimeout(3000, true);

  Serial.begin(115200);
  delay(1000);

  pinMode(ENABLE_PIN, OUTPUT);
  digitalWrite(ENABLE_PIN, HIGH);
  Serial.println("D12 set HIGH (power to mux)");

  // ENS160 setup
  selectMux(CH_ENS160);
  ens160.begin(&Wire, 0x52);
  Serial.println("ENS160 initializing...");
  while (ens160.init() != true) {
    Serial.print(".");
    delay(1000);
  }
  Serial.println("ENS160 init success");
  ens160.startStandardMeasure();

  // SGP41 setup
  selectMux(CH_SGP41);
  if (!sgp41.begin()) {
    Serial.println("SGP41 init failed");
  } else {
    Serial.println("SGP41 detected");
    if (sgp41.executeSelfTest()) {
      Serial.println("SGP41 self-test passed");
  } else {
      Serial.println("SGP41 self-test failed");
  }
  }

  // SCD40 setup
  selectMux(CH_SCD40);
  Serial.println("SCD40 initializing...");
  if (scd40.begin() == false) {
    Serial.println("SCD40 init failed");
  } else {
    Serial.println("SCD40 init success");
  }

  Serial.println("Setup complete.");
  Serial.println();
}
// ------------------------------------------------------------
void loop() {
  python_communication = "";
  arduino_communication = "";

  Serial.print("_");
  while (!Serial.available()) {
    delay(10);
  }

  s = "";

  while (Serial.available()) {
    c = Serial.read();
    s = s + c;
  }

  Serial.println(s);

  //Measurements
  ens160_output = ens160_measure();
  delay(3);

  sgp41_output = sgp41_measure();
  delay(3);

  tgs2602_output = tgs2602_measure();
  delay(3);

  scd40_output = scd40_measure();
  delay(3);

  mq3_output = mq3_measure();
  delay(3);

  python_communication = ens160_output + "," + sgp41_output + "," + tgs2602_output + "," + scd40_output + "," + mq3_output + "!";
  Serial.println(python_communication);
  delay(3);
}